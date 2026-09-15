"""Net-worth projection engine for base, optimistic, and pessimistic scenarios. This pure module
has no database dependencies: ForecastService must resolve automatic values before calling it.
Initial wealth is tracked separately as cash and invested assets; only the portfolio earns
returns, and uninvested cash earns no interest in v1.0. Positive annual cash flow is invested;
deficits reduce cash without automatic portfolio sales. expected_annual_return is total
return, including reinvested distributions. Separately paid dividends would require an
explicit annual dividend yield input. Extraordinary contributions are applied in full at the
end of (previous anniversary, current anniversary]; the base date is already included in
starting wealth.
"""

from __future__ import annotations

import datetime as dt
from calendar import monthrange
from dataclasses import dataclass, field
from decimal import Decimal

DEFAULT_MILESTONES = [
    Decimal("100000"),
    Decimal("250000"),
    Decimal("500000"),
    Decimal("1000000"),
    Decimal("2000000"),
]


@dataclass
class YearProjection:
    year_index: int  # 1, 2, 3, ... horizon_years
    date: dt.date
    portfolio_value: Decimal
    cash_balance: Decimal
    net_worth: Decimal
    annual_cash_flow: Decimal
    annual_income: Decimal
    annual_expenses: Decimal


@dataclass
class ScenarioProjection:
    scenario: str  # 'pessimistic' | 'base' | 'optimistic'
    years: list[YearProjection] = field(default_factory=list)
    milestones_reached: dict[str, int] = field(default_factory=dict)  # "500000" -> year_index


@dataclass
class ForecastResult:
    scenarios: dict[str, ScenarioProjection]


def _simulate_scenario(
    scenario_name: str,
    horizon_years: int,
    base_date: dt.date,
    starting_cash_balance: Decimal,
    starting_portfolio_value: Decimal,
    monthly_income: Decimal,
    monthly_expenses: Decimal,
    income_growth_rate_annual: Decimal,
    expense_growth_rate_annual: Decimal,
    annual_return_rate: Decimal,
    contributions: list[tuple[dt.date, Decimal]],
    monthly_savings_override: Decimal | None,
    milestones: list[Decimal],
) -> ScenarioProjection:
    cash_balance = starting_cash_balance
    portfolio_value = starting_portfolio_value
    current_monthly_income = monthly_income
    current_monthly_expenses = monthly_expenses

    years: list[YearProjection] = []
    milestones_reached: dict[str, int] = {}
    milestones_pending = sorted(milestones)
    previous_date = base_date

    for year_index in range(1, horizon_years + 1):
        year = base_date.year + year_index
        year_date = dt.date(
            year, base_date.month, min(base_date.day, monthrange(year, base_date.month)[1])
        )

        annual_income = current_monthly_income * 12
        annual_expenses = current_monthly_expenses * 12
        annual_cash_flow = annual_income - annual_expenses

        if monthly_savings_override is not None:
            invested_this_year = monthly_savings_override * 12
            cash_balance += annual_cash_flow - invested_this_year
        elif annual_cash_flow >= 0:
            invested_this_year = annual_cash_flow
        else:
            invested_this_year = Decimal("0")
            cash_balance += annual_cash_flow  # Deficit absorbed by cash reserves.

        year_contributions = sum(
            (amount for c_date, amount in contributions if previous_date < c_date <= year_date),
            Decimal("0"),
        )

        portfolio_value = (
            portfolio_value * (1 + annual_return_rate) + invested_this_year + year_contributions
        )

        net_worth = portfolio_value + cash_balance

        years.append(
            YearProjection(
                year_index=year_index,
                date=year_date,
                portfolio_value=portfolio_value,
                cash_balance=cash_balance,
                net_worth=net_worth,
                annual_cash_flow=annual_cash_flow,
                annual_income=annual_income,
                annual_expenses=annual_expenses,
            )
        )

        while milestones_pending and net_worth >= milestones_pending[0]:
            reached = milestones_pending.pop(0)
            milestones_reached[str(reached)] = year_index

        current_monthly_income *= 1 + income_growth_rate_annual
        current_monthly_expenses *= 1 + expense_growth_rate_annual
        previous_date = year_date

    return ScenarioProjection(
        scenario=scenario_name, years=years, milestones_reached=milestones_reached
    )


def run_forecast_scenario(scenario_parameters: dict) -> ForecastResult:
    """Project net worth over horizon_years for pessimistic, base, and optimistic scenarios.
    scenario_parameters contains resolved values: horizon_years, base_date,
    starting_cash_balance, starting_portfolio_value, monthly_income, monthly_expenses,
    income_growth_rate_annual, expense_growth_rate_annual, expected_annual_return,
    return_optimistic, return_pessimistic, monthly_savings_to_invest, contributions, and
    milestones. Rates are fractions (0.02 = 2% annually). None savings means automatic income
    minus expenses; None milestones uses DEFAULT_MILESTONES. Contributions are (date, Decimal)
    pairs.
    """
    milestones = scenario_parameters.get("milestones") or DEFAULT_MILESTONES

    common_kwargs = dict(
        horizon_years=scenario_parameters["horizon_years"],
        base_date=scenario_parameters["base_date"],
        starting_cash_balance=scenario_parameters["starting_cash_balance"],
        starting_portfolio_value=scenario_parameters["starting_portfolio_value"],
        monthly_income=scenario_parameters["monthly_income"],
        monthly_expenses=scenario_parameters["monthly_expenses"],
        income_growth_rate_annual=scenario_parameters["income_growth_rate_annual"],
        expense_growth_rate_annual=scenario_parameters["expense_growth_rate_annual"],
        contributions=scenario_parameters.get("contributions", []),
        monthly_savings_override=scenario_parameters.get("monthly_savings_to_invest"),
        milestones=milestones,
    )

    scenarios = {
        "pessimistic": _simulate_scenario(
            "pessimistic",
            annual_return_rate=scenario_parameters["return_pessimistic"],
            **common_kwargs,
        ),
        "base": _simulate_scenario(
            "base",
            annual_return_rate=scenario_parameters["expected_annual_return"],
            **common_kwargs,
        ),
        "optimistic": _simulate_scenario(
            "optimistic",
            annual_return_rate=scenario_parameters["return_optimistic"],
            **common_kwargs,
        ),
    }

    return ForecastResult(scenarios=scenarios)
