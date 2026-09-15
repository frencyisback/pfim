"""Regression tests for temporal account membership (R-06).

The shared fixture uses only in-memory SQLite. Historical closure dates
needed to test the right boundary are set up in the test database,
without opening operational files or snapshots.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.models.account import Account
from tests.integration.conftest import TestingSessionLocal


def _create_category(client, name: str, type_: str) -> int:
    response = client.post("/api/v1/categories", json={"name": name, "type": type_})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_transaction(client, account_id: int, category_id: int, date: dt.date, amount: int):
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": date.isoformat(),
            "amount": amount,
            "currency": "EUR",
        },
    )
    assert response.status_code == 201, response.text


def test_new_account_defaults_to_today_and_rejects_a_future_opening(client):
    today = dt.date.today()
    created = client.post(
        "/api/v1/accounts",
        json={"name": "Opening today", "type": "checking"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["opened_on"] == today.isoformat()
    assert created.json()["closed_on"] is None

    future = client.post(
        "/api/v1/accounts",
        json={
            "name": "Future opening",
            "type": "checking",
            "opened_on": (today + dt.timedelta(days=1)).isoformat(),
        },
    )
    assert future.status_code == 422


def test_investment_cannot_open_before_its_reference_account(client):
    today = dt.date.today()
    reference = client.post(
        "/api/v1/accounts",
        json={"name": "Recent cash", "type": "checking"},
    ).json()

    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Earlier investment account",
            "type": "investment",
            "reference_account_id": reference["id"],
            "opened_on": (today - dt.timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_deactivation_sets_close_and_reactivation_clears_it(client):
    today = dt.date.today()
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Lifecycle", "type": "cash"},
    ).json()

    closed = client.post(f"/api/v1/accounts/{account['id']}/deactivate")
    assert closed.status_code == 200, closed.text
    assert closed.json()["is_active"] is False
    assert closed.json()["closed_on"] == today.isoformat()

    reopened = client.put(
        f"/api/v1/accounts/{account['id']}",
        json={"is_active": True},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["is_active"] is True
    assert reopened.json()["closed_on"] is None

    closed_by_update = client.put(
        f"/api/v1/accounts/{account['id']}",
        json={"is_active": False},
    )
    assert closed_by_update.status_code == 200, closed_by_update.text
    assert closed_by_update.json()["closed_on"] == today.isoformat()


def test_balance_history_and_net_worth_respect_both_lifecycle_bounds(client):
    today = dt.date.today()
    opened_on = today - dt.timedelta(days=10)
    income_date = today - dt.timedelta(days=8)
    snapshot_date = today - dt.timedelta(days=7)
    closed_on = today - dt.timedelta(days=5)
    before_open = opened_on - dt.timedelta(days=1)

    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Temporal account",
            "type": "checking",
            "opened_on": opened_on.isoformat(),
        },
    ).json()
    income = _create_category(client, "Temporal income", "income")
    expense = _create_category(client, "Temporal expense", "expense")
    _create_transaction(client, account["id"], income, income_date, 100)
    _create_transaction(client, account["id"], expense, closed_on, -100)

    # Simulate a consistent historical closure (zero balance) in the in-memory DB
    # to observe post-closure behavior as of today.
    with TestingSessionLocal() as session:
        persisted = session.get(Account, account["id"])
        assert persisted is not None
        persisted.is_active = False
        persisted.closed_on = closed_on
        session.commit()

    before_balance = client.get(
        f"/api/v1/accounts/{account['id']}/balance",
        params={"as_of_date": before_open.isoformat()},
    ).json()
    assert Decimal(before_balance["balance"]) == 0

    during_balance = client.get(
        f"/api/v1/accounts/{account['id']}/balance",
        params={"as_of_date": snapshot_date.isoformat()},
    ).json()
    assert Decimal(during_balance["balance"]) == 100

    after_balance = client.get(f"/api/v1/accounts/{account['id']}/balance").json()
    assert Decimal(after_balance["balance"]) == 0

    before_report = client.get(
        "/api/v1/reports/net-worth",
        params={"as_of_date": before_open.isoformat()},
    ).json()
    assert before_report["by_account"] == []
    assert Decimal(before_report["total_accounts_balance"]) == 0

    during_report = client.get(
        "/api/v1/reports/net-worth",
        params={"as_of_date": snapshot_date.isoformat()},
    ).json()
    assert during_report["by_account"] == [
        {"account_id": account["id"], "name": "Temporal account", "balance": "100.000000"}
    ]

    after_report = client.get("/api/v1/reports/net-worth").json()
    assert after_report["by_account"] == []
    assert Decimal(after_report["total_accounts_balance"]) == 0

    history = client.get(f"/api/v1/accounts/{account['id']}/history").json()
    assert history == [
        {"date": opened_on.isoformat(), "balance": "0.000000"},
        {"date": income_date.isoformat(), "balance": "100.000000"},
        {"date": closed_on.isoformat(), "balance": "0.000000"},
    ]


def test_legacy_null_dates_remain_present_in_historical_reports(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Legacy", "type": "checking", "opening_balance": 25},
    ).json()
    with TestingSessionLocal() as session:
        persisted = session.get(Account, account["id"])
        assert persisted is not None
        persisted.opened_on = None
        persisted.closed_on = None
        session.commit()

    old_date = dt.date(2000, 1, 1)
    report = client.get(
        "/api/v1/reports/net-worth",
        params={"as_of_date": old_date.isoformat()},
    ).json()
    assert report["by_account"] == [
        {"account_id": account["id"], "name": "Legacy", "balance": "25.000000"}
    ]


def test_every_dated_write_rejects_accounts_not_yet_open(client):
    today = dt.date.today()
    before_open = today - dt.timedelta(days=1)
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Recent cash", "type": "checking", "opened_on": today.isoformat()},
    ).json()
    other_cash = client.post(
        "/api/v1/accounts",
        json={"name": "Other recent cash", "type": "cash", "opened_on": today.isoformat()},
    ).json()
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Recent investment account",
            "type": "investment",
            "reference_account_id": cash["id"],
            "opened_on": today.isoformat(),
        },
    ).json()
    category = _create_category(client, "Income before opening", "income")
    security = client.post(
        "/api/v1/securities",
        json={"ticker": "TIME", "name": "Temporal", "type": "stock", "currency": "EUR"},
    ).json()

    responses = [
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": cash["id"],
                "category_id": category,
                "date": before_open.isoformat(),
                "amount": 10,
            },
        ),
        client.post(
            "/api/v1/transactions/transfer",
            json={
                "from_account_id": cash["id"],
                "to_account_id": other_cash["id"],
                "date": before_open.isoformat(),
                "amount": 10,
            },
        ),
        client.post(
            "/api/v1/trades",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "type": "buy",
                "date": before_open.isoformat(),
                "quantity": 1,
                "price": 10,
                "currency": "EUR",
            },
        ),
        client.post(
            "/api/v1/income-events",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "event_type": "dividend",
                "payment_date": before_open.isoformat(),
                "total_amount": 1,
                "currency": "EUR",
            },
        ),
        client.post(
            "/api/v1/portfolio-costs",
            json={
                "account_id": investment["id"],
                "date": before_open.isoformat(),
                "cost_type": "custody_fee",
                "amount": 1,
                "currency": "EUR",
            },
        ),
    ]

    assert [response.status_code for response in responses] == [400, 400, 400, 400, 400]
    assert all(response.json()["error_code"] == "VALIDATION_ERROR" for response in responses)
    assert client.get("/api/v1/transactions").json()["total"] == 0
    assert client.get("/api/v1/trades").json() == []
    assert client.get("/api/v1/income-events").json() == []
    assert client.get("/api/v1/portfolio-costs").json() == []


def test_historical_closure_cannot_be_erased_by_reactivation(client):
    today = dt.date.today()
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Historical closure",
            "type": "cash",
            "opened_on": (today - dt.timedelta(days=10)).isoformat(),
        },
    ).json()
    closed_on = today - dt.timedelta(days=1)
    with TestingSessionLocal() as session:
        persisted = session.get(Account, account["id"])
        assert persisted is not None
        persisted.is_active = False
        persisted.closed_on = closed_on
        session.commit()

    response = client.put(f"/api/v1/accounts/{account['id']}", json={"is_active": True})

    assert response.status_code == 409
    assert response.json()["detail"]["reactivation_policy"] == "same_day_undo_only"
    persisted = next(
        item for item in client.get("/api/v1/accounts").json() if item["id"] == account["id"]
    )
    assert persisted["is_active"] is False
    assert persisted["closed_on"] == closed_on.isoformat()
