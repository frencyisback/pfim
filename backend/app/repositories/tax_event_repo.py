"""Repository: TaxEventRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.tax_event import TaxEvent
from app.repositories.base import BaseRepository


class TaxEventRepository(BaseRepository[TaxEvent]):
    model = TaxEvent

    def list(
        self, *, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> list[TaxEvent]:
        stmt = select(TaxEvent)
        if date_from is not None:
            stmt = stmt.where(TaxEvent.event_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(TaxEvent.event_date <= date_to)
        return list(self.db.scalars(stmt.order_by(TaxEvent.event_date.desc())))

    def list_for_trades(self, trade_ids: list[int]) -> list[TaxEvent]:
        """Events linked to a group of trades, in insertion order, fetched in one query."""
        if not trade_ids:
            return []
        stmt = (
            select(TaxEvent).where(TaxEvent.related_trade_id.in_(trade_ids)).order_by(TaxEvent.id)
        )
        return list(self.db.scalars(stmt))

    def list_for_income(self, income_id: int) -> list[TaxEvent]:
        """Events referencing an income payment, without inferring ownership. No automatic
        income-event origin exists: manual and legacy rows must be shown to the user before
        deleting their source, rather than relying on the foreign-key constraint.
        """
        stmt = select(TaxEvent).where(TaxEvent.related_income_id == income_id).order_by(TaxEvent.id)
        return list(self.db.scalars(stmt))

    def list_automatic_for_trades(self, trade_ids: list[int]) -> list[TaxEvent]:
        """Only derived events owned by the FIFO synchronizer. A trade link does not imply
        ownership: manual and legacy rows may reference trades but must never be adopted or
        rewritten.
        """
        if not trade_ids:
            return []
        stmt = (
            select(TaxEvent)
            .where(
                TaxEvent.related_trade_id.in_(trade_ids),
                TaxEvent.origin == "automatic_trade",
            )
            .order_by(TaxEvent.id)
        )
        return list(self.db.scalars(stmt))
