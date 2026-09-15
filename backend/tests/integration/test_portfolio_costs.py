"""Integration tests: recurring costs and Costs and Tax reports
(specification §11.5, §11.6)."""

import datetime as dt
import io
from decimal import Decimal


def _make_security(client, ticker="ENI.MI") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": f"Security {ticker}", "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _make_accounts(client) -> tuple[int, int]:
    """Return (investment_account_id, reference_account_id)."""
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    invest = client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    return invest["id"], checking["id"]


def _import_price(client, ticker: str, price: float):
    csv_content = "date;ticker;close\n" f"2026-07-10;{ticker};{price}\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    client.post("/api/v1/prices/import", files={"file": ("p.csv", file, "text/csv")})


# --- Recurring costs: entity and linked cash ---------------------------


def test_portfolio_cost_creates_linked_transaction_on_reference_account(client):
    """A recurring cost is outgoing money: as with trades and coupons, cash moves in the REFERENCE account, not the investment account."""
    invest_id, ref_id = _make_accounts(client)
    resp = client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-03-31",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 25,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    assert float(resp.json()["amount_eur"]) == 25.0

    on_reference = client.get(f"/api/v1/transactions?account_id={ref_id}").json()["items"]
    assert len(on_reference) == 1
    assert float(on_reference[0]["amount"]) == -25.0
    assert on_reference[0]["portfolio_cost_id"] == resp.json()["id"]

    # the investment account never holds its own cash
    on_investment = client.get(f"/api/v1/transactions?account_id={invest_id}").json()["items"]
    assert on_investment == []


def test_portfolio_cost_and_linked_cash_use_the_same_normalized_amount(client):
    invest_id, ref_id = _make_accounts(client)
    response = client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-03-31",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": "25.0000005",
            "currency": "EUR",
        },
    )

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["amount"]) == Decimal("25.000000")
    assert Decimal(response.json()["amount_eur"]) == Decimal("25.000000")
    linked = client.get(f"/api/v1/transactions?account_id={ref_id}").json()["items"][0]
    assert Decimal(linked["amount"]) == Decimal("-25.000000")
    assert Decimal(linked["amount_eur"]) == Decimal("-25.000000")


def test_portfolio_cost_requires_investment_account(client):
    _, ref_id = _make_accounts(client)
    resp = client.post(
        "/api/v1/portfolio-costs",
        json={"date": "2026-03-31", "cost_type": "custody_fee", "account_id": ref_id, "amount": 25},
    )
    assert resp.status_code == 400


def test_linked_cost_transaction_cannot_be_deleted_from_cashflow(client):
    invest_id, ref_id = _make_accounts(client)
    cost = client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-03-31",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 25,
        },
    ).json()

    tx = client.get(f"/api/v1/transactions?account_id={ref_id}").json()["items"][0]
    resp = client.delete(f"/api/v1/transactions/{tx['id']}")
    assert resp.status_code == 409

    # deleting the cost also removes its linked transaction
    assert client.delete(f"/api/v1/portfolio-costs/{cost['id']}").status_code == 204
    assert client.get(f"/api/v1/transactions?account_id={ref_id}").json()["items"] == []


# --- Costs report ---------------------------------------------------------


def test_costs_analysis_groups_costs_and_separates_realized_result(client):
    """Costs fall into three groups (tax/operating/recurring); capital gains and losses remain in the result section, outside costs."""
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)

    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{buy['id']}/costs",
        json={"cost_type": "commission", "amount": 5, "currency": "EUR"},
    )
    # profitable sale: 100 x 15 against cost basis 10 -> +500 capital gain
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "sell",
            "date": "2026-02-10",
            "quantity": 100,
            "price": 15,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-03-31",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 20,
        },
    )

    body = client.get("/api/v1/reports/costs-analysis").json()

    assert float(body["realized"]["capital_gains"]) == 500.0
    assert float(body["realized"]["net_realized"]) == 500.0

    groups = {g["group"]: g for g in body["groups"]}
    assert set(groups) == {"taxes", "trading", "recurring"}
    # purchase commission among operating costs
    assert float(groups["trading"]["total_eur"]) == 5.0
    # estimated capital-gains tax at 26%
    assert float(groups["taxes"]["total_eur"]) == 130.0
    assert groups["taxes"]["items"][0]["is_estimated"] is True
    # custody cost among recurring costs
    assert any(i["cost_type"] == "custody_fee" for i in groups["recurring"]["items"])

    # capital gains do NOT appear among costs
    all_types = {i["cost_type"] for g in body["groups"] for i in g["items"]}
    assert "capital_gain" not in all_types

    assert float(body["net_result"]) == float(body["realized"]["gross_result"]) - float(
        body["total_costs"]
    )


def test_real_tax_on_sale_is_subtracted_from_the_estimate(client):
    """Actual withholding on a sale is subtracted from the estimate rather than added, avoiding double counting.

    Tax at 26% on a gain of 500 is 130; with 118 already withheld, the
    residual estimate is 12. Previously the estimate was omitted entirely,
    hiding the difference between broker withholding and the recorded basis."""
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    sell = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "sell",
            "date": "2026-02-10",
            "quantity": 100,
            "price": 15,
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{sell['id']}/costs",
        json={"cost_type": "tax", "amount": 118, "currency": "EUR"},
    )

    body = client.get("/api/v1/reports/costs-analysis").json()
    taxes = next(g for g in body["groups"] if g["group"] == "taxes")
    fiscal = body["fiscal"]

    # 130 total tax on the net, not 248 (118 actual + 130 estimated)
    assert float(fiscal["gross_estimated_tax"]) == 130.0
    assert float(fiscal["tax_already_withheld"]) == 118.0
    assert float(fiscal["estimated_tax_due"]) == 12.0
    assert float(taxes["total_eur"]) == 130.0
    assert float(taxes["estimated_eur"]) == 12.0


def test_withholding_on_coupons_is_counted_as_a_real_cost(client):
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "event_type": "coupon",
            "payment_date": "2026-05-01",
            "total_amount": 100,
            "currency": "EUR",
            "tax_withheld": 26,
        },
    )

    body = client.get("/api/v1/reports/costs-analysis").json()
    taxes = next(g for g in body["groups"] if g["group"] == "taxes")
    withholding = [i for i in taxes["items"] if i["cost_type"] == "withholding_tax"]
    assert len(withholding) == 1
    assert float(withholding[0]["amount_eur"]) == 26.0
    assert withholding[0]["is_estimated"] is False
    # gross coupon income belongs in the result, outside costs
    assert float(body["realized"]["income_gross"]) == 100.0


def test_estimated_stamp_duty_is_skipped_when_a_real_one_exists(client):
    """Estimate stamp duty from the rate only until actual duty is recorded; otherwise the same tax would be counted twice."""
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 12.0)

    before = client.get("/api/v1/reports/costs-analysis").json()
    stamp = before["current_stamp_duty_estimate"]
    assert stamp is not None
    assert stamp["is_estimated"] is True
    # 0.20% on 100 x 12 = 2.40
    assert round(float(stamp["amount_eur"]), 2) == 2.40

    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": dt.date.today().isoformat(),
            "cost_type": "stamp_duty",
            "account_id": invest_id,
            "amount": 3,
        },
    )
    after = client.get("/api/v1/reports/costs-analysis").json()
    assert after["current_stamp_duty_estimate"] is None
    recurring_after = next(g for g in after["groups"] if g["group"] == "recurring")
    stamp_after = [i for i in recurring_after["items"] if i["cost_type"] == "stamp_duty"]
    assert len(stamp_after) == 1
    assert stamp_after[0]["is_estimated"] is False
    assert float(stamp_after[0]["amount_eur"]) == 3.0


def test_costs_reduce_net_twr_compared_to_gross(client):
    """TWR net of costs must be below gross TWR: this measures performance drag."""
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    buy_date = dt.date.today() - dt.timedelta(days=365)
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": buy_date.isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{buy['id']}/costs",
        json={"cost_type": "commission", "amount": 50, "currency": "EUR"},
    )
    _import_price(client, "ENI.MI", 12.0)

    impact = client.get("/api/v1/reports/costs-analysis").json()["impact"]
    assert impact["twr_gross"] is not None
    assert impact["twr_net"] is not None
    assert float(impact["twr_net"]) < float(impact["twr_gross"])
    assert float(impact["twr_drag_pct_points"]) > 0


def test_cost_impact_metrics_are_exposed(client):
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{buy['id']}/costs",
        json={"cost_type": "commission", "amount": 10, "currency": "EUR"},
    )
    _import_price(client, "ENI.MI", 12.0)

    impact = client.get("/api/v1/reports/costs-analysis").json()["impact"]
    # total costs / invested capital: commission 10 on 1000 invested, plus
    # estimated stamp duty -> still a small positive percentage
    assert impact["pct_of_invested"] is not None
    assert 0 < float(impact["pct_of_invested"]) < 10
    assert impact["annual_incidence_pct"] is not None


def test_costs_analysis_respects_the_period_filter(client):
    invest_id, _ = _make_accounts(client)
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2025-06-30",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 15,
        },
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-06-30",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 25,
        },
    )

    body = client.get(
        "/api/v1/reports/costs-analysis?date_from=2026-01-01&date_to=2026-12-31"
    ).json()
    recurring = next(g for g in body["groups"] if g["group"] == "recurring")
    custody = [i for i in recurring["items"] if i["cost_type"] == "custody_fee"]
    assert len(custody) == 1
    assert float(custody[0]["amount_eur"]) == 25.0


def test_annual_incidence_scales_a_short_period_up_to_a_year(client):
    """TER-like cost incidence is comparable with an ETF's TER only on an annual basis: half-year costs must be doubled.

    This multiplication was the only costs_analysis branch with no test
    coverage and contained the project's only hardcoded 365 instead of
    using app.finance.periods.
    """
    year = dt.date.today().year - 1
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": f"{year}-01-05",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/prices",
        json={"security_id": sec_id, "date": f"{year}-01-10", "price_close": 10},
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": f"{year}-03-31",
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 10,
        },
    )

    # Same costs, two windows of different lengths that contain
    # all of them: half a year and a full year.
    semestre = client.get(
        f"/api/v1/reports/costs-analysis?date_from={year}-01-01&date_to={year}-07-01"
    ).json()["impact"]
    scenario_year = client.get(
        f"/api/v1/reports/costs-analysis?date_from={year}-01-01&date_to={year}-12-31"
    ).json()["impact"]

    assert semestre["annual_incidence_pct"] is not None
    # About half a year versus a full year: annualized incidence for the half-year
    # is about double, with equal costs and average value.
    ratio = float(semestre["annual_incidence_pct"]) / float(scenario_year["annual_incidence_pct"])
    assert 1.9 < ratio < 2.1


def test_annual_incidence_without_explicit_start_uses_first_activity_date(client):
    """Without date_from, the report exposes and uses the first actual event."""
    today = dt.date.today()
    start = dt.date(today.year - 1, 1, 5)
    invest_id, _ = _make_accounts(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_id,
            "type": "buy",
            "date": start.isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/prices",
        json={
            "security_id": sec_id,
            "date": (start + dt.timedelta(days=1)).isoformat(),
            "price_close": 10,
        },
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": (start + dt.timedelta(days=30)).isoformat(),
            "cost_type": "custody_fee",
            "account_id": invest_id,
            "amount": 10,
        },
    )

    body = client.get("/api/v1/reports/costs-analysis").json()
    impact = body["impact"]

    period_days = (today - start).days + 1
    assert body["period_from"] == start.isoformat()
    assert body["period_to"] == today.isoformat()
    assert impact["period_days"] == period_days
    expected = 10 / 1000 * 100 * 365 / period_days
    assert abs(float(impact["annual_incidence_pct"]) - expected) < 1e-6
