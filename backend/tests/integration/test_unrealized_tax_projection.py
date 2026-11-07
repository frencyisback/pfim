"""Period-end tax on open FIFO positions and its contribution to cost impact."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.models.price import Price

from .conftest import TestingSessionLocal


def _post(client, path, payload):
    response = client.post(f"/api/v1/{path}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def investment(client):
    cash = _post(
        client, "accounts", {"name": "Cash", "type": "checking", "opened_on": "2000-01-01"}
    )
    return _post(
        client,
        "accounts",
        {
            "name": "Investments",
            "type": "investment",
            "reference_account_id": cash["id"],
            "opened_on": "2000-01-01",
        },
    )["id"]


def _security(client, ticker, currency="EUR"):
    return _post(
        client,
        "securities",
        {"name": ticker, "ticker": ticker, "type": "stock", "currency": currency},
    )["id"]


def _trade(
    client, investment, security, date, quantity, price, *, side="buy", currency="EUR", **kwargs
):
    return _post(
        client,
        "trades",
        dict(
            security_id=security,
            account_id=investment,
            date=date,
            type=side,
            quantity=quantity,
            price=price,
            currency=currency,
            **kwargs,
        ),
    )


def _price(client, security, day, price, **kwargs):
    return _post(
        client, "prices", dict(security_id=security, date=day, price_close=price, **kwargs)
    )


def _report(client, **params):
    response = client.get("/api/v1/reports/costs-analysis", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_open_gains_and_losses_offset_only_each_other_using_current_rate(client, investment):
    winner, loser = _security(client, "WIN"), _security(client, "LOSS")
    purchase = _trade(client, investment, winner, "2024-01-01", 10, 10)
    _trade(client, investment, loser, "2024-01-03", 5, 10)
    _price(client, winner, "2024-01-12", 20)
    _price(client, loser, "2024-01-15", 5)
    _post(client, f"trades/{purchase['id']}/costs", {"cost_type": "commission", "amount": 3})
    assert (
        client.put("/api/v1/tax-settings/capital_gains_tax_rate", json={"value": 20}).status_code
        == 200
    )

    report = _report(client, date_to="2024-01-31")
    p = report["unrealized_tax"]
    assert p["opening"]["as_of"] == "2023-12-31"
    assert p["opening"]["open_positions"] == 0
    assert p["closing"]["as_of"] == "2024-01-31"
    assert p["closing"]["open_positions"] == 2
    assert p["closing"]["missing_price_tickers"] == []
    assert Decimal(p["closing"]["net_unrealized_eur"]) == 75
    assert Decimal(p["closing"]["estimated_tax_eur"]) == 15
    assert Decimal(p["economic_gross_result_eur"]) == 75
    assert Decimal(p["projected_period_costs_eur"]) == 18
    assert Decimal(p["projected_cost_impact_pct"]) == 24
    assert Decimal(report["total_costs"]) == 3
    assert Decimal(report["total_estimated"]) == Decimal(report["fiscal"]["estimated_tax_due"]) == 0
    assert Decimal(report["net_result"]) == -3
    assert client.get("/api/v1/tax-events").json() == []


def test_partial_and_full_sales_release_preperiod_estimates_once(client, investment):
    security = _security(client, "FIFO")
    _trade(client, investment, security, "2024-01-01", 2, 40)
    _trade(client, investment, security, "2024-01-02", 2, 60)
    _price(client, security, "2024-01-04", 100)
    sale = _trade(client, investment, security, "2024-02-01", 1, 110, side="sell")
    _post(
        client, f"trades/{sale['id']}/costs", {"cost_type": "capital_gains_tax", "amount": "18.20"}
    )
    _trade(client, investment, security, "2024-02-02", 3, 110, side="sell")

    report = _report(client, date_from="2024-02-01", date_to="2024-02-01")
    p = report["unrealized_tax"]
    assert p["opening"]["as_of"] == "2024-01-31"
    assert Decimal(p["opening"]["net_unrealized_eur"]) == 200
    assert Decimal(p["closing"]["net_unrealized_eur"]) == 170
    assert Decimal(p["tax_change_eur"]) == Decimal("-7.80")
    assert Decimal(report["fiscal"]["estimated_tax_due"]) == 0
    assert Decimal(report["total_costs"]) == Decimal("18.20")
    assert Decimal(p["economic_gross_result_eur"]) == 40
    assert Decimal(p["projected_period_costs_eur"]) == Decimal("10.40")
    assert Decimal(p["projected_cost_impact_pct"]) == 26

    full = _report(client, date_from="2024-02-01", date_to="2024-02-28")
    assert Decimal(full["total_costs"]) == Decimal("62.40")
    assert Decimal(full["fiscal"]["estimated_tax_due"]) == Decimal("44.20")
    p = full["unrealized_tax"]
    assert p["closing"]["open_positions"] == 0
    assert Decimal(p["closing"]["estimated_tax_eur"]) == 0
    assert Decimal(p["tax_change_eur"]) == -52
    assert Decimal(p["projected_cost_impact_pct"]) == 26


def test_unpriced_open_position_suppresses_incomplete_totals_at_affected_endpoint(
    client, investment
):
    priced, unpriced = _security(client, "PRICED"), _security(client, "UNPRICED")
    for security in [priced, unpriced]:
        _trade(client, investment, security, "2024-01-01", 10, 10)
    # Historical databases can contain trades without an observation on the trade date.
    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.security_id == unpriced))
    _price(client, priced, "2024-01-02", 50)
    _price(client, unpriced, "2024-03-01", 30)

    incomplete = _report(client, date_to="2024-02-28")["unrealized_tax"]
    close = incomplete["closing"]
    assert close["open_positions"] == 2
    assert close["missing_price_tickers"] == ["UNPRICED"]
    assert close["estimated_tax_eur"] is close["net_unrealized_eur"] is None
    assert incomplete["tax_change_eur"] is incomplete["projected_period_costs_eur"] is None
    assert (
        incomplete["economic_gross_result_eur"] is incomplete["projected_cost_impact_pct"] is None
    )

    later = _report(client, date_from="2024-03-01", date_to="2024-03-31")["unrealized_tax"]
    assert later["opening"]["missing_price_tickers"] == ["UNPRICED"]
    assert later["closing"]["missing_price_tickers"] == []
    assert Decimal(later["closing"]["estimated_tax_eur"]) == 156
    assert later["projected_cost_impact_pct"] is later["tax_change_eur"] is None


def test_projection_uses_exact_frozen_fx_cutoff_and_configured_zero_rate(client, investment):
    today = dt.date.today()
    tomorrow = (today + dt.timedelta(days=1)).isoformat()
    security = _security(client, "MICROUSD", "USD")
    _trade(
        client,
        investment,
        security,
        "2024-01-01",
        1_000_000,
        "0.000003",
        currency="USD",
        fx_rate="0.5",
    )
    _price(client, security, "2024-02-01", "0.000005", fx_rate="0.5")
    _price(client, security, tomorrow, 200, fx_rate=1)
    report = _report(client, date_to=tomorrow)
    p = report["unrealized_tax"]
    assert p["closing"]["as_of"] == today.isoformat() == report["period_to"]
    assert Decimal(p["closing"]["net_unrealized_eur"]) == 1
    assert Decimal(p["closing"]["estimated_tax_eur"]) == Decimal("0.26")

    assert (
        client.put("/api/v1/tax-settings/capital_gains_tax_rate", json={"value": 0}).status_code
        == 200
    )
    no_tax = _report(client)["unrealized_tax"]
    assert (
        Decimal(no_tax["closing"]["estimated_tax_eur"])
        == Decimal(no_tax["projected_cost_impact_pct"])
        == 0
    )


def test_tax_rounds_to_cents_after_netting_and_loss_does_not_create_tax_credit(client, investment):
    security = _security(client, "CENTS")
    _trade(client, investment, security, "2024-01-01", 1, 1)
    _price(client, security, "2024-01-02", "1.25")
    _price(client, security, "2024-02-01", "0.75")
    p = _report(client, date_from="2024-02-01", date_to="2024-02-01")["unrealized_tax"]
    assert Decimal(p["opening"]["estimated_tax_eur"]) == Decimal("0.07")
    assert Decimal(p["closing"]["net_unrealized_eur"]) == Decimal("-0.25")
    assert Decimal(p["closing"]["estimated_tax_eur"]) == 0
    assert Decimal(p["projected_period_costs_eur"]) == Decimal("-0.07")
    assert Decimal(p["economic_gross_result_eur"]) == Decimal("-0.50")
    assert p["projected_cost_impact_pct"] is None


def test_income_and_released_tax_can_yield_a_negative_cost_share(client, investment):
    security = _security(client, "INCOME")
    _trade(client, investment, security, "2024-01-01", 10, 10)
    _price(client, security, "2024-01-31", 20)
    _price(client, security, "2024-02-15", 18)
    _post(
        client,
        "income-events",
        {
            "security_id": security,
            "account_id": investment,
            "event_type": "dividend",
            "payment_date": "2024-02-02",
            "total_amount": 30,
            "tax_withheld": 2,
            "currency": "EUR",
        },
    )

    report = _report(client, date_from="2024-02-01", date_to="2024-02-29")
    p = report["unrealized_tax"]
    assert Decimal(report["total_costs"]) == 2
    assert Decimal(p["tax_change_eur"]) == Decimal("-5.20")
    assert Decimal(p["economic_gross_result_eur"]) == 10
    assert Decimal(p["projected_period_costs_eur"]) == Decimal("-3.20")
    assert Decimal(p["projected_cost_impact_pct"]) == -32


@pytest.mark.parametrize("params", [{}, {"date_from": "0001-01-01", "date_to": "0001-01-01"}])
def test_empty_and_earliest_period_start_have_a_zero_opening(client, params):
    p = _report(client, **params)["unrealized_tax"]
    assert p["opening"]["as_of"] is None
    for snapshot in (p["opening"], p["closing"]):
        assert snapshot["open_positions"] == 0
        assert snapshot["missing_price_tickers"] == []
        assert (
            Decimal(snapshot["net_unrealized_eur"]) == Decimal(snapshot["estimated_tax_eur"]) == 0
        )
    assert Decimal(p["tax_change_eur"]) == Decimal(p["economic_gross_result_eur"]) == 0
    assert p["projected_cost_impact_pct"] is None
