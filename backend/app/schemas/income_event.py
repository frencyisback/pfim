"""Pydantic schemas: IncomeEvent, for coupons and dividends."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import fx_rate_description

FX_RATE_DESCRIPTION = fx_rate_description(
    "on the payment date", also=", applying to both gross income and withholding"
)


class IncomeEventBase(BaseModel):
    security_id: int
    account_id: int
    event_type: str = Field(..., pattern="^(dividend|coupon|return_of_capital)$")
    ex_date: dt.date | None = None
    payment_date: dt.date
    quantity_held: Decimal | None = None
    amount_per_unit: Decimal | None = None
    total_amount: Decimal = Field(
        ...,
        ge=0,
        description="GROSS income amount in the declared currency. Income is "
        "money received: correct an incorrect entry by deleting the event, "
        "rather than recording one with the opposite sign.",
    )
    currency: str = Field(..., min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0, description=FX_RATE_DESCRIPTION)
    tax_withheld: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        description="Withholding tax in the same currency and at the same rate as "
        "gross income. It cannot exceed gross income: the resulting net amount is the cash received.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _withholding_cannot_exceed_the_gross(self):
        """Net income (total_amount - tax_withheld) feeds cash and returns. Withholding above
        gross income would create a negative dividend cash movement and is invalid. Full
        withholding with zero net income is allowed.
        """
        if self.tax_withheld > self.total_amount:
            raise ValueError(
                f"withholding tax ({self.tax_withheld}) cannot exceed the gross amount "
                f"({self.total_amount}): the net amount received would be negative"
            )
        return self


class IncomeEventCreate(IncomeEventBase):
    pass


class IncomeEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    security_id: int
    account_id: int
    event_type: str
    ex_date: dt.date | None
    payment_date: dt.date
    quantity_held: Decimal | None
    amount_per_unit: Decimal | None
    total_amount: Decimal
    currency: str
    fx_rate: Decimal
    total_eur: Decimal
    tax_withheld: Decimal
    net_amount_eur: Decimal
    notes: str | None


class IncomeEventSummaryItem(BaseModel):
    security_id: int
    ticker: str
    total_net_eur: Decimal
    events_count: int


class IncomeEventsSummary(BaseModel):
    period_from: dt.date | None
    period_to: dt.date | None
    total_net_eur: Decimal
    by_security: list[IncomeEventSummaryItem]
