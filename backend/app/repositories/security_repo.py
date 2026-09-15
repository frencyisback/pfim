"""Repository: SecurityRepository."""

from __future__ import annotations

from sqlalchemy import select

from app.models.security import Security
from app.repositories.base import BaseRepository


class SecurityRepository(BaseRepository[Security]):
    model = Security

    def get_by_ticker(self, ticker: str) -> Security | None:
        return self.db.scalars(select(Security).where(Security.ticker == ticker)).first()

    def get_by_isin(self, isin: str) -> Security | None:
        return self.db.scalars(select(Security).where(Security.isin == isin)).first()

    def list(self, *, only_active: bool = False) -> list[Security]:
        stmt = select(Security)
        if only_active:
            stmt = stmt.where(Security.is_active.is_(True))
        return list(self.db.scalars(stmt.order_by(Security.ticker)))
