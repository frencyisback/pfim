"""XIRR on net cash-flow dates, without persistence or monetary rounding."""

import datetime as dt
from decimal import Decimal

import pytest

from app.finance.returns import money_weighted_return

START = dt.date(2025, 1, 1)
END = dt.date(2026, 1, 1)


@pytest.mark.parametrize(
    "flows",
    [
        [],
        [(START, Decimal("-100")), (START, Decimal("100"))],
        [(START, Decimal("-100")), (START, Decimal("110"))],
        [
            (START, Decimal("-100")),
            (START, Decimal("100")),
            (END, Decimal("-200")),
            (END, Decimal("200")),
        ],
        [(START, Decimal("0")), (END, Decimal("100"))],
    ],
)
def test_xirr_requires_two_dates_after_exact_cancellations(flows):
    with pytest.raises(ValueError, match="At least two dates"):
        money_weighted_return(flows)


def test_xirr_requires_opposite_signs_after_summing_each_date():
    # Individual rows have opposite signs, but both date totals are positive.
    with pytest.raises(ValueError, match="negative"):
        money_weighted_return(
            [(START, Decimal("-100")), (START, Decimal("110")), (END, Decimal("20"))]
        )


def test_xirr_same_day_trades_income_and_costs_equal_their_net_flow():
    separate_flows = [
        (END, Decimal("100")),
        (START, Decimal("-80")),
        (START, Decimal("-30")),
        (END, Decimal("12")),
        (START, Decimal("15")),
        (START, Decimal("-5")),
        (END, Decimal("-2")),
    ]
    consolidated_flows = [(START, Decimal("-100")), (END, Decimal("110"))]

    assert money_weighted_return(separate_flows) == money_weighted_return(consolidated_flows)
    assert money_weighted_return(separate_flows) == pytest.approx(Decimal("0.1"), abs=1e-8)


def test_xirr_preserves_a_nonzero_flow_smaller_than_default_solver_tolerance():
    # Do not zero amounts using the NPV tolerance (1e-7).
    flows = [(START, Decimal("-0.00000001")), (END, Decimal("0.000000011"))]
    result = money_weighted_return(flows, tolerance=Decimal("1e-25"))
    assert result == pytest.approx(Decimal("0.1"), abs=1e-12)


def test_xirr_zero_return_over_one_year_is_calculable():
    result = money_weighted_return([(START, Decimal("-100")), (END, Decimal("100"))])
    assert result == pytest.approx(Decimal("0"), abs=1e-8)


def test_xirr_preserves_closed_and_reopened_investments():
    # XIRR uses all flows even when the portfolio is empty between two segments.
    result = money_weighted_return(
        [
            (START, Decimal("-100")),
            (dt.date(2025, 4, 1), Decimal("100")),
            (dt.date(2025, 8, 1), Decimal("-100")),
            (END, Decimal("100")),
        ]
    )
    assert result == pytest.approx(Decimal("0"), abs=1e-8)
