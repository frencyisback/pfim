"""A04/A05 HTTP-contract regression tests using only the fixture's in-memory database."""

import datetime as dt
from decimal import Decimal

import pytest


def _post(client, path, payload):
    response = client.post(path, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _position(client, buy_date):
    cash = _post(
        client,
        "/api/v1/accounts",
        {"name": "Cash A04-A05", "type": "checking", "opened_on": "2000-01-01"},
    )
    investment = _post(
        client,
        "/api/v1/accounts",
        {
            "name": "Investment account A04-A05",
            "type": "investment",
            "reference_account_id": cash["id"],
            "opened_on": "2000-01-01",
        },
    )
    security = _post(
        client,
        "/api/v1/securities",
        {"ticker": "CASHADJ", "name": "Return example", "type": "stock", "currency": "EUR"},
    )
    trade = _post(
        client,
        "/api/v1/trades",
        {
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "buy",
            "date": buy_date.isoformat(),
            "quantity": 1,
            "price": 100,
            "currency": "EUR",
        },
    )
    return security, investment, trade


def _performance(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("cost_basis", ["exclude", "include"])
def test_first_day_mwr_is_unavailable_for_security_and_portfolio(client, cost_basis):
    security, _, trade = _position(client, dt.date.today())
    if cost_basis == "include":
        _post(
            client,
            f"/api/v1/trades/{trade['id']}/costs",
            {"cost_type": "commission", "amount": 5, "currency": "EUR"},
        )
    for target in (str(security["id"]), "portfolio"):
        body = _performance(client, f"/api/v1/performance/{target}?cost_basis={cost_basis}")
        assert body["money_weighted_return"] is None


def test_mwr_becomes_calculable_once_the_investment_has_a_time_period(client):
    security, _, _ = _position(client, dt.date.today() - dt.timedelta(days=1))
    for target in (str(security["id"]), "portfolio"):
        body = _performance(client, f"/api/v1/performance/{target}")
        assert body["money_weighted_return"] is not None
        assert Decimal(body["money_weighted_return"]) == pytest.approx(Decimal("0"), abs=1e-6)


def test_extreme_annualization_does_not_hide_the_portfolio(client):
    today = dt.date.today()
    security, _, _ = _position(client, today - dt.timedelta(days=1))
    _post(
        client,
        "/api/v1/prices",
        {"security_id": security["id"], "date": today.isoformat(), "price_close": "1100"},
    )
    body = _performance(client, "/api/v1/performance/portfolio")
    assert Decimal(body["total_current_value"]) == Decimal("1100")
    assert Decimal(body["total_return"]) == Decimal("10")
    assert Decimal(body["time_weighted_return"]) == Decimal("10")
    assert body["total_return_annualized"] is None
    assert body["time_weighted_return_annualized"] is None


def test_portfolio_and_cost_report_share_the_corrected_twr(client):
    today = dt.date.today()
    security, investment, _ = _position(client, today - dt.timedelta(days=365))
    _post(
        client,
        "/api/v1/income-events",
        {
            "security_id": security["id"],
            "account_id": investment["id"],
            "event_type": "dividend",
            "payment_date": today.isoformat(),
            "total_amount": 12,
            "tax_withheld": 2,
            "currency": "EUR",
        },
    )
    _post(
        client,
        "/api/v1/portfolio-costs",
        {
            "account_id": investment["id"],
            "date": today.isoformat(),
            "cost_type": "custody_fee",
            "amount": 5,
            "currency": "EUR",
        },
    )

    for income_basis, cost_basis, expected in (
        ("net", "exclude", "0.10"),
        ("gross", "exclude", "0.12"),
        ("net", "include", "0.05"),
        ("gross", "include", "0.07"),
    ):
        body = _performance(
            client,
            f"/api/v1/performance/portfolio?income_basis={income_basis}&cost_basis={cost_basis}",
        )
        assert Decimal(body["time_weighted_return"]) == Decimal(expected)
        assert body["metadata"]["income_basis"] == income_basis
        assert body["metadata"]["cost_basis"] == cost_basis

    report = _performance(client, "/api/v1/reports/costs-analysis")
    assert Decimal(report["impact"]["twr_gross"]) == Decimal("0.10")
    assert Decimal(report["impact"]["twr_net"]) == Decimal("0.05")
    assert Decimal(report["impact"]["twr_drag_pct_points"]) == Decimal("5")
