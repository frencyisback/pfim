"""Pydantic schemas: portfolio positions."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.report import PortfolioValuationMetadata


class PositionLot(BaseModel):
    """A purchase lot still held, in whole or in part, under FIFO."""

    trade_id: int
    date: str
    quantity_remaining: Decimal
    unit_cost: Decimal


class PositionRead(BaseModel):
    """Open position expressed in both native and EUR values. Unsuffixed fields use the
    security's quoted currency; _eur fields use values frozen when trades and prices were
    entered. Display native values and aggregate EUR values; adding different native
    currencies is meaningless.
    """

    security_id: int
    ticker: str
    name: str
    quantity: Decimal
    currency: str

    # --- Security's native currency ---
    average_cost: Decimal
    total_invested: Decimal
    current_price: Decimal | None
    current_value: Decimal | None
    unrealized_gain_loss: Decimal | None
    # Price change alone, excluding exchange-rate effects.
    unrealized_gain_loss_pct: Decimal | None

    # --- EUR equivalent ---
    average_cost_eur: Decimal
    total_invested_eur: Decimal
    current_price_eur: Decimal | None
    current_value_eur: Decimal | None
    unrealized_gain_loss_eur: Decimal | None
    # Actual return for a EUR investor, including exchange-rate effects. Differs from the
    # native percentage when the rate changes between purchase and today.
    #
    unrealized_gain_loss_pct_eur: Decimal | None
    realized_gain_loss: Decimal  # Always EUR: feeds the tax register.

    current_price_date: dt.date | None
    valuation_source: Literal["market_price", "fifo_cost"]
    lots: list[PositionLot]


class PortfolioSummary(BaseModel):
    total_invested: Decimal
    total_current_value: Decimal
    total_unrealized_gain_loss: Decimal
    total_realized_gain_loss: Decimal
    positions_count: int
    allocation_by_type: dict[str, Decimal]
    portfolio_valuation: PortfolioValuationMetadata = Field(
        default_factory=PortfolioValuationMetadata
    )
