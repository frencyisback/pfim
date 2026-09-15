"""Unit tests for app.finance.returns.
See technical-specification.md §9.2-§9.5.
"""

import datetime as dt
from decimal import Decimal

import pytest

from app.finance.returns import (
    annualize,
    money_weighted_return,
    simple_return,
    time_weighted_return,
    total_return,
)


def test_annualize_over_exactly_one_year_is_unchanged():
    assert round(annualize(Decimal("0.20"), 365), 6) == Decimal("0.2")


def test_annualize_scales_up_a_short_period():
    """+21% over about 6 months is approximately +46.6% compounded annually: 1.21^(365/182) - 1, slightly above 1.21^2 because 182 days is slightly under half a year."""
    assert round(annualize(Decimal("0.21"), 182), 3) == Decimal("0.466")


def test_annualize_scales_down_a_long_period():
    """+100% over 4 years is approximately +18.9% compounded annually (2^(1/4) - 1)."""
    assert round(annualize(Decimal("1.0"), 365 * 4), 4) == Decimal("0.1892")


def test_annualize_rejects_non_positive_period():
    with pytest.raises(ValueError):
        annualize(Decimal("0.1"), 0)


def test_twr_rejects_negative_sub_period_opening_value():
    """If a withdrawal exceeds portfolio valuation on that date because the stored price predates the actual sale price, subperiod opening capital becomes negative. Report TWR as unavailable instead of returning an absurd approximation."""
    with pytest.raises(ValueError, match="cannot calculate TWR"):
        time_weighted_return(
            starting_value=Decimal("2000"),
            ending_value=Decimal("1100"),
            cash_flows=[(dt.date(2026, 7, 26), Decimal("-1500"))],
            prices_at_flow_dates={dt.date(2026, 7, 26): Decimal("1350")},
            period_start=dt.date(2026, 5, 5),
            period_end=dt.date(2026, 7, 26),
        )


def test_annualize_rejects_total_loss():
    with pytest.raises(ValueError):
        annualize(Decimal("-1"), 365)


@pytest.mark.parametrize("value", ["10", "1e400", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_annualize_reports_unrepresentable_values_as_domain_errors(value):
    with pytest.raises(ValueError):
        annualize(Decimal(value), 1)


def test_large_but_representable_annual_return_is_not_clamped():
    assert annualize(Decimal("10"), 365) == Decimal("10")


def test_simple_return_gain():
    r = simple_return(Decimal("120"), Decimal("100"))
    assert r == Decimal("0.20")


def test_simple_return_with_dividends():
    r = simple_return(Decimal("110"), Decimal("100"), dividends=Decimal("5"))
    assert r == Decimal("0.15")


def test_simple_return_zero_cost_basis_raises():
    with pytest.raises(ValueError):
        simple_return(Decimal("100"), Decimal("0"))


def test_total_return_basic():
    r = total_return(Decimal("1000"), Decimal("1100"))
    assert r == Decimal("0.10")


def test_total_return_with_dividends_and_coupons():
    r = total_return(
        Decimal("1000"), Decimal("1050"), net_dividends=Decimal("30"), net_coupons=Decimal("20")
    )
    assert r == Decimal("0.10")


def test_twr_no_cash_flows_equals_simple_return():
    """Without intermediate flows, TWR equals the period's simple return."""
    twr = time_weighted_return(
        starting_value=Decimal("1000"),
        ending_value=Decimal("1100"),
        cash_flows=[],
        prices_at_flow_dates={},
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 12, 31),
    )
    assert twr == Decimal("0.10")


def test_twr_isolates_effect_of_cash_flow():
    """Starting value 1000 rises to 1100 before the flow (+10%); adding 500 brings it to 1600, which then rises to 1760 (+10%).
    TWR must be 1.10 x 1.10 - 1 = 21%, unaffected by the absolute increase
    from 1000 to 1760.
    """
    flow_date = dt.date(2026, 6, 1)
    twr = time_weighted_return(
        starting_value=Decimal("1000"),
        ending_value=Decimal("1760"),
        cash_flows=[(flow_date, Decimal("500"))],
        prices_at_flow_dates={flow_date: Decimal("1100")},
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 12, 31),
    )
    assert twr == pytest.approx(Decimal("0.21"), abs=Decimal("0.0001"))


def test_twr_missing_valuation_at_flow_date_raises():
    with pytest.raises(ValueError, match="Missing valuation"):
        time_weighted_return(
            starting_value=Decimal("1000"),
            ending_value=Decimal("1100"),
            cash_flows=[(dt.date(2026, 6, 1), Decimal("100"))],
            prices_at_flow_dates={},
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
        )


def test_mwr_simple_one_year_10_percent():
    """Invest 1000 today, worth 1100 exactly one year later: IRR = 10%."""
    t0 = dt.date(2026, 1, 1)
    t1 = dt.date(2027, 1, 1)
    irr = money_weighted_return([(t0, Decimal("-1000")), (t1, Decimal("1100"))])
    assert irr == pytest.approx(Decimal("0.10"), abs=Decimal("0.001"))


def test_mwr_with_intermediate_flow():
    """Invest 1000 on January 1 and add 1000 halfway through the year; the portfolio is worth 2200 at year end. IRR must be positive and reasonable; test plausibility rather than the exact value."""
    irr = money_weighted_return(
        [
            (dt.date(2026, 1, 1), Decimal("-1000")),
            (dt.date(2026, 7, 1), Decimal("-1000")),
            (dt.date(2027, 1, 1), Decimal("2200")),
        ]
    )
    assert Decimal("0") < irr < Decimal("1")


def test_mwr_requires_at_least_two_flows():
    with pytest.raises(ValueError, match="At least two"):
        money_weighted_return([(dt.date(2026, 1, 1), Decimal("-1000"))])


def test_mwr_requires_both_signs():
    with pytest.raises(ValueError, match="negative"):
        money_weighted_return(
            [(dt.date(2026, 1, 1), Decimal("1000")), (dt.date(2026, 6, 1), Decimal("500"))]
        )
