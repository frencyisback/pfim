"""Service: ForecastService. Resolve automatic scenario parameters from actual database balances
and positions, then delegate to the pure app.finance.forecast.run_forecast_scenario
calculation.
"""

from __future__ import annotations

import json
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.finance.forecast import run_forecast_scenario
from app.models.forecast_scenario import ForecastScenario
from app.repositories.forecast_repo import ForecastRepository
from app.schemas.forecast import (
    ForecastRunResult,
    ForecastScenarioCreate,
    ForecastScenarioParameters,
    ScenarioProjectionRead,
    YearProjectionRead,
)
from app.services.account_service import AccountService
from app.services.portfolio_service import PortfolioService
from app.utils.errors import NotFoundError, ValidationErrorPFIM


class ForecastService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ForecastRepository(db)
        self.account_service = AccountService(db)
        self.portfolio_service = PortfolioService(db)

    def list_scenarios(self) -> list[ForecastScenario]:
        return self.repo.list()

    def get_scenario(self, scenario_id: int) -> ForecastScenario:
        scenario = self.repo.get(scenario_id)
        if scenario is None:
            raise NotFoundError(
                f"Scenario {scenario_id} not found", detail={"scenario_id": scenario_id}
            )
        return scenario

    def create_scenario(self, data: ForecastScenarioCreate) -> ForecastScenario:
        scenario = ForecastScenario(
            name=data.name,
            description=data.description,
            base_date=data.base_date,
            horizon_years=data.horizon_years,
            parameters=data.parameters.model_dump_json(),
        )
        return self.repo.add(scenario)

    def delete_scenario(self, scenario_id: int) -> None:
        self.get_scenario(scenario_id)
        self.repo.delete(scenario_id)

    def to_read_dict(self, scenario: ForecastScenario) -> dict:
        return {
            "id": scenario.id,
            "name": scenario.name,
            "description": scenario.description,
            "base_date": scenario.base_date,
            "horizon_years": scenario.horizon_years,
            "parameters": json.loads(scenario.parameters),
            "created_at": scenario.created_at,
            "updated_at": scenario.updated_at,
        }

    def _resolve_starting_values(
        self, parameters: ForecastScenarioParameters
    ) -> tuple[Decimal, Decimal]:
        """Return (starting_cash_balance, starting_portfolio_value). For auto, read cash balances
        of active accounts and current portfolio value separately: only the portfolio earns
        simulated returns. An explicit starting-net-worth value is entirely starting cash,
        because a single number cannot determine its allocation.
        """
        starting = parameters.starting_net_worth
        if starting == "auto":
            accounts = self.account_service.list_accounts(only_active=True)
            total_cash = sum(
                (self.account_service.get_balance(a.id).balance for a in accounts), Decimal("0")
            )
            portfolio_summary = self.portfolio_service.get_summary()
            return total_cash, portfolio_summary.total_current_value
        return starting, Decimal("0")

    def _validated_parameters(self, scenario: ForecastScenario) -> ForecastScenarioParameters:
        """Validate historical scenarios without rewriting their stored JSON."""
        try:
            return ForecastScenarioParameters.model_validate_json(scenario.parameters)
        except ValidationError as exc:
            fields = [
                ".".join(["parameters", *(str(part) for part in error["loc"])])
                for error in exc.errors()
            ]
            raise ValidationErrorPFIM(
                f"Scenario {scenario.id} ({scenario.name}) cannot run: "
                f"invalid parameters in {', '.join(fields)}",
                detail={"scenario_id": scenario.id, "fields": fields},
            ) from exc

    def run_scenario(self, scenario_id: int) -> ForecastRunResult:
        scenario = self.get_scenario(scenario_id)
        return self._run_validated_scenario(scenario, self._validated_parameters(scenario))

    def _run_validated_scenario(
        self, scenario: ForecastScenario, parameters: ForecastScenarioParameters
    ) -> ForecastRunResult:
        starting_cash, starting_portfolio = self._resolve_starting_values(parameters)
        cash_flow = parameters.cash_flow
        portfolio = parameters.portfolio

        engine_params = dict(
            horizon_years=scenario.horizon_years,
            base_date=scenario.base_date,
            starting_cash_balance=starting_cash,
            starting_portfolio_value=starting_portfolio,
            monthly_income=cash_flow.monthly_income,
            monthly_expenses=cash_flow.monthly_expenses,
            income_growth_rate_annual=cash_flow.income_growth_rate_annual,
            expense_growth_rate_annual=cash_flow.expense_growth_rate_annual,
            expected_annual_return=portfolio.expected_annual_return,
            return_optimistic=portfolio.return_optimistic,
            return_pessimistic=portfolio.return_pessimistic,
            monthly_savings_to_invest=cash_flow.monthly_savings_to_invest,
            contributions=[(c.date, c.amount) for c in parameters.contributions],
        )

        result = run_forecast_scenario(engine_params)

        scenarios_read = {
            name: ScenarioProjectionRead(
                scenario=proj.scenario,
                years=[
                    YearProjectionRead(
                        year_index=y.year_index,
                        date=y.date,
                        portfolio_value=y.portfolio_value,
                        cash_balance=y.cash_balance,
                        net_worth=y.net_worth,
                        annual_cash_flow=y.annual_cash_flow,
                        annual_income=y.annual_income,
                        annual_expenses=y.annual_expenses,
                    )
                    for y in proj.years
                ],
                milestones_reached=proj.milestones_reached,
            )
            for name, proj in result.scenarios.items()
        }

        return ForecastRunResult(
            scenario_id=scenario.id, scenario_name=scenario.name, scenarios=scenarios_read
        )

    def compare_scenarios(self, scenario_ids: list[int]) -> list[ForecastRunResult]:
        if len(scenario_ids) < 2:
            raise ValidationErrorPFIM("At least 2 scenarios are required for comparison")
        scenarios = [self.get_scenario(sid) for sid in scenario_ids]
        validated = [(scenario, self._validated_parameters(scenario)) for scenario in scenarios]
        return [self._run_validated_scenario(scenario, params) for scenario, params in validated]
