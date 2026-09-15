"""A13: trailing period independent of filters, future income, and FIFO cost as of today."""

import datetime as dt
from decimal import Decimal

import pytest


@pytest.mark.parametrize("with_position", [True, False])
def test_trailing_uses_own_window_and_current_cost_even_when_selected_period_is_empty(
    client, with_position
):
    today = dt.date.today()
    checking = client.post(
        "/api/v1/accounts", json={"name": "Cash", "type": "checking", "opened_on": "2000-01-01"}
    ).json()["id"]
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": checking,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    security = client.post(
        "/api/v1/securities",
        json={"ticker": "TRAIL", "name": "Trailing", "type": "stock", "currency": "EUR"},
    ).json()["id"]
    if with_position:
        for offset, price in ((-400, "100"), (1, "900")):
            response = client.post(
                "/api/v1/trades",
                json={
                    "security_id": security,
                    "account_id": account,
                    "type": "buy",
                    "date": (today + dt.timedelta(days=offset)).isoformat(),
                    "quantity": "1",
                    "price": price,
                    "currency": "EUR",
                },
            )
            assert response.status_code == 201, response.text
    for offset, gross, withheld in (
        (-365, "1000", "0"),
        (-364, "10", "2"),
        (0, "20", "5"),
        (1, "2000", "0"),
    ):
        response = client.post(
            "/api/v1/income-events",
            json={
                "security_id": security,
                "account_id": account,
                "event_type": "dividend",
                "payment_date": (today + dt.timedelta(days=offset)).isoformat(),
                "total_amount": gross,
                "tax_withheld": withheld,
                "currency": "EUR",
            },
        )
        assert response.status_code == 201, response.text
    cases = [
        ({}, 4, "3023"),
        ({"date_from": today.isoformat(), "date_to": today.isoformat()}, 1, "15"),
        (
            {
                "date_from": (today - dt.timedelta(days=100)).isoformat(),
                "date_to": (today - dt.timedelta(days=50)).isoformat(),
            },
            0,
            "0",
        ),
        (
            {
                "date_from": (today + dt.timedelta(days=1)).isoformat(),
                "date_to": (today + dt.timedelta(days=1)).isoformat(),
            },
            1,
            "2000",
        ),
    ]
    for params, count, net in cases:
        response = client.get("/api/v1/reports/dividends-analysis", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["events_count"] == count
        assert Decimal(body["total_net"]) == Decimal(net)
        assert Decimal(body["trailing_12m_net"]) == Decimal("23")
        if with_position:
            assert Decimal(body["portfolio_yield_on_cost_pct"]) == Decimal("23")
        else:
            assert body["portfolio_yield_on_cost_pct"] is None
    if with_position:
        metrics = client.get(
            f"/api/v1/performance/{security}", params={"income_basis": "net"}
        ).json()
        assert Decimal(metrics["yield_on_cost"]) == Decimal("23")


def test_empty_trailing_with_an_open_position_is_zero_not_unavailable(client):
    checking = client.post(
        "/api/v1/accounts", json={"name": "Cash", "type": "checking", "opened_on": "2000-01-01"}
    ).json()["id"]
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": checking,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    security = client.post(
        "/api/v1/securities",
        json={"ticker": "ZERO", "name": "Zero", "type": "stock", "currency": "EUR"},
    ).json()["id"]
    response = client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": account,
            "type": "buy",
            "date": dt.date.today().isoformat(),
            "quantity": "1",
            "price": "100",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201, response.text
    report = client.get("/api/v1/reports/dividends-analysis").json()
    assert Decimal(report["trailing_12m_net"]) == 0
    assert Decimal(report["portfolio_yield_on_cost_pct"]) == 0
