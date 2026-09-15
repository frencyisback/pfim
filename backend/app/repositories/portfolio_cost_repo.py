"""Repository: PortfolioCostRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from app.models.portfolio_cost import PortfolioCost
from app.repositories.base import BaseRepository


class PortfolioCostRepository(BaseRepository[PortfolioCost]):
    model = PortfolioCost

    def list(
        self,
        *,
        account_id: int | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
    ) -> list[PortfolioCost]:
        stmt = select(PortfolioCost)
        if account_id is not None:
            stmt = stmt.where(PortfolioCost.account_id == account_id)
        if date_from is not None:
            stmt = stmt.where(PortfolioCost.date >= date_from)
        if date_to is not None:
            stmt = stmt.where(PortfolioCost.date <= date_to)
        return list(self.db.scalars(stmt.order_by(PortfolioCost.date.desc())))
