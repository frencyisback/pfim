"""Return metrics: simple return, TWR, MWR/IRR, and total return. This pure module accepts
numbers and lists and has no database dependencies.
"""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal, InvalidOperation, Overflow

from app.finance.periods import DAYS_PER_YEAR


def simple_return(
    current_price: Decimal,
    cost_basis: Decimal,
    dividends: Decimal = Decimal("0"),
) -> Decimal:
    """Simple return = (current price - acquisition price + dividends) / acquisition price."""
    if cost_basis == 0:
        raise ValueError("cost_basis cannot be zero")
    return (current_price - cost_basis + dividends) / cost_basis


def total_return(
    starting_value: Decimal,
    ending_value: Decimal,
    net_dividends: Decimal = Decimal("0"),
    net_coupons: Decimal = Decimal("0"),
) -> Decimal:
    """Total return = (ending value - starting value + net dividends + net coupons) / starting
    value.
    """
    if starting_value == 0:
        raise ValueError("starting_value cannot be zero")
    return (ending_value - starting_value + net_dividends + net_coupons) / starting_value


def annualize(cumulative_return: Decimal, days: int) -> Decimal:
    """Convert cumulative period return to compound annual growth rate: annual_return = (1 +
    cumulative_return) ** (365 / days) - 1. This makes periods of different lengths
    comparable. Raise ValueError for nonpositive days, cumulative return <= -100%, non-finite
    values, or unrepresentable annualized results.
    """
    if days <= 0:
        raise ValueError("The period must be at least one day")
    if not cumulative_return.is_finite():
        raise ValueError("Non-finite cumulative return: annualization is undefined")
    try:
        growth = Decimal("1") + cumulative_return
        if growth <= 0:
            raise ValueError("Cumulative return <= -100%: annualization is undefined")
        exponent = Decimal(DAYS_PER_YEAR) / Decimal(days)
        # Preserve the normal calculation while excluding infinity and overflow from responses.
        # The service returns null for this metric alone.
        numeric_growth = float(growth)
        if not math.isfinite(numeric_growth) or numeric_growth <= 0:
            raise ValueError("Annualized return cannot be represented")
        factor = numeric_growth ** float(exponent)
        if not math.isfinite(factor):
            raise ValueError("Annualized return cannot be represented")
        return Decimal(str(factor)) - Decimal("1")
    except (OverflowError, Overflow, InvalidOperation) as exc:
        raise ValueError("Annualized return cannot be represented") from exc


def time_weighted_return(
    starting_value: Decimal,
    ending_value: Decimal,
    cash_flows: list[tuple[dt.date, Decimal]],
    prices_at_flow_dates: dict[dt.date, Decimal],
    period_start: dt.date,
    period_end: dt.date,
) -> Decimal:
    """Time-weighted return excludes external cash-flow effects. Split history at purchase/sale
    cash-flow dates and geometrically chain subperiod returns: product(1 + R_i) - 1.
    starting_value and ending_value are market values at the period boundaries. cash_flows
    contains (date, amount), positive for added capital and negative for withdrawals.
    prices_at_flow_dates maps each date to market value immediately before its flow. Raise
    ValueError for missing pre-flow valuations or nonpositive opening subperiod values, which
    cannot produce economically meaningful returns.
    """
    sorted_flows = sorted(cash_flows, key=lambda f: f[0])

    factor = Decimal("1")
    period_open_value = starting_value

    for flow_date, flow_amount in sorted_flows:
        if flow_date not in prices_at_flow_dates:
            raise ValueError(f"Missing valuation for cash-flow date {flow_date}")
        value_before_flow = prices_at_flow_dates[flow_date]

        if period_open_value <= 0:
            raise ValueError(
                f"Nonpositive subperiod opening value before {flow_date}: " "Cannot calculate TWR"
            )
        sub_period_return = (value_before_flow - period_open_value) / period_open_value
        factor *= 1 + sub_period_return

        period_open_value = value_before_flow + flow_amount

    if period_open_value <= 0:
        raise ValueError("Nonpositive opening value in the last subperiod: cannot calculate TWR")
    last_return = (ending_value - period_open_value) / period_open_value
    factor *= 1 + last_return

    return factor - 1


def money_weighted_return(
    cash_flows: list[tuple[dt.date, Decimal]],
    tolerance: Decimal = Decimal("0.0000001"),
    max_iterations: int = 200,
) -> Decimal:
    """Money-weighted return / XIRR solves 0 = sum(CF_i / (1 + IRR) ** (days_i / 365)) for
    irregular dates. Invested capital is negative; withdrawals and ending value are positive.
    Use bisection, since regular-period IRR cannot represent actual trading dates. Aggregate
    same-day flows and discard only exact zeros before validation. Raise ValueError unless at
    least two dates have nonzero net flows of opposite signs, or if bisection fails to
    converge within the search interval.
    """
    flows_by_date: dict[dt.date, Decimal] = {}
    for date, amount in cash_flows:
        flows_by_date[date] = flows_by_date.get(date, Decimal("0")) + amount
    sorted_flows = sorted((date, amount) for date, amount in flows_by_date.items() if amount != 0)

    if len(sorted_flows) < 2:
        raise ValueError(
            "At least two dates with nonzero net cash flows are required to calculate IRR"
        )
    if not any(a < 0 for _, a in sorted_flows) or not any(a > 0 for _, a in sorted_flows):
        raise ValueError("Both negative investment flows and positive return flows are required")

    t0 = sorted_flows[0][0]

    def npv(rate: Decimal) -> Decimal:
        total = Decimal("0")
        for date, amount in sorted_flows:
            years = Decimal((date - t0).days) / Decimal(DAYS_PER_YEAR)
            total += amount / ((1 + rate) ** years)
        return total

    low, high = Decimal("-0.9999"), Decimal("10")
    npv_low, npv_high = npv(low), npv(high)

    if npv_low * npv_high > 0:
        raise ValueError(
            "Cannot find an IRR in the search range [-99.99%, 1000%]: "
            "check that the cash flows make economic sense"
        )

    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < tolerance:
            return mid
        if (npv_low < 0) == (npv_mid < 0):
            low, npv_low = mid, npv_mid
        else:
            high, npv_high = mid, npv_mid

    return (low + high) / 2
