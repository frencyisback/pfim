"""Pydantic schemas: Security."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The UI no longer offers etf (replaced by etf_equity/etf_bond), but it remains accepted
# for securities recorded by earlier versions.
SECURITY_TYPE_PATTERN = "^(stock|bond|etf_equity|etf_bond|fund|commodity|etf)$"
SecurityName = Annotated[str, Field(min_length=1, max_length=200)]
CouponFrequency = Annotated[str, Field(pattern="^(monthly|quarterly|semiannual|annual)$")]


class SecurityDetails(BaseModel):
    """Shared metadata constraints for creation, update, and responses."""

    market: str | None = Field(default=None, max_length=20)
    sector: str | None = Field(default=None, max_length=100)
    industry: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=60)
    coupon_rate: Decimal | None = None
    coupon_freq: CouponFrequency | None = None
    maturity_date: dt.date | None = None
    face_value: Decimal | None = None
    notes: str | None = None


class SecurityBase(SecurityDetails):
    ticker: str = Field(..., min_length=1, max_length=30)
    name: SecurityName
    type: str = Field(..., pattern=SECURITY_TYPE_PATTERN)
    currency: str = Field(..., min_length=3, max_length=3)
    isin: str | None = Field(default=None, max_length=12)


def _validate_name(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("the security name cannot contain only whitespace")
    return value


class SecurityCreate(SecurityBase):
    _nonblank_name = field_validator("name")(_validate_name)


class SecurityUpdate(SecurityDetails):
    name: SecurityName | None = None
    is_active: bool | None = None

    _nonblank_name = field_validator("name")(_validate_name)

    @model_validator(mode="after")
    def _required_columns_cannot_be_explicit_null(self):
        explicit_nulls = sorted(
            field
            for field in {"name", "is_active"} & self.model_fields_set
            if getattr(self, field) is None
        )
        if explicit_nulls:
            raise ValueError("fields that cannot be cleared: " + ", ".join(explicit_nulls))
        return self


class SecurityRead(SecurityBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
