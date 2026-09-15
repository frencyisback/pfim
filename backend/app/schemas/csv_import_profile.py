"""Pydantic schemas: CsvImportProfile."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CsvImportProfileBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    delimiter: str = Field(default=",", min_length=1, max_length=1)
    skip_rows: int = Field(default=0, ge=0)
    date_format: str = Field(default="%Y-%m-%d", min_length=1, max_length=30)
    date_column: str = Field(default="date", min_length=1, max_length=60)
    description_column: str = Field(default="description", min_length=1, max_length=60)
    amount_column: str = Field(default="amount", min_length=1, max_length=60)
    decimal_separator: str = Field(default=".", min_length=1, max_length=1)
    default_currency: str = Field(default="EUR", min_length=3, max_length=3)

    @field_validator("delimiter")
    @classmethod
    def _delimiter_must_be_one_non_newline_character(cls, value: str) -> str:
        if value in {"\r", "\n"}:
            raise ValueError("delimiter cannot be a newline")
        return value

    @field_validator("decimal_separator")
    @classmethod
    def _decimal_separator_must_be_supported(cls, value: str) -> str:
        if value not in {".", ","}:
            raise ValueError("decimal_separator must be '.' or ','")
        return value


class CsvImportProfileCreate(CsvImportProfileBase):
    category_column: str = Field(..., min_length=1, max_length=60)

    @field_validator("category_column")
    @classmethod
    def _normalize_required_category_column(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("category_column cannot be empty")
        return normalized


class CsvImportProfileRead(CsvImportProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Profiles created before categories became required may contain NULL. Keep them readable
    # without inventing a mapping.
    category_column: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime | None
