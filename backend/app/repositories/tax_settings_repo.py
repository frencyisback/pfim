"""Repository: TaxSettingRepository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tax_settings import TaxSetting


class TaxSettingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str) -> TaxSetting | None:
        return self.db.get(TaxSetting, key)

    def list(self) -> list[TaxSetting]:
        return list(self.db.scalars(select(TaxSetting).order_by(TaxSetting.key)))

    def upsert(self, key: str, value, description: str | None = None) -> TaxSetting:
        existing = self.get(key)
        if existing:
            existing.value = value
            if description is not None:
                existing.description = description
            self.db.flush()
            self.db.refresh(existing)
            return existing
        setting = TaxSetting(key=key, value=value, description=description)
        self.db.add(setting)
        self.db.flush()
        self.db.refresh(setting)
        return setting
