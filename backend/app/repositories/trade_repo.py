"""Repository: TradeRepository."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select

from app.models.trade import Trade
from app.models.trade_cost import TradeCost
from app.repositories.base import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    model = Trade

    def list(
        self,
        *,
        security_id: int | None = None,
        account_id: int | None = None,
        date_to: dt.date | None = None,
    ) -> list[Trade]:
        stmt = select(Trade)
        if security_id is not None:
            stmt = stmt.where(Trade.security_id == security_id)
        if account_id is not None:
            stmt = stmt.where(Trade.account_id == account_id)
        if date_to is not None:
            stmt = stmt.where(Trade.date <= date_to)
        return list(self.db.scalars(stmt.order_by(Trade.date, Trade.id)))

    def list_all_costs(self) -> list[TradeCost]:
        """All costs for all trades in one query, for portfolio-wide aggregation such as net cash
        flows and cost analysis.
        """
        return list(self.db.scalars(select(TradeCost)))

    def costs_grouped_by_trade(self) -> dict[int, list[TradeCost]]:
        """Costs grouped by trade, fetched in one query."""
        grouped: dict[int, list[TradeCost]] = defaultdict(list)
        for cost in self.list_all_costs():
            grouped[cost.trade_id].append(cost)
        return grouped

    def group_by_security(self) -> dict[int, list[Trade]]:
        """All trades grouped by security, fetched in one query in the chronological order
        required by FIFO.
        """
        grouped: dict[int, list[Trade]] = defaultdict(list)
        for trade in self.list():
            grouped[trade.security_id].append(trade)
        return grouped

    def add_cost(self, cost: TradeCost) -> TradeCost:
        self.db.add(cost)
        self.db.flush()
        self.db.refresh(cost)
        return cost

    def list_costs(self, trade_id: int) -> list[TradeCost]:
        stmt = select(TradeCost).where(TradeCost.trade_id == trade_id)
        return list(self.db.scalars(stmt))

    def get_cost(self, cost_id: int) -> TradeCost | None:
        return self.db.get(TradeCost, cost_id)

    def delete_cost(self, cost_id: int) -> None:
        cost = self.get_cost(cost_id)
        if cost:
            self.db.delete(cost)
            self.db.flush()
