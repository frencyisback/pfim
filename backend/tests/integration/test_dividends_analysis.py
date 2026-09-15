"""Integration tests: coupon and dividend analysis (specification §7.5.1)."""


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
