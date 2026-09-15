"""Unit tests for app.finance.portfolio (FIFO).
See technical-specification.md §9.1. Target: 100% coverage.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

import pytest

from app.finance.portfolio import calculate_position


@dataclass
class FakeTrade:
    id: int
    type: str
    date: dt.date
    quantity: Decimal
    price: Decimal


def test_single_buy():
    trades = [FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100"))]
    pos = calculate_position(trades)
    assert pos.quantity == Decimal("10")
    assert pos.average_cost == Decimal("100")
    assert pos.total_invested == Decimal("1000")
    assert pos.realized_gain_loss == Decimal("0")


def test_multiple_buys_average_cost():
    trades = [
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
        FakeTrade(2, "buy", dt.date(2026, 2, 1), Decimal("10"), Decimal("120")),
    ]
    pos = calculate_position(trades)
    assert pos.quantity == Decimal("20")
    assert pos.total_invested == Decimal("2200")
    assert pos.average_cost == Decimal("110")


def test_fifo_partial_sell_consumes_oldest_lot_first():
    trades = [
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
        FakeTrade(2, "buy", dt.date(2026, 2, 1), Decimal("10"), Decimal("120")),
        FakeTrade(3, "sell", dt.date(2026, 3, 1), Decimal("5"), Decimal("150")),
    ]
    pos = calculate_position(trades)
    # Sell 5 units from the oldest lot (cost 100): gain = 5 * (150-100) = 250
    assert pos.realized_gain_loss == Decimal("250")
    # Remaining: 5 from the first lot (cost 100) + 10 from the second (cost 120)
    assert pos.quantity == Decimal("15")
    assert pos.total_invested == Decimal("5") * Decimal("100") + Decimal("10") * Decimal("120")


def test_fifo_sell_spanning_multiple_lots():
    trades = [
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
        FakeTrade(2, "buy", dt.date(2026, 2, 1), Decimal("10"), Decimal("120")),
        FakeTrade(3, "sell", dt.date(2026, 3, 1), Decimal("15"), Decimal("150")),
    ]
    pos = calculate_position(trades)
    # 10 units from the first lot: gain = 10*(150-100)=500
    # 5 units from the second lot: gain = 5*(150-120)=150
    assert pos.realized_gain_loss == Decimal("650")
    assert pos.quantity == Decimal("5")
    assert pos.average_cost == Decimal("120")


def test_sell_full_position_closes_it():
    trades = [
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
        FakeTrade(2, "sell", dt.date(2026, 2, 1), Decimal("10"), Decimal("130")),
    ]
    pos = calculate_position(trades)
    assert pos.quantity == Decimal("0")
    assert pos.total_invested == Decimal("0")
    assert pos.average_cost == Decimal("0")
    assert pos.realized_gain_loss == Decimal("300")
    assert pos.lots == []


def test_oversell_raises_value_error():
    trades = [
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
        FakeTrade(2, "sell", dt.date(2026, 2, 1), Decimal("15"), Decimal("100")),
    ]
    with pytest.raises(ValueError, match="available"):
        calculate_position(trades)


def test_unknown_trade_type_raises_value_error():
    trades = [FakeTrade(1, "hold", dt.date(2026, 1, 1), Decimal("10"), Decimal("100"))]
    with pytest.raises(ValueError, match="Unknown"):
        calculate_position(trades)


def test_trades_processed_in_chronological_order_regardless_of_input_order():
    trades = [
        FakeTrade(2, "sell", dt.date(2026, 3, 1), Decimal("5"), Decimal("150")),
        FakeTrade(1, "buy", dt.date(2026, 1, 1), Decimal("10"), Decimal("100")),
    ]
    pos = calculate_position(trades)
    assert pos.quantity == Decimal("5")
    assert pos.realized_gain_loss == Decimal("250")


def test_empty_trades_list():
    pos = calculate_position([])
    assert pos.quantity == Decimal("0")
    assert pos.realized_gain_loss == Decimal("0")
    assert pos.lots == []
