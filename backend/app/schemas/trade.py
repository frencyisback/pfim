"""Pydantic schemas: Trade, TradeCost."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import fx_rate_description
from app.utils.numeric_limits import (
    FX_RATE_MAX,
    FX_RATE_MIN,
    NUMERIC_18_6_MAX,
    NUMERIC_18_6_MIN_POSITIVE,
    PRICE_MAX,
    PRICE_MIN,
)

FX_RATE_DESCRIPTION = fx_rate_description("on the trade date")


class TradeCostCreate(BaseModel):
    cost_type: str = Field(..., min_length=1, max_length=30)
    description: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    percentage: Decimal | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Alternative to amount: a percentage of the trade total. "
        "Immediately converted to a fixed amount in the trade's currency, "
        "using the trade's declared exchange rate; later trade edits "
        "do not recalculate it.",
    )
    currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        description="Ignored when percentage is supplied: the cost inherits "
        "the trade's currency and exchange rate.",
    )
    fx_rate: Decimal | None = Field(default=None, gt=0, description=FX_RATE_DESCRIPTION)
    notes: str | None = None

    @model_validator(mode="after")
    def _check_amount_xor_percentage(self):
        if (self.amount is None) == (self.percentage is None):
            raise ValueError("Specify exactly one of amount and percentage")
        return self


class TradeCostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trade_id: int
    cost_type: str
    description: str | None
    amount: Decimal
    currency: str
    fx_rate: Decimal
    amount_eur: Decimal
    percentage_used: Decimal | None
    notes: str | None


class TradeBase(BaseModel):
    security_id: int
    account_id: int
    type: str = Field(..., pattern="^(buy|sell)$")
    date: dt.date
    quantity: Decimal = Field(
        ...,
        ge=NUMERIC_18_6_MIN_POSITIVE,
        le=NUMERIC_18_6_MAX,
        description="Positive quantity representable with at most six decimal places.",
    )
    price: Decimal = Field(..., ge=PRICE_MIN, le=PRICE_MAX)
    quote_price: Decimal | None = Field(
        default=None,
        ge=PRICE_MIN,
        le=PRICE_MAX,
        description="Unit price in the security's quotation currency. May be "
        "omitted when this matches the settlement currency; required when "
        "the currencies differ.",
    )
    currency: str = Field(
        ...,
        min_length=3,
        max_length=3,
        description="Trade SETTLEMENT currency. May differ from the security's "
        "quotation currency: a US security bought on a European market can settle "
        "in EUR.",
    )
    fx_rate: Decimal | None = Field(
        default=None, ge=FX_RATE_MIN, le=FX_RATE_MAX, description=FX_RATE_DESCRIPTION
    )
    notes: str | None = None


class TradeCreate(TradeBase):
    pass


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    security_id: int
    account_id: int
    type: str
    date: dt.date
    quantity: Decimal
    price: Decimal
    quote_price: Decimal
    currency: str
    fx_rate: Decimal
    price_eur: Decimal
    total_amount: Decimal
    total_eur: Decimal
    notes: str | None
    total_costs_eur: Decimal = Decimal("0")
    created_at: dt.datetime
    updated_at: dt.datetime | None
