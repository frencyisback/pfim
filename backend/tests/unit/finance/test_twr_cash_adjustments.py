"""TWR on synthetic collections, without database sessions or queries.

Examples check economic results for all four income/cost combinations,
including opening, boundaries, and same-date operations.
"""

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.performance_service import PerformanceService

START = dt.date(2025, 1, 1)
MIDDLE = dt.date(2025, 7, 1)
END = dt.date(2026, 1, 1)


def _trade(trade_id=1, *, date=START, kind="buy", quantity="1", price="100"):
    quantity = Decimal(quantity)
    price = Decimal(price)
    return SimpleNamespace(
        id=trade_id,
        security_id=1,
        date=date,
        type=kind,
        quantity=quantity,
        price=price,
        quote_price=price,
        total_eur=quantity * price,
    )


def _price(date=START, amount="100"):
    return SimpleNamespace(
        security_id=1, date=date, price_close=Decimal(amount), fx_rate=Decimal("1")
    )


def _income(date=MIDDLE, gross="10", net=None):
    return SimpleNamespace(
        payment_date=date,
        total_eur=Decimal(gross),
        net_amount_eur=Decimal(net if net is not None else gross),
    )


def _cost(date=MIDDLE, amount="5"):
    return SimpleNamespace(date=date, amount_eur=Decimal(amount))


def _twr(
    *,
    trades=None,
    prices=None,
    income_events=(),
    costs_by_trade=None,
    recurring_costs=(),
    income_basis="net",
    period_start=None,
    period_end=END,
    net_modes=(False, True),
):
    # Repositories are not initialized: an unexpected read fails instead of
    # accessing a database. All sources are preloaded.
    service = PerformanceService.__new__(PerformanceService)
    return service._portfolio_twr_variants(
        net_modes=net_modes,
        income_basis=income_basis,
        costs_by_trade=costs_by_trade if costs_by_trade is not None else {},
        recurring_costs=list(recurring_costs),
        as_of=period_end,
        period_start=period_start,
        trades=sorted(trades if trades is not None else [_trade()], key=lambda t: (t.date, t.id)),
        income_events=list(income_events),
        prices=prices if prices is not None else [_price()],
    )


def test_distribution_on_unchanged_capital_returns_ten_percent():
    results = _twr(income_events=[_income()])
    assert results == {False: Decimal("0.1"), True: Decimal("0.1")}


@pytest.mark.parametrize("income_basis, income_return", [("net", "0.10"), ("gross", "0.12")])
def test_income_basis_and_cost_basis_are_independent(income_basis, income_return):
    results = _twr(
        income_events=[_income(gross="12", net="10")],
        recurring_costs=[_cost(amount="5")],
        income_basis=income_basis,
    )
    assert results[False] == Decimal(income_return)
    assert results[True] == Decimal(income_return) - Decimal("0.05")


def test_cost_only_date_reduces_return_without_creating_invested_capital():
    results = _twr(recurring_costs=[_cost(amount="10")])
    assert results == {False: Decimal("0"), True: Decimal("-0.1")}


@pytest.mark.parametrize("income", ["0", "10"])
def test_opening_income_and_trade_cost_are_counted_once(income):
    results = _twr(
        income_events=[_income(date=START, gross=income)],
        costs_by_trade={1: Decimal("5")},
    )
    assert results[False] == Decimal(income) / Decimal("100")
    assert results[True] == (Decimal("100") + Decimal(income)) / Decimal("105") - 1


def test_opening_factor_aggregates_recurring_and_trade_costs_and_multiple_distributions():
    results = _twr(
        income_events=[_income(START, "6"), _income(START, "4")],
        costs_by_trade={1: Decimal("2")},
        recurring_costs=[_cost(START, "3")],
    )
    assert results[False] == Decimal("0.1")
    assert results[True] == Decimal("110") / Decimal("105") - 1


def test_opening_factor_then_later_distribution_and_cost_compound_once():
    results = _twr(
        income_events=[_income(START), _income(MIDDLE)],
        costs_by_trade={1: Decimal("5")},
        recurring_costs=[_cost(MIDDLE, "5")],
    )
    assert results[False] == Decimal("0.21")
    expected = Decimal("110") / Decimal("105") * Decimal("1.05") - 1
    assert results[True] == expected


@pytest.mark.parametrize("event_date", [MIDDLE, END])
def test_already_open_period_includes_income_and_cost_on_both_boundaries(event_date):
    results = _twr(
        period_start=MIDDLE,
        income_events=[_income(event_date)],
        recurring_costs=[_cost(event_date)],
    )
    assert results == {False: Decimal("0.1"), True: Decimal("0.05")}


def test_requested_period_excludes_earlier_and_future_distributions_and_costs():
    outside = [MIDDLE - dt.timedelta(days=1), END + dt.timedelta(days=1)]
    results = _twr(
        period_start=MIDDLE,
        income_events=[_income(date, "50") for date in outside] + [_income(END)],
        recurring_costs=[_cost(date, "40") for date in outside] + [_cost(END)],
        costs_by_trade={1: Decimal("30")},
    )
    assert results == {False: Decimal("0.1"), True: Decimal("0.05")}


def test_income_and_cost_before_first_trade_do_not_change_the_initial_factor():
    before = START - dt.timedelta(days=1)
    results = _twr(income_events=[_income(before, "50")], recurring_costs=[_cost(before, "40")])
    assert results == {False: Decimal("0"), True: Decimal("0")}


@pytest.mark.parametrize("sell_first", [False, True])
def test_simultaneous_buys_sells_distributions_and_costs_share_one_date(sell_first):
    buy_id, sell_id = (3, 2) if sell_first else (2, 3)
    results = _twr(
        trades=[_trade(), _trade(buy_id, date=MIDDLE), _trade(sell_id, date=MIDDLE, kind="sell")],
        income_events=[_income(MIDDLE, "4"), _income(MIDDLE, "6")],
        costs_by_trade={buy_id: Decimal("2"), sell_id: Decimal("3")},
    )
    assert results == {False: Decimal("0.1"), True: Decimal("0.05")}


def test_zero_net_external_flow_still_accounts_for_cost_and_distribution():
    # Sale 5, dividend 5, costs 10: zero net flow but economic cost 5.
    results = _twr(
        trades=[_trade(), _trade(2, date=MIDDLE, kind="sell", quantity="0.05")],
        income_events=[_income(MIDDLE, "5")],
        costs_by_trade={2: Decimal("10")},
    )
    assert results == {False: Decimal("0.05"), True: Decimal("-0.05")}


def test_cash_adjustments_do_not_change_price_return_between_contributions():
    results = _twr(
        trades=[_trade(), _trade(2, date=MIDDLE, price="110")],
        prices=[_price(), _price(MIDDLE, "110"), _price(END, "121")],
    )
    assert results == {False: Decimal("0.21"), True: Decimal("0.21")}


@pytest.mark.parametrize("reopen", [False, True])
@pytest.mark.parametrize("sale_price", ["100", "90"])
def test_fully_closed_portfolio_remains_unavailable_even_after_reopening(reopen, sale_price):
    # Capital does not remain open even when the quote differs from the execution price.
    trades = [_trade(), _trade(2, date=MIDDLE, kind="sell", price=sale_price)]
    if reopen:
        trades.append(_trade(3, date=END - dt.timedelta(days=30)))
    results = _twr(
        trades=trades,
        income_events=[_income(MIDDLE)],
        costs_by_trade={2: Decimal("5")},
    )
    assert results == {False: None, True: None}


def test_period_starting_after_closure_can_measure_only_the_new_open_segment():
    reopen_date = END - dt.timedelta(days=30)
    results = _twr(
        period_start=MIDDLE + dt.timedelta(days=1),
        trades=[
            _trade(),
            _trade(2, date=MIDDLE, kind="sell"),
            _trade(3, date=reopen_date),
        ],
        income_events=[_income(reopen_date)],
        costs_by_trade={3: Decimal("5")},
    )
    assert results[False] == Decimal("0.1")
    assert results[True] == Decimal("110") / Decimal("105") - 1


@pytest.mark.parametrize("reopen", [False, True])
def test_full_sale_on_requested_period_start_remains_unavailable(reopen):
    # The quote stays at 100 while execution is 90: the pre-flow accounting
    # remainder plus sale must not imply a position after closure.
    trades = [_trade(), _trade(2, date=MIDDLE, kind="sell", price="90")]
    if reopen:
        trades.append(_trade(3, date=END - dt.timedelta(days=30)))
    assert _twr(trades=trades, period_start=MIDDLE) == {False: None, True: None}


def test_income_and_cost_on_distinct_dates_compound_geometrically():
    results = _twr(
        income_events=[_income(MIDDLE)],
        recurring_costs=[_cost(END, "5")],
    )
    assert results == {False: Decimal("0.1"), True: Decimal("0.045")}


def test_twr_on_the_opening_date_remains_unavailable():
    assert _twr(period_end=START, income_events=[_income(START)]) == {False: None, True: None}


def test_cost_modes_do_not_mutate_the_shared_pre_flow_valuations():
    kwargs = dict(income_events=[_income()], recurring_costs=[_cost()])
    pair = _twr(**kwargs)
    assert _twr(net_modes=(True, False), **kwargs) == pair
    assert _twr(net_modes=(True,), **kwargs) == {True: pair[True]}
    assert _twr(net_modes=(False,), **kwargs) == {False: pair[False]}
