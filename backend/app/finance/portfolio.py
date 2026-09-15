"""FIFO portfolio position calculation. This pure module accepts generic trades with
type/date/quantity/price attributes and has no database dependencies. PFIM records distinguish
settlement and quoted prices; use calculate_position_native or calculate_position_eur for
those records.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


class TradeLike(Protocol):
    """Minimum interface accepted from either an ORM Trade or a test dataclass."""

    id: int
    type: str  # 'buy' | 'sell'
    date: object  # Date, used only for sorting and lot references.
    quantity: Decimal
    price: Decimal


@dataclass
class Lot:
    trade_id: int
    date: object
    quantity_remaining: Decimal
    unit_cost: Decimal


@dataclass
class Position:
    quantity: Decimal
    average_cost: Decimal
    total_invested: Decimal
    realized_gain_loss: Decimal
    lots: list[Lot] = field(default_factory=list)


class PositionTracker:
    """FIFO state updated one trade at a time. calculate_position applies all trades for a final
    snapshot; historical net worth and TWR apply trades once chronologically and inspect state
    after each date. Both reuse the same algorithm. Callers must sort with trade_sort_key
    before applying trades.
    """

    def __init__(self) -> None:
        self._lots: deque[Lot] = deque()
        self._realized_gain_loss = Decimal("0")

    def apply(self, trade) -> None:
        """Apply a trade; raise ValueError on short selling."""
        quantity = Decimal(trade.quantity)
        price = Decimal(trade.price)

        if trade.type == "buy":
            self._lots.append(
                Lot(
                    trade_id=trade.id, date=trade.date, quantity_remaining=quantity, unit_cost=price
                )
            )
        elif trade.type == "sell":
            remaining_to_sell = quantity
            available = sum((lot.quantity_remaining for lot in self._lots), Decimal("0"))
            if remaining_to_sell > available:
                raise ValueError(
                    f"Sale of {remaining_to_sell} units requested, available {available}"
                )
            while remaining_to_sell > 0:
                oldest = self._lots[0]
                consumed = min(oldest.quantity_remaining, remaining_to_sell)
                self._realized_gain_loss += consumed * (price - oldest.unit_cost)
                oldest.quantity_remaining -= consumed
                remaining_to_sell -= consumed
                if oldest.quantity_remaining == 0:
                    self._lots.popleft()
        else:
            raise ValueError(f"Unknown trade type: {trade.type}")

    @property
    def quantity(self) -> Decimal:
        """Remaining quantity, independent of price currency and readable from a EUR tracker."""
        return sum((lot.quantity_remaining for lot in self._lots), Decimal("0"))

    @property
    def total_invested(self) -> Decimal:
        return sum((lot.quantity_remaining * lot.unit_cost for lot in self._lots), Decimal("0"))

    @property
    def realized_gain_loss(self) -> Decimal:
        """Realized gains or losses accumulated so far. Differences between consecutive readings
        give the result of each sale; see realized_by_sell.
        """
        return self._realized_gain_loss

    def snapshot(self) -> Position:
        """Immutable snapshot of the current state."""
        remaining_lots = [
            Lot(
                trade_id=lot.trade_id,
                date=lot.date,
                quantity_remaining=lot.quantity_remaining,
                unit_cost=lot.unit_cost,
            )
            for lot in self._lots
            if lot.quantity_remaining > 0
        ]
        total_quantity = sum((lot.quantity_remaining for lot in remaining_lots), Decimal("0"))
        total_invested = sum(
            (lot.quantity_remaining * lot.unit_cost for lot in remaining_lots), Decimal("0")
        )
        return Position(
            quantity=total_quantity,
            average_cost=(total_invested / total_quantity) if total_quantity > 0 else Decimal("0"),
            total_invested=total_invested,
            realized_gain_loss=self._realized_gain_loss,
            lots=remaining_lots,
        )


def trade_sort_key(trade):
    """Deterministic chronological order, using ID to break same-day ties in recording order."""
    return (trade.date, trade.id)


def calculate_position(trades: list) -> Position:
    """Calculate a security's FIFO position. Sales consume the oldest purchase lots; each sold
    portion contributes (sale price - FIFO acquisition price) * quantity to realized gain or
    loss. The generic engine uses price, which is PFIM's settlement price. Use
    calculate_position_native for quote_price or calculate_position_eur for aggregates. Raise
    ValueError when a sale exceeds holdings; short selling is unsupported in v1.0.
    """
    tracker = PositionTracker()
    for trade in sorted(trades, key=trade_sort_key):
        tracker.apply(trade)
    return tracker.snapshot()


@dataclass
class _PricedTrade:
    """Minimal trade view using the caller's selected price. Reuse FIFO for quoted prices in the
    security currency or frozen EUR values per unit.
    """

    id: int
    type: str
    date: object
    quantity: Decimal
    price: Decimal


def as_native_priced(trade) -> _PricedTrade:
    """View a PFIM trade in its quoted currency."""
    return _PricedTrade(
        id=trade.id,
        type=trade.type,
        date=trade.date,
        quantity=Decimal(trade.quantity),
        price=Decimal(trade.quote_price),
    )


def calculate_position_native(trades: list) -> Position:
    """FIFO expressed in the security's quoted currency."""
    return calculate_position([as_native_priced(t) for t in trades])


def as_eur_priced(trade) -> _PricedTrade:
    """EUR view allocated from the trade's frozen total. The six-decimal price_eur can amplify
    rounding at large quantities. Allocate authoritative total_eur over quantity so FIFO
    reconstructs the exact cash total when consuming the lot.
    """
    quantity = Decimal(trade.quantity)
    return _PricedTrade(
        id=trade.id,
        type=trade.type,
        date=trade.date,
        quantity=quantity,
        price=Decimal(trade.total_eur) / quantity,
    )


def calculate_position_eur(trades: list) -> Position:
    """EUR-normalized calculate_position for all multi-security and multi-currency aggregates,
    including net worth and taxation. Use frozen total_eur / quantity, matching cash values.
    price_eur remains informational and is not multiplied again, avoiding amplified rounding.
    """
    return calculate_position([as_eur_priced(t) for t in trades])


def realized_by_sell(trades: list) -> dict[int, Decimal]:
    """Return realized gain or loss for each sale as {trade_id: realized_delta}, including
    zero-result sales. Earlier trade changes alter lots consumed by subsequent sales, so tax
    records require synchronization after every write. Raise ValueError on short selling.
    """
    tracker = PositionTracker()
    realized: dict[int, Decimal] = {}
    previous_total = Decimal("0")
    for trade in sorted(trades, key=trade_sort_key):
        tracker.apply(trade)
        if trade.type == "sell":
            total = tracker.realized_gain_loss
            realized[trade.id] = total - previous_total
            previous_total = total
    return realized


def realized_by_sell_eur(trades: list) -> dict[int, Decimal]:
    """EUR-normalized realized_by_sell for tax records. Taxable aggregates always use EUR, even
    for securities quoted in other currencies.
    """
    return realized_by_sell([as_eur_priced(t) for t in trades])
