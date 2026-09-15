"""Temporal consistency, rounding, and SQL cost of the Costs report."""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import event

from .conftest import engine


def _portfolio(client, *, ticker: str = "PERIOD") -> tuple[int, int]:
    cash = client.post(
        "/api/v1/accounts",
        json={"name": f"Cash {ticker}", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": f"Investment account {ticker}",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    security = client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]
    return investment, security


def _buy(client, investment: int, security: int, *, date: dt.date, price: str = "10"):
    response = client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": investment,
            "type": "buy",
            "date": date.isoformat(),
            "quantity": "100",
            "price": price,
            "currency": "EUR",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_historical_cost_period_uses_only_its_daily_average_bases(client):
    year = dt.date.today().year - 1
    period_start = dt.date(year, 1, 1)
    price_change = dt.date(year, 1, 15)
    period_end = dt.date(year, 1, 31)
    investment, security = _portfolio(client)
    _buy(client, investment, security, date=period_start)
    client.post(
        "/api/v1/prices",
        json={
            "security_id": security,
            "date": price_change.isoformat(),
            "price_close": "20",
        },
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": period_end.isoformat(),
            "cost_type": "custody_fee",
            "account_id": investment,
            "amount": "10",
            "currency": "EUR",
        },
    )

    response = client.get(
        "/api/v1/reports/costs-analysis",
        params={"date_from": period_start.isoformat(), "date_to": period_end.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    impact = body["impact"]

    assert body["period_from"] == period_start.isoformat()
    assert body["period_to"] == period_end.isoformat()
    assert body["current_stamp_duty_estimate"] is None
    assert impact["period_days"] == 31
    assert Decimal(impact["average_invested_capital"]) == Decimal("1000")
    expected_average_value = (Decimal("1000") * 14 + Decimal("2000") * 17) / 31
    assert abs(Decimal(impact["average_portfolio_value"]) - expected_average_value) < Decimal(
        "0.000001"
    )
    expected_incidence = Decimal("10") / expected_average_value * 100 * 365 / 31
    assert abs(Decimal(impact["annual_incidence_pct"]) - expected_incidence) < Decimal("0.000001")


def test_current_stamp_estimate_is_disclosed_but_not_counted_as_period_cost(client):
    today = dt.date.today()
    investment, security = _portfolio(client)
    _buy(client, investment, security, date=today.replace(month=1, day=1))

    body = client.get(
        "/api/v1/reports/costs-analysis",
        params={"date_from": today.replace(month=1, day=1).isoformat()},
    ).json()

    estimate = body["current_stamp_duty_estimate"]
    assert estimate is not None
    assert estimate["is_estimated"] is True
    assert Decimal(estimate["amount_eur"]) > 0
    assert Decimal(body["total_costs"]) == 0
    assert Decimal(body["total_estimated"]) == 0
    assert all(
        item["cost_type"] != "stamp_duty" for group in body["groups"] for item in group["items"]
    )


def test_capital_gain_tax_rounding_does_not_create_a_zero_cent_ghost_due(client):
    investment, security = _portfolio(client)
    buy = _buy(
        client,
        investment,
        security,
        date=dt.date(dt.date.today().year, 1, 1),
        price="100",
    )
    assert buy
    sale = client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": investment,
            "type": "sell",
            "date": dt.date(dt.date.today().year, 2, 1).isoformat(),
            "quantity": "1",
            "price": "918.81",
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{sale['id']}/costs",
        json={"cost_type": "tax", "amount": "212.89", "currency": "EUR"},
    )

    body = client.get("/api/v1/reports/costs-analysis").json()
    assert Decimal(body["fiscal"]["gross_estimated_tax"]) == Decimal("212.89")
    assert Decimal(body["fiscal"]["tax_already_withheld"]) == Decimal("212.89")
    assert Decimal(body["fiscal"]["estimated_tax_due"]) == Decimal("0.00")
    assert not any(
        item["is_estimated"] and item["cost_type"] == "capital_gains_tax"
        for group in body["groups"]
        for item in group["items"]
    )


@pytest.mark.parametrize(
    "report",
    [
        "income-statement",
        "spending-analysis",
        "income-analysis",
        "transfer-analysis",
        "dividends-analysis",
        "costs-analysis",
    ],
)
def test_periodic_reports_reject_inverted_date_ranges(client, report):
    response = client.get(
        f"/api/v1/reports/{report}",
        params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/transactions",
        "/api/v1/transactions/summary",
        "/api/v1/income-events",
        "/api/v1/income-events/summary",
        "/api/v1/portfolio-costs",
        "/api/v1/tax-events",
    ],
)
def test_filtered_lists_reject_inverted_date_ranges(client, path):
    response = client.get(
        path,
        params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def _count_queries(client) -> int:
    counter = {"value": 0}

    def count(*args, **kwargs):
        counter["value"] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get("/api/v1/reports/costs-analysis").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return counter["value"]


def test_costs_report_query_count_does_not_scale_with_number_of_securities(client):
    for index in range(2):
        investment, security = _portfolio(client, ticker=f"FEW{index}")
        _buy(client, investment, security, date=dt.date(dt.date.today().year, 1, 1))
    few = _count_queries(client)

    for index in range(8):
        investment, security = _portfolio(client, ticker=f"MANY{index}")
        _buy(client, investment, security, date=dt.date(dt.date.today().year, 1, 1))
    many = _count_queries(client)

    assert many == few, f"{few} queries with 2 securities, {many} with 10"
    assert many <= 20
