"""Service: PortfolioService. Combine FIFO positions from the finance engine with the latest
available prices to value current holdings.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from sqlalchemy.orm import Session

from app.finance.portfolio import (
    calculate_position,
    calculate_position_eur,
    calculate_position_native,
)
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.repositories.trade_repo import TradeRepository
from app.schemas.portfolio import PortfolioSummary, PositionLot, PositionRead
from app.schemas.report import PortfolioValuationFallback, PortfolioValuationMetadata
from app.utils.currency import to_eur
from app.utils.errors import NotFoundError


def _pct(delta: Decimal | None, base: Decimal) -> Decimal | None:
    return (delta / base * 100) if delta is not None and base > 0 else None


class PortfolioService:
    def __init__(self, db: Session):
        self.db = db
        self.security_repo = SecurityRepository(db)
        self.trade_repo = TradeRepository(db)
        self.price_repo = PriceRepository(db)

    def _market_data_as_of(self, as_of_date: dt.date) -> tuple[dict[int, list], dict[int, object]]:
        """Load trades and the latest price on or before the cutoff. Current portfolio views
        exclude future-dated preparatory records. Centralize this filter so lists and
        summaries agree.
        """
        trades_by_security: dict[int, list] = defaultdict(list)
        for trade in self.trade_repo.list(date_to=as_of_date):
            trades_by_security[trade.security_id].append(trade)

        latest_prices: dict[int, object] = {}
        for price in self.price_repo.list_all(date_to=as_of_date):
            # list_all is sorted by security/date: the last assignment is exactly the latest price
            # within the cutoff.
            latest_prices[price.security_id] = price
        return dict(trades_by_security), latest_prices

    def _build_position(
        self,
        security_id: int,
        *,
        trades: list | None = None,
        latest_price=None,
        as_of_date: dt.date | None = None,
    ) -> PositionRead | None:
        """Build positions in both native currency and EUR. Native FIFO uses trade.quote_price;
        EUR FIFO divides trade.total_eur by quantity so cost matches cash without amplifying
        unit rounding. Accept preloaded trades and latest_price to avoid two queries per
        security.
        """
        security = self.security_repo.get(security_id)
        if security is None:
            return None

        if trades is None:
            cutoff = as_of_date or dt.date.today()
            trades = self.trade_repo.list(security_id=security_id, date_to=cutoff)
            latest_price = self.price_repo.get_latest(security_id, as_of=cutoff)
        if not trades:
            return None

        position = calculate_position_native(trades)
        position_eur = calculate_position_eur(trades)
        if position.quantity == 0 and position.realized_gain_loss == 0:
            return None  # No relevant holdings for this security.

        current_price = Decimal(latest_price.price_close) if latest_price else None
        current_price_eur = (
            to_eur(current_price, Decimal(latest_price.fx_rate)) if latest_price else None
        )
        if latest_price is not None:
            current_value = current_price * position.quantity
            current_value_eur = current_price_eur * position.quantity
            unrealized = current_value - position.total_invested
            unrealized_eur = current_value_eur - position_eur.total_invested
            valuation_source = "market_price"
        else:
            # FIFO cost prevents a position from disappearing from totals, but is never presented as a
            # market price.
            current_value = position.total_invested
            current_value_eur = position_eur.total_invested
            unrealized = Decimal("0")
            unrealized_eur = Decimal("0")
            valuation_source = "fifo_cost"

        return PositionRead(
            security_id=security.id,
            ticker=security.ticker,
            name=security.name,
            quantity=position.quantity,
            currency=security.currency,
            average_cost=position.average_cost,
            total_invested=position.total_invested,
            current_price=current_price,
            current_value=current_value,
            unrealized_gain_loss=unrealized,
            unrealized_gain_loss_pct=_pct(unrealized, position.total_invested),
            average_cost_eur=position_eur.average_cost,
            total_invested_eur=position_eur.total_invested,
            current_price_eur=current_price_eur,
            current_value_eur=current_value_eur,
            unrealized_gain_loss_eur=unrealized_eur,
            unrealized_gain_loss_pct_eur=_pct(unrealized_eur, position_eur.total_invested),
            realized_gain_loss=position_eur.realized_gain_loss,
            current_price_date=latest_price.date if latest_price else None,
            valuation_source=valuation_source,
            lots=[
                PositionLot(
                    trade_id=lot.trade_id,
                    date=lot.date.isoformat(),
                    quantity_remaining=lot.quantity_remaining,
                    unit_cost=lot.unit_cost,
                )
                for lot in position.lots
            ],
        )

    def get_all_positions(self, *, as_of_date: dt.date | None = None) -> list[PositionRead]:
        # Load trades and latest prices in bulk: one pair of queries for the entire portfolio.
        #
        cutoff = as_of_date or dt.date.today()
        trades_by_security, latest_prices = self._market_data_as_of(cutoff)
        positions = [
            self._build_position(
                s.id,
                trades=trades_by_security.get(s.id, []),
                latest_price=latest_prices.get(s.id),
            )
            for s in self.security_repo.list()
        ]
        return [p for p in positions if p is not None and p.quantity > 0]

    def get_position(self, security_id: int, *, as_of_date: dt.date | None = None) -> PositionRead:
        position = self._build_position(security_id, as_of_date=as_of_date)
        if position is None:
            raise NotFoundError(
                f"No position found for security {security_id}",
                detail={"security_id": security_id},
            )
        return position

    def get_summary(self, *, as_of_date: dt.date | None = None) -> PortfolioSummary:
        """Always aggregate in EUR. Entry-time conversion freezes native prices and rates
        together. Preserve the product's precision until multiplying by quantity to avoid
        amplifying rounded EUR unit prices on large positions.
        """
        cutoff = as_of_date or dt.date.today()
        trades_by_security, latest_prices = self._market_data_as_of(cutoff)
        total_invested_eur = Decimal("0")
        total_current_value_eur = Decimal("0")
        total_realized_eur = Decimal("0")
        allocation: dict[str, Decimal] = {}
        fallback_securities: list[PortfolioValuationFallback] = []
        positions_count = 0

        for security in self.security_repo.list():
            trades = trades_by_security.get(security.id)
            if not trades:
                continue

            position_eur = calculate_position_eur(trades)
            total_realized_eur += position_eur.realized_gain_loss

            quantity = calculate_position(trades).quantity
            if quantity <= 0:
                continue
            positions_count += 1
            total_invested_eur += position_eur.total_invested

            latest_price = latest_prices.get(security.id)
            if latest_price is not None:
                current_value_eur = (
                    to_eur(Decimal(latest_price.price_close), Decimal(latest_price.fx_rate))
                    * quantity
                )
            else:
                current_value_eur = position_eur.total_invested
                fallback_securities.append(
                    PortfolioValuationFallback(
                        security_id=security.id,
                        ticker=security.ticker,
                        name=security.name,
                    )
                )
            total_current_value_eur += current_value_eur

            type_key = security.type
            allocation[type_key] = allocation.get(type_key, Decimal("0")) + current_value_eur

        return PortfolioSummary(
            total_invested=total_invested_eur,
            total_current_value=total_current_value_eur,
            total_unrealized_gain_loss=total_current_value_eur - total_invested_eur,
            total_realized_gain_loss=total_realized_eur,
            positions_count=positions_count,
            allocation_by_type=allocation,
            portfolio_valuation=PortfolioValuationMetadata(
                cost_fallback_used=bool(fallback_securities),
                cost_fallback_securities=fallback_securities,
            ),
        )
