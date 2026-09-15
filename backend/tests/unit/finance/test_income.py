"""Unit tests for app.finance.income. See technical-specification.md §9.6, §9.7.

Both functions divide TOTAL income by TOTAL position value. Passing a
per-unit value raises no error but multiplies the percentage by the number
of units, so tests explicitly enforce the total-value contract.
"""

from decimal import Decimal

import pytest

from app.finance.income import current_yield, yield_on_cost


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
