"""Unit tests for app.finance.income. See technical-specification.md §9.6, §9.7.

Both functions divide TOTAL income by TOTAL position value. Passing a
per-unit value raises no error but multiplies the percentage by the number
of units, so tests explicitly enforce the total-value contract.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.finance.income import current_yield, open_distribution_fractions, yield_on_cost


def test_open_distribution_fraction_uses_account_and_ex_date_before_same_day_trades():
    def trade(ident, account, day, kind, quantity):
        return SimpleNamespace(
            id=ident,
            account_id=account,
            security_id=1,
            date=date(2024, 1, day),
            type=kind,
            quantity=Decimal(quantity),
        )

    def payment(ident, account, ex_day, reported_quantity=None):
        return SimpleNamespace(
            id=ident,
            account_id=account,
            security_id=1,
            ex_date=date(2024, 1, ex_day) if ex_day else None,
            payment_date=date(2024, 1, 2),
            quantity_held=reported_quantity,
        )

    trades = [
        trade(1, 1, 1, "buy", 100),
        trade(2, 2, 1, "buy", 50),
        trade(3, 1, 2, "buy", 100),
        trade(4, 1, 3, "sell", 100),
    ]
    events = [
        payment(1, 1, None),
        payment(2, 1, 2),
        payment(3, 2, 2),
        payment(4, 2, 2, Decimal(100)),
        payment(5, 3, 2),
    ]
    # Account 1 sold the first 100 units. On the ex-date only those were
    # entitled; at payment-day close 100 of the then 200 units survive.
    # Account 2's units remain intact; a larger declared entitlement records
    # a partly missing holding history. Account 3 has no recorded units.
    assert open_distribution_fractions(trades, events) == {
        1: Decimal("0.5"),
        2: 0,
        3: 1,
        4: Decimal("0.5"),
        5: 0,
    }


def test_yield_on_cost():
    """EUR 4.5 income on EUR 100 invested = 4.5%."""
    assert yield_on_cost(Decimal("4.5"), Decimal("100")) == Decimal("4.5")


def test_yield_on_cost_is_independent_of_the_number_of_units():
    """Equal capital and income yield the same YoC, whether held as 100 units at EUR 10 or 10 at EUR 100."""
    assert yield_on_cost(Decimal("50"), Decimal("1000")) == yield_on_cost(
        Decimal("50"), Decimal("10") * Decimal("100")
    )


def test_yield_on_cost_zero_cost_raises():
    with pytest.raises(ValueError):
        yield_on_cost(Decimal("4.5"), Decimal("0"))


def test_current_yield():
    """EUR 5 income on EUR 125 market value = 4%."""
    assert current_yield(Decimal("5"), Decimal("125")) == Decimal("4")


def test_current_yield_zero_value_raises():
    with pytest.raises(ValueError):
        current_yield(Decimal("5"), Decimal("0"))
