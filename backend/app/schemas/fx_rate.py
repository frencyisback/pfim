"""Pydantic schemas: FxRate."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class FxRateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date: dt.date
    from_currency: str
    to_currency: str
    rate: Decimal
    source: str


class FxRateImportError(BaseModel):
    row_number: int
    column: str | None = None
    message: str


class FxRateImportResult(BaseModel):
    imported: int
    reciprocal_calculated: int
    reciprocal_created: int = 0
    reciprocal_updated: int = 0
    errors: int
    row_errors: list[FxRateImportError] = Field(default_factory=list)


class FxRateSuggestion(BaseModel):
    """Exchange-rate suggestion for form prefilling. rate is None if no usable stored rate exists
    and must be entered manually. rate_date identifies the stored rate's date, which may
    precede the requested date.
    """

    currency: str
    date: dt.date
    rate: Decimal | None
    rate_date: dt.date | None = None
    source: str | None = None
