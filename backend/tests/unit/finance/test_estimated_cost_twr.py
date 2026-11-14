"""Report TWR on synthetic holdings, with dated quotes, recorded costs and tax estimates."""

import datetime as dt
from decimal import Decimal

import pytest

from app.services.performance_service import PerformanceService

from .test_twr_cash_adjustments import END, MIDDLE, START, _cost, _income, _price, _trade


def _report_twr(
    *,
    trades=None,
    prices=None,
    rate="26",
    period_start=START,
    period_end=END,
    costs=None,
    recurring=(),
    incomes=(),
    gains=None,
    withheld=None,
):
    # Every source is preloaded. Any unexpected database access will fail the test.
    service = PerformanceService.__new__(PerformanceService)
    return service.cost_report_twr(
        period_start=period_start,
        as_of=period_end,
        trades=trades if trades is not None else [_trade(quantity="10")],
        prices=prices if prices is not None else [_price(), _price(END, "120")],
        income_events=list(incomes),
        recurring_costs=list(recurring),
        costs_by_trade=costs or {},
        tax_rate_pct=Decimal(rate),
        realized_gain_changes=gains or {},
        capital_gains_withheld=withheld or {},
    )


def test_mark_to_market_and_no_cost_cash_move():
    assert _report_twr() == (Decimal("0.2"), Decimal("0.2"), Decimal("0.148"))


def test_rates_and_valuation_precision_match_the_period_cost_estimate():
    # One half-cent on EUR 0.25 at 26% rounds up to EUR 0.07.
    result = _report_twr(trades=[_trade()], prices=[_price(), _price(END, "100.25")])
    assert result[-1] == Decimal("0.0018")


def test_filtered_period_starts_from_pre_trade_opening_at_the_available_quote():
    prices = [_price(), _price(MIDDLE, "120"), _price(END + dt.timedelta(days=1), "180")]
    assert _report_twr(period_start=MIDDLE, prices=prices) == (0, 0, 0)


@pytest.mark.parametrize("tax_paid", ["0", "10", "26"])
def test_partial_sale_at_unchanged_quote_moves_open_tax_to_realised_once(tax_paid):
    sale_day = MIDDLE + dt.timedelta(days=1)
    paid = Decimal(tax_paid)
    gross, recorded, estimated = _report_twr(
        period_start=MIDDLE,
        trades=[
            _trade(quantity="10"),
            _trade(2, date=sale_day, kind="sell", quantity="5", price="120"),
        ],
        prices=[_price(), _price(MIDDLE, "120")],
        costs={2: paid},
        withheld={sale_day: paid},
        gains={sale_day: Decimal("100")},
    )
    assert gross == estimated == 0
    assert abs(recorded + paid / Decimal("1200")) < Decimal("1e-24")


def test_excess_withholding_remains_a_cost_and_prior_period_gains_are_excluded():
    sale_day = MIDDLE + dt.timedelta(days=1)
    gross, _, estimated = _report_twr(
        period_start=MIDDLE,
        trades=[
            _trade(quantity="10"),
            _trade(2, date=sale_day, kind="sell", quantity="5", price="120"),
        ],
        prices=[_price(), _price(MIDDLE, "120")],
        costs={2: Decimal("30")},
        withheld={sale_day: Decimal("30")},
        gains={START: Decimal("9000"), sale_day: Decimal("100")},
    )
    assert gross == 0
    assert abs(estimated + Decimal("4") / Decimal("1148")) < Decimal("1e-24")


def test_fees_and_tax_use_net_capital_on_each_side_of_a_contribution():
    gross, _, estimated = _report_twr(
        trades=[_trade(quantity="10"), _trade(2, date=MIDDLE, quantity="10", price="120")],
        prices=[_price(), _price(MIDDLE, "120"), _price(END, "130")],
        costs={1: Decimal("4"), 2: Decimal("2")},
    )
    assert gross == Decimal("1.2") * Decimal("2600") / Decimal("2400") - 1
    # Opening capital 1000 + 4 fee, pre-flow 1200 - 52 tax - 2 fee;
    # post-flow 2400 - 52 tax, closing 2600 - 104 tax.
    expected = Decimal("1146") / 1004 * Decimal("2496") / 2348 - 1
    assert abs(estimated - expected) < Decimal("1e-24")


def test_tax_due_between_cash_flows_is_net_of_losses_by_the_valuation_date():
    gain_day = START + dt.timedelta(days=1)
    loss_day = MIDDLE + dt.timedelta(days=1)
    _, _, estimated = _report_twr(
        prices=[_price()],
        gains={gain_day: Decimal("100"), loss_day: Decimal("-100")},
        incomes=[_income(date=MIDDLE, gross="12", net="10")],
    )
    # Tax due EUR 26 when EUR 10 actually leaves via the dividend, zero at the end.
    expected = Decimal("984") / 1000 * Decimal("1000") / 974 - 1
    assert abs(estimated - expected) < Decimal("1e-24")


def test_zero_rate_reproduces_recorded_net_with_distinct_execution_and_quote():
    trades = [
        _trade(quantity="10"),
        _trade(2, date=MIDDLE, quantity="2", price="119"),
        _trade(3, date=MIDDLE, kind="sell", quantity="1", price="122"),
    ]
    _, recorded, estimated = _report_twr(
        rate="0",
        trades=trades,
        prices=[_price(START, "102"), _price(MIDDLE, "120")],
        costs={1: Decimal("3"), 2: Decimal("1"), 3: Decimal("2")},
        incomes=[_income(MIDDLE, "20", "17")],
        recurring=[_cost(END, "5")],
        gains={MIDDLE: Decimal("22")},
        withheld={MIDDLE: Decimal("2")},
    )
    assert recorded is not None and estimated == recorded


def test_missing_quote_on_intermediate_buy_preserves_historical_twr_only():
    new_security = _trade(2, date=MIDDLE)
    new_security.security_id = 2
    later_quote = _price(END, "110")
    later_quote.security_id = 2
    gross, recorded, estimated = _report_twr(
        trades=[_trade(), new_security], prices=[_price(), later_quote]
    )
    assert gross == recorded == Decimal("0.05")
    assert estimated is None


def test_missing_opening_quote_and_nonpositive_net_assets_have_no_estimated_twr():
    assert _report_twr(prices=[_price(END, "120")])[-1] is None
    assert _report_twr(gains={MIDDLE: Decimal("10000")})[-1] is None


def test_exhausted_terminal_value_has_a_return_when_the_last_period_opened_positive():
    # The remaining positions are still held. At the end, estimated tax due
    # covers the entire EUR 1,000 NAV. At that point there is no further flow.
    assert _report_twr(prices=[_price()], rate="100", gains={END: Decimal("1000")}) == (0, 0, -1)
    # The same zero on a flow date would be the opening base of another subperiod.
    assert (
        _report_twr(
            prices=[_price()],
            rate="100",
            gains={MIDDLE: Decimal("1000")},
            incomes=[_income(MIDDLE)],
            period_end=END,
        )[-1]
        is None
    )


def test_full_sale_reopening_and_zero_duration_keep_the_portfolio_twr_convention():
    closed = [_trade(), _trade(2, date=MIDDLE, kind="sell"), _trade(3, date=END)]
    assert _report_twr(trades=closed) == (None, None, None)
    assert _report_twr(period_end=START) == (None, None, None)
