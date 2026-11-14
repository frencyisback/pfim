"""Period-end tax on open FIFO positions and its contribution to cost impact."""

import csv
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
    export = client.get("/api/v1/reports/costs-analysis", params={"format": "csv"})
    assert export.status_code == 200
    rows = list(csv.DictReader(export.text.splitlines()))
    assert [(r["cost_type"], r["group"], Decimal(r["amount_eur"])) for r in rows] == [
        ("commission", "trading", Decimal("3"))
    ]


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
    assert Decimal(p["unrealized_change_eur"]) == -30
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


@pytest.mark.parametrize("withheld", [0, 13, 26])
def test_sale_at_unchanged_price_reconciles_open_tax_with_paid_and_unpaid_tax(
    client, investment, withheld
):
    security = _security(client, "SPLIT")
    _trade(client, investment, security, "2024-01-01", 10, 100)
    _price(client, security, "2024-01-31", 120)
    sale = _trade(client, investment, security, "2024-02-10", 5, 120, side="sell")
    if withheld:
        _post(
            client,
            f"trades/{sale['id']}/costs",
            {"cost_type": "capital_gains_tax", "amount": withheld},
        )

    report = _report(client, date_from="2024-02-01", date_to="2024-02-29")
    assert Decimal(report["fiscal"]["estimated_tax_due"]) == 26 - withheld
    assert Decimal(report["net_result"]) == 74
    projection, impact = report["unrealized_tax"], report["impact"]
    assert Decimal(projection["unrealized_change_eur"]) == -100
    assert Decimal(projection["tax_change_eur"]) == -26
    assert Decimal(projection["economic_gross_result_eur"]) == 0
    assert Decimal(projection["projected_period_costs_eur"]) == 0
    assert projection["projected_cost_impact_pct"] is None
    assert Decimal(impact["projected_pct_of_invested"]) == 0
    assert Decimal(impact["projected_annual_incidence_pct"]) == 0
    assert Decimal(impact["estimated_twr_net"]) == 0
    assert Decimal(impact["estimated_twr_drag_pct_points"]) == 0


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

    _post(
        client,
        "portfolio-costs",
        {
            "date": "2024-01-20",
            "cost_type": "custody_fee",
            "account_id": investment,
            "amount": 4,
            "currency": "EUR",
        },
    )
    report = _report(client, date_to="2024-02-28")
    incomplete = report["unrealized_tax"]
    close = incomplete["closing"]
    assert close["open_positions"] == 2
    assert close["missing_price_tickers"] == ["UNPRICED"]
    assert close["estimated_tax_eur"] is close["net_unrealized_eur"] is None
    assert incomplete["tax_change_eur"] is incomplete["projected_period_costs_eur"] is None
    assert (
        incomplete["economic_gross_result_eur"] is incomplete["projected_cost_impact_pct"] is None
    )
    assert incomplete["unrealized_change_eur"] is None
    assert Decimal(report["realized"]["gross_result"]) == 0
    assert Decimal(report["total_costs"]) == 4
    assert Decimal(report["net_result"]) == -4
    impact = report["impact"]
    assert impact["average_quoted_portfolio_value"] is None
    assert impact["projected_pct_of_invested"] is impact["projected_annual_incidence_pct"] is None
    assert impact["estimated_twr_net"] is impact["estimated_twr_drag_pct_points"] is None
    assert impact["twr_gross"] is not None

    later = _report(client, date_from="2024-03-01", date_to="2024-03-31")["unrealized_tax"]
    assert later["opening"]["missing_price_tickers"] == ["UNPRICED"]
    assert later["closing"]["missing_price_tickers"] == []
    assert Decimal(later["closing"]["estimated_tax_eur"]) == 156
    assert later["projected_cost_impact_pct"] is later["tax_change_eur"] is None
    assert later["unrealized_change_eur"] is None


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
    assert Decimal(report["impact"]["projected_pct_of_invested"]) == Decimal("-3.20")
    market_average = (Decimal(200) * 14 + Decimal(180) * 15) / 29
    adjusted_annual = Decimal("-3.20") / market_average * 100 * 365 / 29
    assert Decimal(report["impact"]["average_quoted_portfolio_value"]) == market_average
    assert Decimal(report["impact"]["projected_annual_incidence_pct"]) == adjusted_annual


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


def test_unified_impact_uses_the_change_in_unrealized_gains_for_each_period(client, investment):
    security = _security(client, "PERIOD")
    _trade(client, investment, security, "2024-01-01", 10, 100)
    _price(client, security, "2024-01-31", 120)

    report = _report(client, date_to="2024-01-31")
    projection, impact = report["unrealized_tax"], report["impact"]
    assert Decimal(projection["unrealized_change_eur"]) == 200
    assert Decimal(projection["economic_gross_result_eur"]) == 200
    assert Decimal(report["net_result"]) == 0
    assert Decimal(projection["projected_cost_impact_pct"]) == 26
    assert Decimal(impact["projected_pct_of_invested"]) == Decimal("5.2")
    average = (30 * Decimal(1000) + Decimal(1200)) / 31
    assert Decimal(impact["projected_annual_incidence_pct"]) == 52 / average * 100 * 365 / 31
    assert Decimal(impact["twr_gross"]) == Decimal("0.20")
    assert Decimal(impact["twr_net"]) == Decimal("0.20")
    assert Decimal(impact["estimated_twr_net"]) == Decimal("0.148")
    assert Decimal(impact["estimated_twr_drag_pct_points"]) == Decimal("5.2")

    next_month = _report(client, date_from="2024-02-01", date_to="2024-02-29")
    projection, impact = next_month["unrealized_tax"], next_month["impact"]
    assert Decimal(projection["closing"]["estimated_tax_eur"]) == 52
    assert (
        Decimal(projection["unrealized_change_eur"]) == Decimal(projection["tax_change_eur"]) == 0
    )
    assert Decimal(projection["economic_gross_result_eur"]) == 0
    assert projection["projected_cost_impact_pct"] is None
    assert Decimal(impact["projected_annual_incidence_pct"]) == 0
    assert Decimal(impact["projected_pct_of_invested"]) == 0
    assert (
        Decimal(impact["estimated_twr_net"])
        == Decimal(impact["estimated_twr_drag_pct_points"])
        == 0
    )


def test_missing_intermediate_market_value_only_suppresses_dependent_measures(client, investment):
    security = _security(client, "LATE")
    _trade(client, investment, security, "2024-02-02", 10, 100)
    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.security_id == security))
    _price(client, security, "2024-02-15", 120)
    report = _report(client, date_from="2024-02-01", date_to="2024-02-29")
    projection, impact = report["unrealized_tax"], report["impact"]
    assert Decimal(projection["projected_period_costs_eur"]) == 52
    assert Decimal(projection["economic_gross_result_eur"]) == 200
    assert impact["average_quoted_portfolio_value"] is None
    assert impact["projected_annual_incidence_pct"] is None
    assert impact["estimated_twr_net"] is None
    assert Decimal(impact["average_portfolio_value"]) > 0
    invested_average = Decimal(1000) * 28 / 29
    assert Decimal(impact["projected_pct_of_invested"]) == 52 / invested_average * 100
