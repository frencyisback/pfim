"""Explicit performance contract and temporal cutoff.

All data is created in the shared in-memory fixture database;
the operational database is neither opened nor copied.
"""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal


def _setup_portfolio(client):
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Cash", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    security = client.post(
        "/api/v1/securities",
        json={
            "ticker": "PERF",
            "name": "Performance fixture",
            "type": "stock",
            "currency": "EUR",
        },
    ).json()
    today = dt.date.today()
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "buy",
            "date": (today - dt.timedelta(days=500)).isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    assert (
        client.post(
            f"/api/v1/trades/{buy['id']}/costs",
            json={"cost_type": "commission", "amount": 10, "currency": "EUR"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/income-events",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "event_type": "dividend",
                "payment_date": (today - dt.timedelta(days=100)).isoformat(),
                "total_amount": 100,
                "tax_withheld": 25,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/portfolio-costs",
            json={
                "account_id": investment["id"],
                "date": (today - dt.timedelta(days=50)).isoformat(),
                "cost_type": "custody_fee",
                "amount": 20,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    prices = "date;ticker;close\n" f"{(today - dt.timedelta(days=1)).isoformat()};PERF;12\n"
    assert (
        client.post(
            "/api/v1/prices/import",
            files={"file": ("prices.csv", io.BytesIO(prices.encode()), "text/csv")},
        ).json()["errors"]
        == 0
    )
    return security, investment, today


def test_named_bases_are_coherent_and_legacy_gross_remains_an_alias(client):
    security, _, _ = _setup_portfolio(client)

    default = client.get("/api/v1/performance/portfolio").json()
    explicit_default = client.get(
        "/api/v1/performance/portfolio?income_basis=net&cost_basis=exclude"
    ).json()
    assert default == explicit_default

    legacy_gross = client.get("/api/v1/performance/portfolio?gross=true").json()
    named_gross = client.get(
        "/api/v1/performance/portfolio?income_basis=gross&cost_basis=exclude"
    ).json()
    assert legacy_gross == named_gross

    net_with_costs = client.get(
        "/api/v1/performance/portfolio?income_basis=net&cost_basis=include"
    ).json()
    assert default["metadata"]["income_basis"] == "net"
    assert default["metadata"]["cost_basis"] == "exclude"
    assert named_gross["metadata"]["income_basis"] == "gross"
    assert net_with_costs["metadata"]["cost_basis"] == "include"

    assert Decimal(named_gross["total_income_received"]) == Decimal("100")
    assert Decimal(default["total_income_received"]) == Decimal("75")
    assert Decimal(named_gross["total_return"]) > Decimal(default["total_return"])
    assert Decimal(net_with_costs["total_return"]) < Decimal(default["total_return"])
    assert Decimal(net_with_costs["time_weighted_return"]) < Decimal(
        default["time_weighted_return"]
    )

    security_default = client.get(f"/api/v1/performance/{security['id']}").json()
    security_gross = client.get(f"/api/v1/performance/{security['id']}?income_basis=gross").json()
    security_with_costs = client.get(
        f"/api/v1/performance/{security['id']}?cost_basis=include"
    ).json()
    assert Decimal(security_gross["yield_on_cost"]) > Decimal(security_default["yield_on_cost"])
    assert Decimal(security_with_costs["total_return"]) < Decimal(security_default["total_return"])
    assert security_with_costs["yield_on_cost"] == security_default["yield_on_cost"]
    assert security_with_costs["metadata"]["recurring_costs_scope"] == "not_allocated_to_security"

    conflict = client.get("/api/v1/performance/portfolio?gross=true&income_basis=net")
    assert conflict.status_code == 400
    assert conflict.json()["error_code"] == "VALIDATION_ERROR"


def test_future_rows_do_not_change_current_performance(client):
    security, investment, today = _setup_portfolio(client)
    query = "/api/v1/performance/portfolio?income_basis=net&cost_basis=include"
    security_query = f"/api/v1/performance/{security['id']}?income_basis=net&cost_basis=include"
    before_portfolio = client.get(query).json()
    before_security = client.get(security_query).json()

    future = today + dt.timedelta(days=30)
    sale = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "sell",
            "date": future.isoformat(),
            "quantity": 5,
            "price": 100,
            "currency": "EUR",
        },
    ).json()
    assert (
        client.post(
            f"/api/v1/trades/{sale['id']}/costs",
            json={"cost_type": "commission", "amount": 50, "currency": "EUR"},
        ).status_code
        == 201
    )
    future_price = f"date;ticker;close\n{future.isoformat()};PERF;999\n"
    assert (
        client.post(
            "/api/v1/prices/import",
            files={"file": ("future.csv", io.BytesIO(future_price.encode()), "text/csv")},
        ).json()["errors"]
        == 0
    )
    assert (
        client.post(
            "/api/v1/income-events",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "event_type": "dividend",
                "payment_date": future.isoformat(),
                "total_amount": 500,
                "tax_withheld": 0,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/portfolio-costs",
            json={
                "account_id": investment["id"],
                "date": future.isoformat(),
                "cost_type": "custody_fee",
                "amount": 500,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )

    assert client.get(query).json() == before_portfolio
    assert client.get(security_query).json() == before_security
