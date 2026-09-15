"""Pydantic schemas: TaxEvent."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaxEventBase(BaseModel):
    event_date: dt.date
    event_type: str = Field(
        ..., pattern="^(capital_gain|capital_loss|withholding|substitute_tax|other)$"
    )
    related_trade_id: int | None = Field(default=None, gt=0)
    related_income_id: int | None = Field(default=None, gt=0)
    description: str = Field(..., min_length=1)
    gross_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = Field(
        default=None,
        description="GROSS tax on this individual event, before offsetting capital "
        "gains and losses. This is a detail, not the tax due: the total after "
        "offsets is in the fiscal field of /reports/costs-analysis.",
    )
    net_amount: Decimal | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _only_one_related_source(self):
        if self.related_trade_id is not None and self.related_income_id is not None:
            raise ValueError(
                "A tax event may reference either a trade or an income payment, not both"
            )
        return self


class TaxEventCreate(TaxEventBase):
    pass


class TaxEventUpdate(BaseModel):
    event_date: dt.date | None = None
    event_type: str | None = Field(
        default=None,
        pattern="^(capital_gain|capital_loss|withholding|substitute_tax|other)$",
    )
    related_trade_id: int | None = Field(default=None, gt=0)
    related_income_id: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, min_length=1)
    gross_amount: Decimal | None = None
    tax_rate: Decimal | None = None
    tax_amount: Decimal | None = None
    net_amount: Decimal | None = None
    is_compensated: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _validate_partial_update(self):
        required_fields = {"event_date", "event_type", "description", "is_compensated"}
        explicit_nulls = sorted(
            field
            for field in required_fields
            if field in self.model_fields_set and getattr(self, field) is None
        )
        if explicit_nulls:
            raise ValueError("the following fields cannot be null: " + ", ".join(explicit_nulls))
        if self.related_trade_id is not None and self.related_income_id is not None:
            raise ValueError(
                "A tax event may reference either a trade or an income payment, not both"
            )
        return self


class TaxEventRead(TaxEventBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    origin: str
    is_compensated: bool
