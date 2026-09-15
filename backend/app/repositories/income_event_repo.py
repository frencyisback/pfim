"""Repository: IncomeEventRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.income_event import IncomeEvent
from app.repositories.base import BaseRepository


class IncomeEventRepository(BaseRepository[IncomeEvent]):
    model = IncomeEvent

    def list(
        self,
        *,
        security_id: int | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
    ) -> list[IncomeEvent]:
        stmt = select(IncomeEvent)
        if security_id is not None:
            stmt = stmt.where(IncomeEvent.security_id == security_id)
        if date_from is not None:
            stmt = stmt.where(IncomeEvent.payment_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(IncomeEvent.payment_date <= date_to)
        return list(self.db.scalars(stmt.order_by(IncomeEvent.payment_date.desc())))
