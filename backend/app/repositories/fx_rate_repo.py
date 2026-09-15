"""Repository: FxRateRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.fx_rate import FxRate


class FxRateRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, from_currency: str, to_currency: str, date: dt.date) -> FxRate | None:
        stmt = select(FxRate).where(
            FxRate.from_currency == from_currency,
            FxRate.to_currency == to_currency,
            FxRate.date == date,
        )
        return self.db.scalars(stmt).first()

    def get_as_of(self, from_currency: str, to_currency: str, date: dt.date) -> FxRate | None:
        """Latest exchange rate on or before date. Provides a plausible form suggestion when the
        exact date has no quote, for example on weekends, holidays, or gaps in the archive.
        """
        stmt = (
            select(FxRate)
            .where(
                FxRate.from_currency == from_currency,
                FxRate.to_currency == to_currency,
                FxRate.date <= date,
            )
            .order_by(FxRate.date.desc())
        )
        return self.db.scalars(stmt).first()

    def list(self) -> list[FxRate]:
        return list(self.db.scalars(select(FxRate).order_by(FxRate.date.desc())))

    def upsert(self, rate: FxRate) -> FxRate:
        existing = self.get(rate.from_currency, rate.to_currency, rate.date)
        if existing:
            existing.rate = rate.rate
            existing.source = rate.source
            self.db.flush()
            self.db.refresh(existing)
            return existing
        self.db.add(rate)
        self.db.flush()
        self.db.refresh(rate)
        return rate
