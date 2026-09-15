from decimal import Decimal

import pytest

from app.finance.statistics import percentile_inc, winsorized_mean


def test_percentile_inc_interpolates_between_observations():
    values = [Decimal("0"), Decimal("10"), Decimal("20"), Decimal("30")]

    assert percentile_inc(values, Decimal("0.25")) == Decimal("7.50")
    assert percentile_inc(values, Decimal("0.95")) == Decimal("28.50")


def test_winsorized_mean_keeps_all_twelve_months_and_limits_both_tails():
    months = [
        Decimal("-100"),
        Decimal("0"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("100"),
        Decimal("1000"),
    ]

    lower = percentile_inc(months, Decimal("0.05"))
    upper = percentile_inc(months, Decimal("0.95"))
    expected = sum((min(max(value, lower), upper) for value in months), Decimal("0")) / 12

    assert lower == Decimal("-45.00")
    assert upper == Decimal("505.00")
    assert winsorized_mean(months) == expected


def test_statistics_reject_empty_or_inverted_ranges():
    with pytest.raises(ValueError):
        percentile_inc([], Decimal("0.5"))
    with pytest.raises(ValueError):
        winsorized_mean([Decimal("1")], Decimal("0.9"), Decimal("0.1"))
