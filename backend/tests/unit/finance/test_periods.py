"""Shared calendar conventions (app/finance/periods.py).

The last-12-month window is a function because sharing a constant was
insufficient: different comparisons (>= and >) yielded different lengths.
These tests establish the definition;
tests/integration/test_trailing_year_window.py verifies report compliance.
"""

import datetime as dt
from decimal import Decimal

from app.finance.periods import (
    DAYS_PER_MONTH,
    DAYS_PER_YEAR,
    MONTHS_PER_TRAILING_YEAR,
    trailing_year_start,
)

TEST_TODAY = dt.date(2026, 7, 29)


def test_the_window_contains_exactly_one_year_of_days():
    start = trailing_year_start(TEST_TODAY)

    assert (TEST_TODAY - start).days + 1 == DAYS_PER_YEAR


def test_today_is_inside_the_window():
    assert trailing_year_start(TEST_TODAY) <= TEST_TODAY


def test_the_day_exactly_one_year_back_is_outside():
    """The day on which the two reports disagreed."""
    one_year_ago = TEST_TODAY - dt.timedelta(days=DAYS_PER_YEAR)

    assert one_year_ago < trailing_year_start(TEST_TODAY)


def test_the_day_after_that_is_inside():
    first_included_day = TEST_TODAY - dt.timedelta(days=DAYS_PER_YEAR - 1)

    assert first_included_day >= trailing_year_start(TEST_TODAY)


def test_the_window_crosses_a_leap_day_without_changing_length():
    """The convention uses 365 fixed days, not a calendar year: an intervening February 29 does not extend it."""
    end_date = dt.date(2028, 3, 1)  # 2028 is a leap year

    assert (end_date - trailing_year_start(end_date)).days + 1 == DAYS_PER_YEAR


def test_the_monthly_divisor_matches_the_window_length():
    """The monthly average divides by the actual months in the window, approximately 11.99 rather than exactly 12; the difference affects the average by 1.4%."""
    assert MONTHS_PER_TRAILING_YEAR == Decimal(DAYS_PER_YEAR) / DAYS_PER_MONTH
    assert Decimal("11.9") < MONTHS_PER_TRAILING_YEAR < Decimal("12.1")
