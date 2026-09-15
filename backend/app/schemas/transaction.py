"""Pydantic schemas: Transaction."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import fx_rate_description

FX_RATE_DESCRIPTION = fx_rate_description("on the transaction date")


class TransactionBase(BaseModel):
    account_id: int
    category_id: int
    date: dt.date
    amount: Decimal  # Positive = income, negative = expense.
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0, description=FX_RATE_DESCRIPTION)
    description: str | None = None
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("amount")
    @classmethod
    def _amount_must_not_be_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("the transaction amount cannot be zero")
        return value


class TransactionCreate(TransactionBase):
    pass


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    category_id: int
    date: dt.date
    amount: Decimal
    currency: str
    # Always populated through entry-time conversion. Use amount_eur for every sum, never
    # amount.
    fx_rate: Decimal
    amount_eur: Decimal
    description: str | None
    notes: str | None
    tags: list[str] = Field(default_factory=list)
    transfer_group_id: str | None = None
    trade_id: int | None = None
    income_event_id: int | None = None
    portfolio_cost_id: int | None = None
    created_at: dt.datetime
    updated_at: dt.datetime | None


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    date: dt.date
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    fx_rate: Decimal | None = Field(default=None, gt=0, description=FX_RATE_DESCRIPTION)
    description: str | None = None
    notes: str | None = None


class TransferResult(BaseModel):
    from_transaction: TransactionRead
    to_transaction: TransactionRead


class TransactionSummaryItem(BaseModel):
    key: str  # e.g. category, month
    total_income: Decimal
    total_expense: Decimal
    net: Decimal


class TransactionSummary(BaseModel):
    period_from: dt.date | None
    period_to: dt.date | None
    total_income: Decimal
    total_expense: Decimal
    net: Decimal
    by_category: list[TransactionSummaryItem] = Field(default_factory=list)


class ImportPreviewRow(BaseModel):
    row_number: int
    date: dt.date | None
    description: str | None
    amount: Decimal | None
    category: str | None = None
    is_duplicate: bool
    errors: list[str] = Field(default_factory=list)


class ImportPreviewResult(BaseModel):
    rows: list[ImportPreviewRow]
    total_rows: int
    duplicate_rows: int
    error_rows: int
    page: int = 1
    page_size: int
    total_pages: int


class ImportResult(BaseModel):
    imported: int
    skipped_duplicates: int
    errors: int
