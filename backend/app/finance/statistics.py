"""Robust financial statistics, independent of the database."""

from __future__ import annotations

from decimal import Decimal


def percentile_inc(values: list[Decimal], percentile: Decimal) -> Decimal:
    """Inclusive percentile with linear interpolation (type 7). This matches PERCENTILE.INC:
    percentiles 0 and 1 are the minimum and maximum, with interpolation between observations.
    """
    if not values:
        raise ValueError("A percentile requires at least one value")
    if percentile < 0 or percentile > 1:
        raise ValueError("The percentile must be between 0 and 1")

    ordered = sorted(values)
    rank = Decimal(len(ordered) - 1) * percentile
    lower_index = int(rank)
    fraction = rank - Decimal(lower_index)
    if fraction == 0:
        return ordered[lower_index]
    return ordered[lower_index] + (ordered[lower_index + 1] - ordered[lower_index]) * fraction


def winsorized_mean(
    values: list[Decimal],
    lower_percentile: Decimal = Decimal("0.05"),
    upper_percentile: Decimal = Decimal("0.95"),
) -> Decimal:
    """Mean after clipping each value to the requested percentile bounds. Winsorization preserves
    the number of observations, limiting extreme months to P5/P95 instead of discarding them.
    """
    if not values:
        raise ValueError("The winsorized mean requires at least one value")
    if lower_percentile > upper_percentile:
        raise ValueError("The lower percentile cannot exceed the upper percentile")

    lower = percentile_inc(values, lower_percentile)
    upper = percentile_inc(values, upper_percentile)
    limited = [min(max(value, lower), upper) for value in values]
    return sum(limited, Decimal("0")) / Decimal(len(limited))
