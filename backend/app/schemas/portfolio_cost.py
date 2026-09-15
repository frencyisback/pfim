"""Pydantic schemas: PortfolioCost."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import fx_rate_description

COST_TYPE_PATTERN = "^(stamp_duty|custody_fee|account_fee|other)$"

FX_RATE_DESCRIPTION = fx_rate_description("on the cost date")


class PortfolioCostBase(BaseModel):
    date: dt.date
    cost_type: str = Field(..., pattern=COST_TYPE_PATTERN)
    account_id: int
    description: str | None = None
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0, description=FX_RATE_DESCRIPTION)
    notes: str | None = None


class PortfolioCostCreate(PortfolioCostBase):
    pass


class PortfolioCostRead(PortfolioCostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fx_rate: Decimal
    amount_eur: Decimal
