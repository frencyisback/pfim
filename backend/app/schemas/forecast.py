"""Pydantic schemas: ForecastScenario."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ForecastContribution(BaseModel):
    date: dt.date
    amount: Decimal  # Positive = contribution, negative = withdrawal.
    label: str


class ForecastCashFlowParams(BaseModel):
    monthly_income: Decimal = Field(ge=0)
    monthly_expenses: Decimal = Field(ge=0)
    income_growth_rate_annual: Decimal = Field(default=Decimal("0"), ge=-1)
    expense_growth_rate_annual: Decimal = Field(default=Decimal("0"), ge=-1)
    monthly_savings_to_invest: Decimal | None = None  # None = automatic (income minus expenses).


class ForecastPortfolioParams(BaseModel):
    """Expected returns for the three scenarios. expected_annual_return includes price changes
    and reinvested distributions. The v1.0 model cannot separate dividends; independent
    distribution controls would require a separate dividend-yield input.
    """

    expected_annual_return: Decimal = Field(ge=-1)
    return_optimistic: Decimal = Field(ge=-1)
    return_pessimistic: Decimal = Field(ge=-1)

    @model_validator(mode="after")
    def check_return_order(self):
        if not self.return_pessimistic <= self.expected_annual_return <= self.return_optimistic:
            raise ValueError(
                "The base return must lie between the pessimistic and optimistic returns"
            )
        return self


class ForecastScenarioParameters(BaseModel):
    """Structure of ForecastScenario's parameters JSON field."""

    starting_net_worth: Literal["auto"] | Decimal = Field(
        default="auto",
        description="'auto' reads account balances and portfolio value on the scenario base date "
        "(only the portfolio earns returns). An explicit numeric value "
        "is treated entirely as starting cash with no initial portfolio: "
        "the simulation cannot infer the user's preferred allocation.",
    )
    cash_flow: ForecastCashFlowParams
    portfolio: ForecastPortfolioParams
    contributions: list[ForecastContribution] = Field(default_factory=list)

    @field_validator("starting_net_worth", mode="before")
    @classmethod
    def validate_starting_net_worth(cls, value):
        if value == "auto":
            return value
        message = "Starting net worth must be 'auto' or a finite number"
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise ValueError(message)
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(message) from exc
        if not amount.is_finite():
            raise ValueError(message)
        return amount

    def base_date_error(self, base_date: dt.date, horizon_years: int) -> str | None:
        if self.starting_net_worth == "auto" and base_date > dt.date.today():
            return "Choose a numeric starting net worth for a future base date"
        if base_date.year + horizon_years > dt.date.max.year:
            return "The final projection anniversary must be within the supported calendar"
        return None


class ForecastScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    base_date: dt.date
    horizon_years: int = Field(..., ge=1, le=50)
    parameters: ForecastScenarioParameters

    @model_validator(mode="after")
    def check_base_date(self):
        message = self.parameters.base_date_error(self.base_date, self.horizon_years)
        if message:
            raise ValueError(message)
        return self


class ForecastScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    base_date: dt.date
    horizon_years: int
    parameters: dict  # Deserialized from JSON for the response.
    created_at: dt.datetime
    updated_at: dt.datetime | None


class YearProjectionRead(BaseModel):
    year_index: int
    date: dt.date
    portfolio_value: Decimal
    cash_balance: Decimal
    net_worth: Decimal
    annual_cash_flow: Decimal
    annual_income: Decimal
    annual_expenses: Decimal


class ScenarioProjectionRead(BaseModel):
    scenario: str
    years: list[YearProjectionRead]
    milestones_reached: dict[str, int]


class ForecastRunResult(BaseModel):
    scenario_id: int
    scenario_name: str
    scenarios: dict[str, ScenarioProjectionRead]


class ForecastCompareRequest(BaseModel):
    scenario_ids: list[int] = Field(..., min_length=2)


class ForecastCompareResult(BaseModel):
    results: list[ForecastRunResult]
