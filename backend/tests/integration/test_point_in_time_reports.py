"""Regression tests for net-worth and portfolio temporal cutoffs.

All fixtures use the suite's in-memory database; no test accesses
the operational database.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.repositories.price_repo import PriceRepository
from app.services.performance_service import PerformanceService

from .conftest import TestingSessionLocal


def _checking(
    client,
    *,
    opening_balance: int = 0,
    opened_on: dt.date | None = None,
) -> int:
    payload = {
        "name": "Account point-in-time",
        "type": "checking",
        "opening_balance": opening_balance,
    }
    if opened_on is not None:
        payload["opened_on"] = opened_on.isoformat()
    response = client.post(
        "/api/v1/accounts",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _investment(
    client,
    reference_account_id: int,
    *,
    opened_on: dt.date | None = None,
) -> int:
    payload = {
        "name": "Investment account point-in-time",
        "type": "investment",
        "reference_account_id": reference_account_id,
    }
    if opened_on is not None:
        payload["opened_on"] = opened_on.isoformat()
    response = client.post(
        "/api/v1/accounts",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _security(client) -> int:
    response = client.post(
        "/api/v1/securities",
        json={
            "name": "Security point-in-time",
            "ticker": "PIT",
            "type": "stock",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _trade(client, security_id: int, account_id: int, date: dt.date, quantity: int, price: int):
    response = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": account_id,
            "type": "buy",
            "date": date.isoformat(),
            "quantity": quantity,
            "price": price,
            "currency": "EUR",
        },
    )
    assert response.status_code == 201, response.text


def _price(client, security_id: int, date: dt.date, close: int):
    response = client.post(
        "/api/v1/prices",
        json={"security_id": security_id, "date": date.isoformat(), "price_close": close},
    )
    assert response.status_code == 201, response.text


def test_net_worth_and_current_portfolio_share_a_today_cutoff(client):
    today = dt.date.today()
    as_of = today - dt.timedelta(days=2)
    future = today + dt.timedelta(days=1)

    cash = _checking(client, opening_balance=5000, opened_on=as_of)
    investment = _investment(client, cash, opened_on=as_of)
    security = _security(client)

    _trade(client, security, investment, as_of, quantity=10, price=100)
    _price(client, security, as_of, close=110)

    # Valid future data must not affect today's snapshot.
    _trade(client, security, investment, future, quantity=10, price=200)
    _price(client, security, future, close=999)

    snapshot = client.get("/api/v1/reports/net-worth", params={"as_of_date": as_of.isoformat()})
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert Decimal(body["total_accounts_balance"]) == Decimal("4000")
    assert Decimal(body["total_portfolio_value"]) == Decimal("1100")
    assert Decimal(body["net_worth"]) == Decimal("5100")
    assert body["portfolio_valuation"] == {
        "price_policy": "latest_price_at_or_before_date_else_fifo_cost",
        "cost_fallback_used": False,
        "cost_fallback_securities": [],
    }

    positions = client.get("/api/v1/portfolio").json()
    assert len(positions) == 1
    assert Decimal(positions[0]["quantity"]) == Decimal("10")
    assert Decimal(positions[0]["current_price_eur"]) == Decimal("110")
    assert positions[0]["current_price_date"] == as_of.isoformat()

    summary = client.get("/api/v1/portfolio/summary").json()
    assert Decimal(summary["total_invested"]) == Decimal("1000")
    assert Decimal(summary["total_current_value"]) == Decimal("1100")

    history = client.get("/api/v1/reports/net-worth/history").json()
    assert history[-1]["date"] == as_of.isoformat()
    assert Decimal(history[-1]["portfolio_value"]) == Decimal("1100")
    assert all(point["date"] <= today.isoformat() for point in history)


def test_net_worth_rejects_a_future_cutoff(client):
    future = dt.date.today() + dt.timedelta(days=1)
    response = client.get("/api/v1/reports/net-worth", params={"as_of_date": future.isoformat()})
    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_net_worth_declares_fifo_cost_fallback_until_a_price_exists(client):
    today = dt.date.today()
    as_of = today - dt.timedelta(days=2)
    future = today + dt.timedelta(days=1)

    cash = _checking(client, opening_balance=5000, opened_on=as_of)
    investment = _investment(client, cash, opened_on=as_of)
    security = _security(client)
    _trade(client, security, investment, as_of, quantity=10, price=100)

    # New trades also record a price on the trade date. To reproduce a
    # legacy record without a quote in a controlled way, remove that price
    # only from the test's in-memory database.
    db = TestingSessionLocal()
    try:
        for price in PriceRepository(db).list_all():
            db.delete(price)
        db.commit()
    finally:
        db.close()

    # A future quote cannot value a position retroactively.
    _price(client, security, future, close=999)

    db = TestingSessionLocal()
    try:
        prices = [
            (price.date, Decimal(price.price_close_eur)) for price in PriceRepository(db).list_all()
        ]
        assert prices == [(future, Decimal("999"))]
        values, fallbacks = PerformanceService(db).portfolio_value_series_details(
            [as_of], include_same_day_trades=True
        )
        assert values[as_of] == Decimal("1000")
        assert fallbacks[as_of] == [security]
    finally:
        db.close()

    response = client.get("/api/v1/reports/net-worth", params={"as_of_date": as_of.isoformat()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["total_portfolio_value"]) == Decimal("1000")
    assert body["portfolio_valuation"]["cost_fallback_used"] is True
    assert body["portfolio_valuation"]["cost_fallback_securities"] == [
        {
            "security_id": security,
            "ticker": "PIT",
            "name": "Security point-in-time",
        }
    ]

    history = client.get("/api/v1/reports/net-worth/history")
    assert history.status_code == 200, history.text
    point = next(row for row in history.json() if row["date"] == as_of.isoformat())
    assert point["portfolio_valuation"]["cost_fallback_used"] is True
    assert point["portfolio_valuation"]["cost_fallback_securities"][0]["security_id"] == security
