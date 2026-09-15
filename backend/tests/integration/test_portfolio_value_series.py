"""Equivalence between bulk and naive historical valuation.

portfolio_value_series replaces a loop that ran two queries per security
and rebuilt FIFO for every date. The rewrite makes five years of movements
practical instead of taking over 45,000 queries and a minute, while keeping
results identical to the cent.

The naive implementation remains a REFERENCE. These tests compare exact
results for difficult cursor cases: prices starting after the first
purchase, gaps in history, closed and reopened positions, and unsorted dates.
"""

import datetime as dt
import io
from decimal import Decimal

from sqlalchemy import select

from app.finance.portfolio import calculate_position, calculate_position_eur
from app.models.price import Price
from app.repositories.security_repo import SecurityRepository
from app.repositories.trade_repo import TradeRepository
from app.services.performance_service import PerformanceService
from app.utils.currency import to_eur

from .conftest import TestingSessionLocal


def naive_price_as_of(db, security_id: int, as_of: dt.date):
    """Latest price not later than as_of.

    This lives in tests because production now uses a price cursor in
    portfolio_value_series. Keeping it as a public PriceRepository method
    solely for this test would falsely suggest it remained in application use.
    """
    return db.scalars(
        select(Price)
        .where(Price.security_id == security_id, Price.date <= as_of)
        .order_by(Price.date.desc())
    ).first()


def naive_portfolio_value_as_of(db, as_of: dt.date, *, include_same_day_trades: bool) -> Decimal:
    """ORIGINAL implementation, retained as a reference.

    Do not optimize it: its purpose is to be easy to read and demonstrate
    that the fast version has not changed results.
    """
    total = Decimal("0")
    for security in SecurityRepository(db).list():
        trades = [
            t
            for t in TradeRepository(db).list(security_id=security.id)
            if (t.date <= as_of if include_same_day_trades else t.date < as_of)
        ]
        if not trades:
            continue
        quantity = calculate_position(trades).quantity
        if quantity <= 0:
            continue
        price = naive_price_as_of(db, security.id, as_of)
        if price is not None:
            total += to_eur(Decimal(price.price_close), Decimal(price.fx_rate)) * quantity
        else:
            total += calculate_position_eur(trades).total_invested
    return total


def assert_series_matches_naive(dates, *, include_same_day_trades: bool):
    db = TestingSessionLocal()
    try:
        fast = PerformanceService(db).portfolio_value_series(
            dates, include_same_day_trades=include_same_day_trades
        )
        for d in dates:
            expected = naive_portfolio_value_as_of(
                db, d, include_same_day_trades=include_same_day_trades
            )
            assert fast[d] == expected, f"mismatch on {d}: {fast[d]} instead of {expected}"
    finally:
        db.close()


# --------------------------------------------------------------------------
# data construction helpers
# --------------------------------------------------------------------------
def _accounts(client):
    ref = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": ref,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _security(client, ticker, currency="EUR"):
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": currency},
    ).json()["id"]


def _trade(client, sec, acc, type_, date, qty, price, currency="EUR", fx_rate=None):
    payload = {
        "security_id": sec,
        "account_id": acc,
        "type": type_,
        "date": date,
        "quantity": qty,
        "price": price,
        "currency": currency,
    }
    if fx_rate is not None:
        payload["fx_rate"] = fx_rate
    resp = client.post("/api/v1/trades", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _prices(client, rows: str):
    csv_content = "date;ticker;close;fx_rate\n" + rows
    return client.post(
        "/api/v1/prices/import",
        files={"file": ("p.csv", io.BytesIO(csv_content.encode()), "text/csv")},
    ).json()


def _range(start: str, days: int) -> list[dt.date]:
    d0 = dt.date.fromisoformat(start)
    return [d0 + dt.timedelta(days=i) for i in range(days)]


# --------------------------------------------------------------------------
class TestEquivalence:
    def test_empty_portfolio(self, client):
        assert_series_matches_naive(_range("2026-01-01", 5), include_same_day_trades=True)

    def test_no_dates_requested(self, client):
        db = TestingSessionLocal()
        try:
            assert (
                PerformanceService(db).portfolio_value_series([], include_same_day_trades=True)
                == {}
            )
        finally:
            db.close()

    def test_prices_start_after_first_trade(self, client):
        """Before the first price, a position is valued at cost basis: the fallback branch a poorly managed cursor could skip."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-10", 10, 100)
        _prices(client, "2026-02-01;AAA;120;\n")

        assert_series_matches_naive(_range("2026-01-01", 60), include_same_day_trades=True)

    def test_gaps_in_price_history(self, client):
        """With sparse prices, carry forward the latest known price."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-05", 10, 100)
        _prices(
            client,
            "2026-01-10;AAA;110;\n2026-03-20;AAA;130;\n2026-06-01;AAA;90;\n",
        )

        assert_series_matches_naive(_range("2026-01-01", 200), include_same_day_trades=True)

    def test_position_closed_and_reopened(self, client):
        """When quantity reaches zero and later rises, the incremental tracker must clear lots and restart just like a full recalculation."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-05", 10, 100)
        _trade(client, sec, acc, "sell", "2026-03-05", 10, 120)
        _trade(client, sec, acc, "buy", "2026-05-05", 5, 90)
        _prices(client, "2026-01-05;AAA;100;\n2026-04-01;AAA;115;\n")

        assert_series_matches_naive(_range("2026-01-01", 180), include_same_day_trades=True)

    def test_same_day_flag_changes_the_result(self, client):
        """Keep both variants distinct: include_same_day_trades selects valuation before or after that day's trades."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-10", 10, 100)
        _prices(client, "2026-01-10;AAA;100;\n")
        day = dt.date(2026, 1, 10)

        db = TestingSessionLocal()
        try:
            service = PerformanceService(db)
            after = service.portfolio_value_series([day], include_same_day_trades=True)[day]
            before = service.portfolio_value_series([day], include_same_day_trades=False)[day]
        finally:
            db.close()

        assert after == Decimal("1000")
        assert before == Decimal("0")

    def test_multiple_securities_and_currencies(self, client):
        acc = _accounts(client)
        eur = _security(client, "AAA")
        usd = _security(client, "BBB", "USD")
        _trade(client, eur, acc, "buy", "2026-01-05", 10, 100)
        _trade(client, usd, acc, "buy", "2026-02-05", 10, 50, currency="USD", fx_rate=0.9)
        _prices(client, "2026-03-01;AAA;110;\n2026-03-01;BBB;60;0.92\n")

        assert_series_matches_naive(_range("2026-01-01", 120), include_same_day_trades=True)
        assert_series_matches_naive(_range("2026-01-01", 120), include_same_day_trades=False)

    def test_unsorted_and_duplicated_dates(self, client):
        """The caller need not supply sorted or distinct dates."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-05", 10, 100)
        _prices(client, "2026-02-01;AAA;120;\n")
        dates = [
            dt.date(2026, 3, 1),
            dt.date(2026, 1, 1),
            dt.date(2026, 3, 1),
            dt.date(2026, 2, 15),
        ]

        db = TestingSessionLocal()
        try:
            series = PerformanceService(db).portfolio_value_series(
                dates, include_same_day_trades=True
            )
            for d in set(dates):
                assert series[d] == naive_portfolio_value_as_of(db, d, include_same_day_trades=True)
        finally:
            db.close()


class TestSingleDateEntryPoint:
    def test_as_of_matches_the_series(self, client):
        """_portfolio_value_as_of must remain a special case of the series rather than a separate implementation."""
        acc = _accounts(client)
        sec = _security(client, "AAA")
        _trade(client, sec, acc, "buy", "2026-01-05", 10, 100)
        _prices(client, "2026-02-01;AAA;120;\n")
        day = dt.date(2026, 6, 1)

        db = TestingSessionLocal()
        try:
            service = PerformanceService(db)
            assert service._portfolio_value_as_of(day, include_same_day_trades=True) == (
                naive_portfolio_value_as_of(db, day, include_same_day_trades=True)
            )
        finally:
            db.close()


class TestQueryBudget:
    def test_series_cost_does_not_grow_with_the_number_of_dates(self, client):
        """The rewrite makes cost depend on data volume, not the number of requested dates. This constraint prevents a silent recurrence of the regression."""
        from sqlalchemy import event

        from .conftest import engine

        acc = _accounts(client)
        for i in range(5):
            sec = _security(client, f"S{i}")
            _trade(client, sec, acc, "buy", "2026-01-05", 10, 100)

        counter = {"n": 0}

        def _count(conn, cursor, statement, parameters, context, executemany):
            # The budget measures service application queries. R-04's explicit BEGIN
            # is transactional, does not grow with the number of dates,
            # and may occur only on the session's first call.
            if statement.lstrip().upper().startswith(("SELECT", "WITH")):
                counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _count)
        try:
            db = TestingSessionLocal()
            try:
                service = PerformanceService(db)
                counter["n"] = 0
                service.portfolio_value_series(
                    _range("2026-01-01", 5), include_same_day_trades=True
                )
                few = counter["n"]

                counter["n"] = 0
                service.portfolio_value_series(
                    _range("2026-01-01", 400), include_same_day_trades=True
                )
                many = counter["n"]
            finally:
                db.close()
        finally:
            event.remove(engine, "before_cursor_execute", _count)

        assert (
            few == many
        ), f"{few} queries for 5 dates, {many} for 400: cost scales with date count"
        assert many <= 5, f"{many} queries for a series: too many for a bulk load"
