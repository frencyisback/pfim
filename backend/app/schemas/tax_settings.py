"""Pydantic schemas: TaxSetting."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TaxSettingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Decimal
    description: str | None


class TaxSettingUpdate(BaseModel):
    value: Decimal
