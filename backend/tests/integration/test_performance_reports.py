"""Integration tests: performance and reports (specification §6.7, §6.8, §9)."""

import datetime as dt
import io


def _make_security(client, ticker="ENI.MI", type_="stock") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": f"Security {ticker}", "type": type_, "currency": "EUR"},
    ).json()["id"]


def _make_checking_account(client, opening_balance=0) -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Checking Account",
            "type": "checking",
            "opening_balance": opening_balance,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _make_investment_account(client, reference_account_id=None) -> int:
    if reference_account_id is None:
        reference_account_id = _make_checking_account(client)
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": reference_account_id,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _import_price(client, ticker: str, price: float):
    csv_content = f"date;ticker;close\n2026-07-10;{ticker};{price}\n"
    file = io.BytesIO(csv_content.encode("utf-8"))
    client.post("/api/v1/prices/import", files={"file": ("p.csv", file, "text/csv")})


def test_security_performance_basic(client):
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2025-07-11",
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 17.0)

    resp = client.get(f"/api/v1/performance/{sec_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert round(float(body["simple_return"]), 4) == round(3 / 14, 4)
    assert body["money_weighted_return"] is not None


def test_performance_no_trades_returns_400(client):
    sec_id = _make_security(client)
    resp = client.get(f"/api/v1/performance/{sec_id}")
    assert resp.status_code == 400


def test_performance_nonexistent_security_returns_404(client):
    resp = client.get("/api/v1/performance/9999")
    assert resp.status_code == 404


def test_portfolio_performance_aggregate(client):
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2025-07-11",
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 17.0)

    resp = client.get("/api/v1/performance/portfolio")
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["total_invested"]) == 1400.0
    assert float(body["total_current_value"]) == 1700.0
    assert len(body["by_security"]) == 1


def test_portfolio_twr_and_mwr_are_exposed(client):
    """One purchase with no later flows: TWR equals price appreciation (14 -> 17 = +21.43%) because there are no intermediate flows to remove. MWR is positive but differs because it accounts for elapsed time (§9.3, §9.4)."""
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2025-07-11",
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 17.0)

    body = client.get("/api/v1/performance/portfolio").json()
    assert round(float(body["time_weighted_return"]), 4) == round(3 / 14, 4)
    assert body["money_weighted_return"] is not None
    assert float(body["money_weighted_return"]) > 0


def test_portfolio_twr_neutralises_timing_of_contributions(client):
    """TWR must ignore HOW MUCH capital arrived and when: two purchases at different prices must not change returns relative to price movements alone (unlike MWR, §9.3)."""
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    for date, qty, price in [("2025-01-10", 100, 10), ("2025-06-10", 900, 12)]:
        client.post(
            "/api/v1/trades",
            json={
                "security_id": sec_id,
                "account_id": acc_id,
                "type": "buy",
                "date": date,
                "quantity": qty,
                "price": price,
                "currency": "EUR",
            },
        )
    # price on second purchase date + current price
    for date, price in [("2025-06-10", 12.0), ("2026-07-10", 15.0)]:
        csv_content = f"date;ticker;close\n{date};ENI.MI;{price}\n"
        client.post(
            "/api/v1/prices/import",
            files={"file": ("p.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        )

    body = client.get("/api/v1/performance/portfolio").json()
    # 10 -> 12 (+20%) then 12 -> 15 (+25%): 1.20 * 1.25 - 1 = 50%
    assert round(float(body["time_weighted_return"]), 4) == 0.5


def test_portfolio_returns_are_annualized_over_the_holding_period(client):
    """A +21.43% gain over about one year should have an annualized return close to its cumulative return; MWR is already annualized by definition (§9.6)."""
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    buy_date = dt.date.today() - dt.timedelta(days=365)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": buy_date.isoformat(),
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 17.0)

    body = client.get("/api/v1/performance/portfolio").json()
    assert body["investment_period_days"] == 365
    cumulative = float(body["time_weighted_return"])
    annualized = float(body["time_weighted_return_annualized"])
    assert round(annualized, 4) == round(cumulative, 4)
    assert body["total_return_annualized"] is not None


def test_portfolio_annualized_return_scales_a_multi_year_period(client):
    """The same gain spread over 4 years must have an annualized return well below its cumulative return."""
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    buy_date = dt.date.today() - dt.timedelta(days=365 * 4)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": buy_date.isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 20.0)

    body = client.get("/api/v1/performance/portfolio").json()
    # +100% cumulative over 4 years -> approximately +18.9% annually
    assert round(float(body["time_weighted_return"]), 4) == 1.0
    assert round(float(body["time_weighted_return_annualized"]), 4) == 0.1892


def test_twr_ignores_income_events_dated_before_the_first_trade(client):
    """Income dated before the first purchase must not erase TWR by opening the period on an empty portfolio with zero starting capital. A date typo must not lose the metric for the entire history."""
    sec_id = _make_security(client)
    acc_id = _make_investment_account(client)
    buy_date = dt.date.today() - dt.timedelta(days=365)
    # coupon dated BEFORE the first purchase
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": (buy_date - dt.timedelta(days=20)).isoformat(),
            "total_amount": 50,
            "currency": "EUR",
            "tax_withheld": 0,
        },
    )
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": buy_date.isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 12.0)

    body = client.get("/api/v1/performance/portfolio").json()
    assert body["time_weighted_return"] is not None
    # the period starts at purchase, not at the coupon 20 days earlier
    assert body["investment_period_days"] == 365


def test_portfolio_twr_and_mwr_are_none_without_trades(client):
    _make_security(client)
    body = client.get("/api/v1/performance/portfolio").json()
    assert body["time_weighted_return"] is None
    assert body["money_weighted_return"] is None


def test_net_worth_report_combines_accounts_and_portfolio(client):
    cash_acc = _make_checking_account(client, opening_balance=5000)
    sec_id = _make_security(client)
    invest_acc = _make_investment_account(client, reference_account_id=cash_acc)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": invest_acc,
            "type": "buy",
            "date": "2025-07-11",
            "quantity": 100,
            "price": 14,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 17.0)

    resp = client.get("/api/v1/reports/net-worth")
    body = resp.json()
    # The purchase (100 x 14) creates a linked transaction reducing the
    # investment account balance by 1400. Without this link, cash spent
    # on securities would remain invisible and net worth would count
    # the same value twice: once as an account balance and once as
    # portfolio value.
    assert float(body["total_accounts_balance"]) == 3600.0
    assert float(body["total_portfolio_value"]) == 1700.0
    assert float(body["net_worth"]) == 5300.0


def test_income_statement_report(client):
    acc_id = _make_checking_account(client)
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "Income-statement income", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "Income-statement expense", "type": "expense"}
    ).json()["id"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": income_category_id,
            "date": "2026-06-01",
            "amount": 2000,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": expense_category_id,
            "date": "2026-06-15",
            "amount": -500,
            "currency": "EUR",
        },
    )
    resp = client.get("/api/v1/reports/income-statement")
    body = resp.json()
    assert float(body["total_income"]) == 2000.0
    assert float(body["total_expense"]) == -500.0
    period = next(p for p in body["periods"] if p["period_label"] == "2026-06")
    assert float(period["savings_rate_pct"]) == 75.0


def test_spending_analysis_report(client):
    acc_id = _make_checking_account(client)
    cat = client.post("/api/v1/categories", json={"name": "Test expense", "type": "expense"}).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": cat["id"],
            "date": "2026-06-01",
            "amount": -100,
            "currency": "EUR",
            "description": "Supermarket",
        },
    )
    resp = client.get("/api/v1/reports/spending-analysis")
    body = resp.json()
    assert float(body["total_amount"]) == -100.0
    assert len(body["by_category"]) == 1
    assert body["by_category"][0]["category_name"] == cat["name"]


def test_all_three_analyses_share_the_same_shape(client):
    """Expenses, income, and transfers must expose identical fields (§7.5) so the three report tabs can be compared."""
    expected_keys = {
        "period_from",
        "period_to",
        "total_amount",
        "by_top_level_category",
        "by_category",
        "by_category_detail",
        "by_month",
        "top_transactions",
    }
    for endpoint in ("spending-analysis", "income-analysis", "transfer-analysis"):
        body = client.get(f"/api/v1/reports/{endpoint}").json()
        assert set(body.keys()) == expected_keys, endpoint


def test_category_analysis_groups_by_month_and_caps_top_10(client):
    acc_id = _make_checking_account(client)
    cat = client.post("/api/v1/categories", json={"name": "Expense", "type": "expense"}).json()
    # 12 distinct categories -> by_category stops at the 10 most relevant
    for i in range(12):
        c = client.post("/api/v1/categories", json={"name": f"Cat {i}", "type": "expense"}).json()
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc_id,
                "category_id": c["id"],
                "date": "2026-06-01",
                "amount": -(i + 1),
                "currency": "EUR",
            },
        )
    # two distinct months in the base category
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": cat["id"],
            "date": "2026-07-05",
            "amount": -50,
            "currency": "EUR",
        },
    )

    body = client.get("/api/v1/reports/spending-analysis").json()
    assert len(body["by_category"]) == 10
    assert len(body["by_category_detail"]) == 13
    assert sum(float(row["total_amount"]) for row in body["by_category_detail"]) == -128.0
    # descending absolute value: the largest entry is -50
    assert float(body["by_category"][0]["total_amount"]) == -50.0
    assert len(body["top_transactions"]) == 10

    months = {m["period_label"]: float(m["total_amount"]) for m in body["by_month"]}
    assert months["2026-06"] == -sum(range(1, 13))
    assert months["2026-07"] == -50.0


def test_spending_analysis_exposes_complete_top_level_breakdown(client):
    account_id = _make_checking_account(client)
    home = client.post("/api/v1/categories", json={"name": "Home", "type": "expense"}).json()
    rent = client.post(
        "/api/v1/categories",
        json={"name": "Rent", "type": "expense", "parent_id": home["id"]},
    ).json()
    utilities = client.post(
        "/api/v1/categories",
        json={"name": "Utilities", "type": "expense", "parent_id": home["id"]},
    ).json()
    leisure = client.post("/api/v1/categories", json={"name": "Leisure", "type": "expense"}).json()

    for category_id, amount in ((rent["id"], -700), (utilities["id"], -150), (leisure["id"], -50)):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": "2026-06-15",
                "amount": amount,
                "currency": "EUR",
            },
        )
        assert response.status_code == 201

    body = client.get("/api/v1/reports/spending-analysis").json()
    roots = {row["category_name"]: row for row in body["by_top_level_category"]}

    assert set(roots) == {"Home", "Leisure"}
    assert float(roots["Home"]["total_amount"]) == -850.0
    assert float(roots["Leisure"]["total_amount"]) == -50.0
    assert round(sum(float(row["pct_of_total"]) for row in roots.values()), 8) == 100.0


def test_category_analysis_respects_date_range(client):
    acc_id = _make_checking_account(client)
    cat = client.post("/api/v1/categories", json={"name": "Expense", "type": "expense"}).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": cat["id"],
            "date": "2026-05-01",
            "amount": -100,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": cat["id"],
            "date": "2026-06-01",
            "amount": -30,
            "currency": "EUR",
        },
    )

    body = client.get(
        "/api/v1/reports/spending-analysis",
        params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
    ).json()
    assert float(body["total_amount"]) == -30.0
    assert len(body["by_month"]) == 1


def test_income_analysis_report(client):
    acc_id = _make_checking_account(client)
    cat = client.post("/api/v1/categories", json={"name": "Test salary", "type": "income"}).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_id,
            "category_id": cat["id"],
            "date": "2026-06-01",
            "amount": 1500,
            "currency": "EUR",
        },
    )
    resp = client.get("/api/v1/reports/income-analysis")
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["total_amount"]) == 1500.0
    assert body["by_category"][0]["category_name"] == cat["name"]


def test_transfer_analysis_report(client):
    acc_a = _make_checking_account(client)
    acc_b = client.post(
        "/api/v1/accounts",
        json={"name": "Account B", "type": "savings", "opened_on": "2000-01-01"},
    ).json()["id"]
    client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": acc_a,
            "to_account_id": acc_b,
            "date": "2026-06-01",
            "amount": 300,
            "currency": "EUR",
        },
    )
    resp = client.get("/api/v1/reports/transfer-analysis")
    assert resp.status_code == 200
    body = resp.json()
    # The transfer creates two rows (positive and negative) that cancel:
    # the report counts only the outgoing side, so the total is the VOLUME
    # transferred rather than an uninformative constant zero.
    assert float(body["total_amount"]) == 300.0
    assert len(body["by_category"]) == 1
    assert body["by_category"][0]["category_name"] == "Account Transfer"


def test_securities_analysis_groups_by_type_and_ranks_positions(client):
    """Security analysis captures the CURRENT portfolio: allocation by type and rankings by value/gain/loss (§7.5)."""
    acc_id = _make_investment_account(client)
    # profitable equity ETF, losing bond, small commodities position
    setup = [
        ("VWCE.DE", "etf_equity", 10, 100, 150.0),  # +50%
        ("BTP.MI", "bond", 20, 100, 80.0),  # -20%
        ("GOLD.MI", "commodity", 1, 50, 55.0),  # +10%
    ]
    for ticker, type_, qty, price, current in setup:
        sec_id = _make_security(client, ticker=ticker, type_=type_)
        client.post(
            "/api/v1/trades",
            json={
                "security_id": sec_id,
                "account_id": acc_id,
                "type": "buy",
                "date": "2026-01-10",
                "quantity": qty,
                "price": price,
                "currency": "EUR",
            },
        )
        _import_price(client, ticker, current)

    body = client.get("/api/v1/reports/securities-analysis").json()

    assert body["positions_count"] == 3
    # 10*150 + 20*80 + 1*55 = 1500 + 1600 + 55
    assert float(body["total_value"]) == 3155.0

    by_type = {r["type"]: r for r in body["by_type"]}
    assert set(by_type) == {"etf_equity", "bond", "commodity"}
    assert float(by_type["bond"]["total_value"]) == 1600.0
    assert by_type["bond"]["positions_count"] == 1
    # descending value: the bond is the first entry
    assert body["by_type"][0]["type"] == "bond"
    assert round(sum(float(r["pct_of_total"]) for r in body["by_type"]), 2) == 100.0

    assert [i["ticker"] for i in body["top_by_value"]] == ["BTP.MI", "VWCE.DE", "GOLD.MI"]
    # profitable positions only, best first
    assert [i["ticker"] for i in body["top_gainers"]] == ["VWCE.DE", "GOLD.MI"]
    # losing positions only, worst first
    assert [i["ticker"] for i in body["top_losers"]] == ["BTP.MI"]


def test_securities_analysis_groups_scalar_classifications(client):
    account_id = _make_investment_account(client)
    securities = [
        ("SOFT.MI", "Technology", "Software", "Italy", 100),
        ("BANK.MI", "Finance", "Banks", "Italy", 200),
        ("UNKNOWN.MI", None, None, None, 50),
    ]
    for ticker, sector, industry, country, current_price in securities:
        created = client.post(
            "/api/v1/securities",
            json={
                "ticker": ticker,
                "name": ticker,
                "type": "stock",
                "currency": "EUR",
                "sector": sector,
                "industry": industry,
                "country": country,
            },
        )
        assert created.status_code == 201
        security_id = created.json()["id"]
        assert (
            client.post(
                "/api/v1/trades",
                json={
                    "security_id": security_id,
                    "account_id": account_id,
                    "type": "buy",
                    "date": "2026-01-10",
                    "quantity": 1,
                    "price": 10,
                    "currency": "EUR",
                },
            ).status_code
            == 201
        )
        _import_price(client, ticker, current_price)

    body = client.get("/api/v1/reports/securities-analysis").json()
    by_country = {row["key"]: row for row in body["by_country"]}

    assert float(by_country["Italy"]["total_value"]) == 300.0
    assert by_country["Italy"]["positions_count"] == 2
    assert float(by_country["Unspecified"]["total_value"]) == 50.0
    assert {row["key"] for row in body["by_sector"]} == {
        "Technology",
        "Finance",
        "Unspecified",
    }
    assert {row["key"] for row in body["by_industry"]} == {
        "Software",
        "Banks",
        "Unspecified",
    }
    software = next(item for item in body["top_by_value"] if item["ticker"] == "SOFT.MI")
    assert (software["sector"], software["industry"], software["country"]) == (
        "Technology",
        "Software",
        "Italy",
    )


def test_securities_analysis_ignores_fully_sold_positions(client):
    """A security already fully sold no longer belongs to the current portfolio and must not appear in the analysis."""
    acc_id = _make_investment_account(client)
    sec_id = _make_security(client)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "buy",
            "date": "2026-01-10",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "type": "sell",
            "date": "2026-02-10",
            "quantity": 10,
            "price": 12,
            "currency": "EUR",
        },
    )
    _import_price(client, "ENI.MI", 12.0)

    body = client.get("/api/v1/reports/securities-analysis").json()
    assert body["positions_count"] == 0
    assert float(body["total_value"]) == 0.0
    assert body["by_type"] == []


def test_new_security_types_are_accepted(client):
    for type_ in ("etf_equity", "etf_bond", "commodity", "fund"):
        resp = client.post(
            "/api/v1/securities",
            json={"ticker": f"T-{type_}", "name": type_, "type": type_, "currency": "EUR"},
        )
        assert resp.status_code == 201, type_
        assert resp.json()["type"] == type_


def test_unknown_security_type_is_rejected(client):
    resp = client.post(
        "/api/v1/securities",
        json={"ticker": "XXX", "name": "X", "type": "cryptopunk", "currency": "EUR"},
    )
    assert resp.status_code == 422


def test_net_worth_history_aggregates_all_accounts(client):
    acc_a = client.post(
        "/api/v1/accounts",
        json={
            "name": "A",
            "type": "checking",
            "opening_balance": 1000,
            "opened_on": "2026-06-01",
        },
    ).json()["id"]
    acc_b = client.post(
        "/api/v1/accounts",
        json={
            "name": "B",
            "type": "savings",
            "opening_balance": 500,
            "opened_on": "2026-06-01",
        },
    ).json()["id"]
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "Net-worth history income", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "Net-worth history expense", "type": "expense"}
    ).json()["id"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_a,
            "category_id": income_category_id,
            "date": "2026-06-01",
            "amount": 200,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": acc_b,
            "category_id": expense_category_id,
            "date": "2026-06-02",
            "amount": -50,
            "currency": "EUR",
        },
    )

    resp = client.get("/api/v1/reports/net-worth/history")
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 2
    assert float(points[0]["total_balance"]) == 1700.0  # 1000+200+500 on June 1
    assert float(points[1]["total_balance"]) == 1650.0  # -50 on June 2
