"""Pydantic schemas: performance and returns."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.report import PortfolioValuationMetadata

IncomeBasis = Literal["net", "gross"]
CostBasis = Literal["exclude", "include"]


class PerformanceMetadata(BaseModel):
    """Explicit calculation bases used for each response."""

    income_basis: IncomeBasis
    cost_basis: CostBasis
    trade_costs_scope: str
    recurring_costs_scope: str
    metric_bases: dict[str, str]


class PerformanceMetrics(BaseModel):
    security_id: int
    ticker: str
    simple_return: Decimal | None
    total_return: Decimal | None
    money_weighted_return: Decimal | None
    yield_on_cost: Decimal | None
    current_yield: Decimal | None
    realized_gain_loss: Decimal
    total_income_received: Decimal
    metadata: PerformanceMetadata


class PortfolioPerformance(BaseModel):
    total_invested: Decimal
    total_current_value: Decimal
    total_return: Decimal | None
    total_return_annualized: Decimal | None = None
    time_weighted_return: Decimal | None = None
    time_weighted_return_annualized: Decimal | None = None
    # MWR/XIRR is already an annual rate by definition; do not annualize it again
    # (specification §9.4, §9.5.1).
    money_weighted_return: Decimal | None = None
    investment_period_days: int | None = None
    total_realized_gain_loss: Decimal
    total_income_received: Decimal
    by_security: list[PerformanceMetrics]
    metadata: PerformanceMetadata
    portfolio_valuation: PortfolioValuationMetadata = Field(
        default_factory=PortfolioValuationMetadata
    )
