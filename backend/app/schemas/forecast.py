"""Pydantic schemas: ForecastScenario."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ForecastContribution(BaseModel):
    date: dt.date
    amount: Decimal  # Positive = contribution, negative = withdrawal.
    label: str


class ForecastCashFlowParams(BaseModel):
    monthly_income: Decimal
    monthly_expenses: Decimal
    income_growth_rate_annual: Decimal = Decimal("0")
    expense_growth_rate_annual: Decimal = Decimal("0")
    monthly_savings_to_invest: Decimal | None = None  # None = automatic (income minus expenses).


class ForecastPortfolioParams(BaseModel):
    """Expected returns for the three scenarios. expected_annual_return includes price changes
    and reinvested distributions. The v1.0 model cannot separate dividends; independent
    distribution controls would require a separate dividend-yield input.
    """

    expected_annual_return: Decimal
    return_optimistic: Decimal
    return_pessimistic: Decimal


class ForecastScenarioParameters(BaseModel):
    """Structure of ForecastScenario's parameters JSON field."""

    starting_net_worth: Literal["auto"] | Decimal = Field(
        default="auto",
        description="'auto' reads actual account balances and portfolio value separately from the database "
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


class ForecastScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    base_date: dt.date
    horizon_years: int = Field(..., ge=1, le=50)
    parameters: ForecastScenarioParameters


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
