"""Repository: AccountRepository."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select

from app.models.account import Account
from app.repositories.base import BaseRepository


class AccountRepository(BaseRepository[Account]):
    model = Account

    def list(
        self,
        *,
        only_active: bool = False,
        as_of_date: dt.date | None = None,
    ) -> list[Account]:
        stmt = select(Account)
        if only_active:
            stmt = stmt.where(Account.is_active.is_(True))
        if as_of_date is not None:
            stmt = stmt.where(
                or_(Account.opened_on.is_(None), Account.opened_on <= as_of_date),
                or_(Account.closed_on.is_(None), Account.closed_on >= as_of_date),
            )
        return list(self.db.scalars(stmt.order_by(Account.name)))
