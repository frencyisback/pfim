"""Pydantic schemas: Price."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.numeric_limits import FX_RATE_MAX, FX_RATE_MIN, PRICE_MAX, PRICE_MIN


class PriceCreate(BaseModel):
    security_id: int
    date: dt.date
    price_close: Decimal = Field(..., ge=PRICE_MIN, le=PRICE_MAX)
    fx_rate: Decimal | None = Field(
        default=None,
        ge=FX_RATE_MIN,
        le=FX_RATE_MAX,
        description="EUR per unit of the SECURITY's currency on the price "
        "date. Required for securities in currencies other than EUR; omit it "
        "for EUR securities. Enables position valuation without looking up rates "
        "at runtime.",
    )

    @field_validator("price_close", "fx_rate")
    @classmethod
    def _decimal_must_be_finite(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and not value.is_finite():
            raise ValueError("the value must be finite")
        return value


class PriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    security_id: int
    date: dt.date
    price_close: Decimal
    fx_rate: Decimal
    price_close_eur: Decimal
    source: str
    origin_trade_id: int | None


class PriceImportResult(BaseModel):
    imported: int
    updated: int
    skipped_unrecognized_ticker: int
    errors: int


class PriceImportPreviewRow(BaseModel):
    row_number: int
    date: dt.date | None
    ticker: str | None
    security_id: int | None
    security_label: str | None
    close: Decimal | None
    # Matched security currency and applicable exchange rate show which preview rows require
    # the fx_rate column.
    currency: str | None = None
    fx_rate: Decimal | None = None
    close_eur: Decimal | None = None
    is_update: bool
    errors: list[str]
    # Valid duplicates: the last row wins, even on another page.
    superseded_by_row: int | None = None
    final_row_number: int | None = None
    final_close: Decimal | None = None
    final_fx_rate: Decimal | None = None
    final_close_eur: Decimal | None = None


class PriceImportPreviewResult(BaseModel):
    rows: list[PriceImportPreviewRow]
    total_rows: int
    new_rows: int
    update_rows: int
    skipped_unrecognized_ticker: int
    error_rows: int
    page: int = 1
    page_size: int
    total_pages: int
