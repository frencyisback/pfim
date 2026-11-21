"""Integration tests: coupon and dividend analysis (specification §7.5.1)."""

from decimal import Decimal


def _make_accounts(client) -> int:
    """Return the investment account ID (with its reference account)."""
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _make_security(client, ticker: str, type_: str = "stock") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": f"Security {ticker}", "type": type_, "currency": "EUR"},
    ).json()["id"]


def _income(client, sec_id, acc_id, date, gross, tax=0, event_type="dividend"):
    return client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": event_type,
            "payment_date": date,
            "total_amount": gross,
            "currency": "EUR",
            "tax_withheld": tax,
        },
    )


def test_dividends_analysis_accumulates_by_year_with_growth(client):
    acc_id = _make_accounts(client)
    sec_id = _make_security(client, "ENI.MI")
    _income(client, sec_id, acc_id, "2024-05-10", 100, 26)
    _income(client, sec_id, acc_id, "2025-05-10", 150, 39)
    _income(client, sec_id, acc_id, "2025-11-10", 50, 13)

    body = client.get("/api/v1/reports/dividends-analysis").json()

    assert float(body["total_gross"]) == 300.0
    assert float(body["total_net"]) == 222.0
    assert float(body["total_tax"]) == 78.0
    assert round(float(body["tax_incidence_pct"]), 2) == 26.0
    assert body["events_count"] == 3
    assert body["first_event_date"] == "2024-05-10"
    assert body["last_event_date"] == "2025-11-10"

    years = {y["year"]: y for y in body["by_year"]}
    assert float(years[2024]["net"]) == 74.0
    assert float(years[2025]["net"]) == 148.0
    # the cumulative total grows progressively
    assert float(years[2024]["cumulative_net"]) == 74.0
    assert float(years[2025]["cumulative_net"]) == 222.0
    # 74 -> 148 is a doubling
    assert years[2024]["growth_pct"] is None  # no previous year
    assert round(float(years[2025]["growth_pct"]), 1) == 100.0


def test_dividends_analysis_ranks_securities_and_computes_yield_on_cost(client):
    acc_id = _make_accounts(client)
    generous = _make_security(client, "GEN.MI")
    stingy = _make_security(client, "STI.MI")
    # open GEN position to calculate yield on cost
    client.post(
        "/api/v1/trades",
        json={
            "security_id": generous,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-05",
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    _income(client, generous, acc_id, "2026-05-10", 200, 0)
    _income(client, stingy, acc_id, "2026-05-10", 50, 0)

    body = client.get("/api/v1/reports/dividends-analysis").json()

    ranked = body["by_security"]
    assert [s["ticker"] for s in ranked] == ["GEN.MI", "STI.MI"]
    assert round(float(ranked[0]["pct_of_total"]), 1) == 80.0
    # 200 income on 1000 cost basis = 20%
    assert round(float(ranked[0]["yield_on_cost_pct"]), 2) == 20.0
    # no open STI position: yield on cost cannot be calculated
    assert ranked[1]["yield_on_cost_pct"] is None


def test_dividends_analysis_groups_by_security_and_event_type(client):
    acc_id = _make_accounts(client)
    stock = _make_security(client, "ENI.MI", "stock")
    bond = _make_security(client, "BTP.MI", "bond")
    _income(client, stock, acc_id, "2026-05-10", 100, 0, "dividend")
    _income(client, bond, acc_id, "2026-06-10", 300, 0, "coupon")

    body = client.get("/api/v1/reports/dividends-analysis").json()

    by_type = {r["key"]: r for r in body["by_security_type"]}
    assert float(by_type["bond"]["net"]) == 300.0
    assert round(float(by_type["bond"]["pct_of_total"]), 1) == 75.0
    assert float(by_type["stock"]["net"]) == 100.0
    # sort by amount descending
    assert body["by_security_type"][0]["key"] == "bond"

    by_event = {r["key"]: r for r in body["by_event_type"]}
    assert set(by_event) == {"dividend", "coupon"}
    assert float(by_event["coupon"]["net"]) == 300.0


def test_dividends_analysis_exposes_monthly_seasonality(client):
    """The monthly distribution shows when income arrives: it always has 12 entries, including zero-income months."""
    acc_id = _make_accounts(client)
    sec_id = _make_security(client, "ENI.MI")
    _income(client, sec_id, acc_id, "2025-05-10", 100, 0)
    _income(client, sec_id, acc_id, "2026-05-20", 200, 0)
    _income(client, sec_id, acc_id, "2026-11-20", 60, 0)

    body = client.get("/api/v1/reports/dividends-analysis").json()

    months = {m["month"]: m for m in body["by_month"]}
    assert len(months) == 12
    # May aggregates both years
    assert float(months[5]["net"]) == 300.0
    assert months[5]["events_count"] == 2
    assert float(months[11]["net"]) == 60.0
    assert float(months[1]["net"]) == 0.0


def test_dividends_analysis_respects_period_filter(client):
    acc_id = _make_accounts(client)
    sec_id = _make_security(client, "ENI.MI")
    _income(client, sec_id, acc_id, "2025-05-10", 100, 0)
    _income(client, sec_id, acc_id, "2026-05-10", 200, 0)

    body = client.get(
        "/api/v1/reports/dividends-analysis?date_from=2026-01-01&date_to=2026-12-31"
    ).json()
    assert float(body["total_net"]) == 200.0
    assert [y["year"] for y in body["by_year"]] == [2026]


def test_dividends_analysis_is_empty_without_events(client):
    body = client.get("/api/v1/reports/dividends-analysis").json()
    assert body["events_count"] == 0
    assert float(body["total_net"]) == 0.0
    assert body["by_year"] == []
    assert body["by_security"] == []
    assert body["tax_incidence_pct"] is None
    # seasonality keeps 12 empty months so the chart remains valid
    assert len(body["by_month"]) == 12


def test_calendar_month_average_year_gaps_and_returned_capital(client):
    account = _make_accounts(client)
    security = _make_security(client, "CAL")
    for day, amount, kind in (
        ("2022-04-05", 100, "dividend"),
        ("2023-02-10", 30, "return_of_capital"),
        ("2024-06-15", 120, "coupon"),
    ):
        assert _income(client, security, account, day, amount, event_type=kind).status_code == 201

    endpoint = "/api/v1/reports/dividends-analysis"
    year = client.get(endpoint, params={"date_from": "2024-01-01", "date_to": "2024-12-31"}).json()
    assert Decimal(year["average_monthly_net"]) == 10
    params = {"date_from": "2022-01-01", "date_to": "2024-12-31"}
    body = client.get(endpoint, params=params).json()
    assert Decimal(body["total_net"]) == 220
    assert Decimal(body["returned_capital_net"]) == 30
    assert body["events_count"] == 2
    assert [row["year"] for row in body["by_year"]] == [2022, 2023, 2024]
    assert Decimal(body["by_year"][1]["growth_pct"]) == -100
    assert body["by_year"][2]["growth_pct"] is None
    costs = client.get("/api/v1/reports/costs-analysis", params=params).json()
    assert Decimal(costs["realized"]["income_gross"]) == 220
    assert Decimal(costs["realized"]["returned_capital_gross"]) == 30
    assert Decimal(costs["realized"]["gross_result"]) == 220


def test_partial_sale_reconciles_cash_income_and_remaining_position_yield(client):
    account = _make_accounts(client)
    security = _make_security(client, "PART")
    trade = {"security_id": security, "account_id": account, "price": 10, "currency": "EUR"}
    assert (
        client.post(
            "/api/v1/trades", json={**trade, "type": "buy", "date": "2022-01-01", "quantity": 100}
        ).status_code
        == 201
    )
    assert _income(client, security, account, "2022-02-01", 50).status_code == 201
    assert (
        client.post(
            "/api/v1/trades", json={**trade, "type": "sell", "date": "2022-03-01", "quantity": 90}
        ).status_code
        == 201
    )
    body = client.get("/api/v1/reports/dividends-analysis").json()
    assert Decimal(body["total_net"]) == 50
    assert Decimal(body["by_security"][0]["yield_on_cost_pct"]) == 5


def test_principal_repayment_reconciles_with_price_drop(client):
    account = _make_accounts(client)
    security = _make_security(client, "REPAY")
    trade = {
        "security_id": security,
        "account_id": account,
        "type": "buy",
        "date": "2023-01-01",
        "quantity": 1,
        "price": 100,
        "currency": "EUR",
    }
    assert client.post("/api/v1/trades", json=trade).status_code == 201
    assert (
        _income(
            client, security, account, "2023-03-01", 10, event_type="return_of_capital"
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/prices",
            json={"security_id": security, "date": "2023-03-01", "price_close": 90},
        ).status_code
        == 201
    )
    result = client.get(
        "/api/v1/reports/costs-analysis?date_from=2023-03-01&date_to=2023-03-31"
    ).json()
    assert Decimal(result["realized"]["income_gross"]) == 0
    assert Decimal(result["unrealized_tax"]["unrealized_change_eur"]) == -10
    assert Decimal(result["unrealized_tax"]["economic_gross_result_eur"]) == 0


def test_fiscal_summary_splits_principal_and_income_withholding_and_reconciles_costs(client):
    account = _make_accounts(client)
    security = _make_security(client, "TAXSPLIT")
    for kind, day, gross, tax in (
        ("dividend", "2023-03-10", 14, 2),
        ("coupon", "2023-03-15", 12, 1),
        ("return_of_capital", "2023-03-20", 25, 5),
        ("return_of_capital", "2023-04-01", 20, 4),
    ):
        assert _income(client, security, account, day, gross, tax, kind).status_code == 201

    period = {"date_from": "2023-03-01", "date_to": "2023-03-31"}
    result = client.get("/api/v1/reports/costs-analysis", params=period).json()
    fiscal = result["fiscal"]
    assert Decimal(fiscal["dividend_withholding"]) == 3
    assert Decimal(fiscal["principal_withholding"]) == 5
    assert Decimal(fiscal["tax_already_withheld"]) == 0  # Withholding on sales only.
    assert Decimal(result["total_costs"]) == 8
    taxes = next(group for group in result["groups"] if group["group"] == "taxes")
    assert Decimal(taxes["total_eur"]) == 8
    income = client.get("/api/v1/reports/dividends-analysis", params=period).json()
    assert Decimal(income["total_tax"]) == Decimal(fiscal["dividend_withholding"])
    assert Decimal(income["returned_capital_net"]) == 20
