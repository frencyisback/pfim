"""Repository: PriceRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.price import Price


class PriceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_security_and_date(self, security_id: int, date: dt.date) -> Price | None:
        stmt = select(Price).where(Price.security_id == security_id, Price.date == date)
        return self.db.scalars(stmt).first()

    def list_for_security(self, security_id: int) -> list[Price]:
        stmt = select(Price).where(Price.security_id == security_id).order_by(Price.date)
        return list(self.db.scalars(stmt))

    def list_all(self, *, date_to: dt.date | None = None) -> list[Price]:
        """All prices ordered by security and date. Loading once and advancing a cursor supports
        valuation on many dates with one query instead of one query per security per date.
        """
        stmt = select(Price)
        if date_to is not None:
            stmt = stmt.where(Price.date <= date_to)
        stmt = stmt.order_by(Price.security_id, Price.date)
        return list(self.db.scalars(stmt))

    def get_latest(self, security_id: int, *, as_of: dt.date | None = None) -> Price | None:
        stmt = select(Price).where(Price.security_id == security_id)
        if as_of is not None:
            stmt = stmt.where(Price.date <= as_of)
        stmt = stmt.order_by(Price.date.desc())
        return self.db.scalars(stmt).first()

    def get_by_origin_trade_id(self, trade_id: int) -> Price | None:
        return self.db.scalars(select(Price).where(Price.origin_trade_id == trade_id)).first()

    def latest_by_security(self, *, as_of: dt.date | None = None) -> dict[int, Price]:
        """Latest price for every security in one query. Use this for whole-portfolio valuation
        instead of repeatedly calling get_latest.
        """
        latest_stmt = select(
            Price.security_id.label("security_id"), func.max(Price.date).label("max_date")
        )
        if as_of is not None:
            latest_stmt = latest_stmt.where(Price.date <= as_of)
        latest_dates = latest_stmt.group_by(Price.security_id).subquery()
        stmt = select(Price).join(
            latest_dates,
            (Price.security_id == latest_dates.c.security_id)
            & (Price.date == latest_dates.c.max_date),
        )
        return {p.security_id: p for p in self.db.scalars(stmt)}

    def upsert(self, price: Price) -> Price:
        """Insert or update a security price for a date, including all currency conversion
        fields. This is the shared price upsert implementation.
        """
        existing = self.get_by_security_and_date(price.security_id, price.date)
        if existing:
            existing.price_close = price.price_close
            existing.fx_rate = price.fx_rate
            existing.price_close_eur = price.price_close_eur
            existing.source = price.source
            existing.origin_trade_id = price.origin_trade_id
            self.db.flush()
            self.db.refresh(existing)
            return existing
        self.db.add(price)
        self.db.flush()
        self.db.refresh(price)
        return price
