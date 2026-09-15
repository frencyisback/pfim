"""Integration tests: risk and liquidity indicators (specification §7.5).

Concentration, currency exposure, spending runway, and actual
net-worth history (accounts + securities).
"""

import io
from decimal import Decimal

from app.finance.statistics import winsorized_mean


def _make_checking(client, name="Checking Account", opening=0) -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "checking",
            "opening_balance": opening,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _make_investment(client, reference_id) -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": reference_id,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _make_security(client, ticker, currency="EUR", type_="stock") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": f"Security {ticker}", "type": type_, "currency": currency},
    ).json()["id"]


def _import_price(client, ticker, price, date="2026-07-10", fx_rate=""):
    """Set fx_rate only for non-euro securities: it freezes the converted price value (docs/multi-currency.md)."""
    csv_content = "date;ticker;close;fx_rate\n" f"{date};{ticker};{price};{fx_rate}\n"
    client.post(
        "/api/v1/prices/import",
        files={"file": ("p.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )


def _buy(client, sec_id, acc_id, qty, price, date="2026-01-10", currency="EUR", fx_rate=None):
    payload = {
        "security_id": sec_id,
        "account_id": acc_id,
        "type": "buy",
        "date": date,
        "quantity": qty,
        "price": price,
        "currency": currency,
    }
    if fx_rate is not None:
        payload["fx_rate"] = fx_rate
    return client.post("/api/v1/trades", json=payload)


# --- Concentration --------------------------------------------------------


def test_concentration_measures_dependence_on_few_holdings(client):
    """With one security weighted at 80%, the portfolio behaves as though it contains far fewer securities than its count."""
    ref = _make_checking(client)
    acc = _make_investment(client, ref)
    for ticker, qty, price in [("BIG.MI", 80, 10), ("MID.MI", 15, 10), ("SML.MI", 5, 10)]:
        sec = _make_security(client, ticker)
        _buy(client, sec, acc, qty, price)
        _import_price(client, ticker, price)

    body = client.get("/api/v1/reports/securities-analysis").json()
    c = body["concentration"]

    assert c["top_ticker"] == "BIG.MI"
    assert round(float(c["top_weight_pct"]), 1) == 80.0
    assert round(float(c["top3_weight_pct"]), 1) == 100.0
    # fewer than 3 available securities: top5 cannot exceed 100%
    assert round(float(c["top5_weight_pct"]), 1) == 100.0
    # 1 / (0.8^2 + 0.15^2 + 0.05^2) = 1 / 0.665 ~ 1.5
    assert round(float(c["effective_holdings"]), 2) == 1.50


def test_equally_weighted_portfolio_has_effective_holdings_equal_to_count(client):
    """Four equally weighted securities must equal exactly 4 effective securities, validating the index calibration."""
    ref = _make_checking(client)
    acc = _make_investment(client, ref)
    for ticker in ("A.MI", "B.MI", "C.MI", "D.MI"):
        sec = _make_security(client, ticker)
        _buy(client, sec, acc, 10, 10)
        _import_price(client, ticker, 10)

    body = client.get("/api/v1/reports/securities-analysis").json()
    assert round(float(body["concentration"]["effective_holdings"]), 2) == 4.00
    assert round(float(body["concentration"]["top_weight_pct"]), 1) == 25.0


def test_concentration_is_null_on_empty_portfolio(client):
    body = client.get("/api/v1/reports/securities-analysis").json()
    assert body["concentration"]["top_weight_pct"] is None
    assert body["concentration"]["effective_holdings"] is None


# --- Currency exposure ----------------------------------------------------


def test_currency_exposure_is_reported_in_eur(client):
    """Currency exposure is expressed in EUR to show the share of assets exposed to exchange rates, without summing different currencies."""
    ref = _make_checking(client)
    acc = _make_investment(client, ref)
    client.post(
        "/api/v1/fx-rates/import",
        files={
            "file": (
                "fx.csv",
                io.BytesIO(b"date;from;to;rate\n2026-01-01;USD;EUR;0.90\n"),
                "text/csv",
            )
        },
    )
    eur_sec = _make_security(client, "ENI.MI", "EUR")
    usd_sec = _make_security(client, "AAPL", "USD")
    _buy(client, eur_sec, acc, 100, 10, currency="EUR")
    _buy(client, usd_sec, acc, 100, 10, currency="USD", fx_rate=0.90)
    _import_price(client, "ENI.MI", 10)
    _import_price(client, "AAPL", 10, fx_rate=0.90)

    body = client.get("/api/v1/reports/securities-analysis").json()
    by_currency = {r["currency"]: r for r in body["by_currency"]}

    assert set(by_currency) == {"EUR", "USD"}
    assert float(by_currency["EUR"]["total_value"]) == 1000.0
    # 100 x 10 USD converted at 0.90 = 900 EUR
    assert float(by_currency["USD"]["total_value"]) == 900.0
    # sort by value descending
    assert body["by_currency"][0]["currency"] == "EUR"
    assert round(sum(float(r["pct_of_total"]) for r in body["by_currency"]), 2) == 100.0


# --- Spending runway ------------------------------------------------------


def test_runway_divides_liquidity_by_average_monthly_expenses(client):
    import datetime as dt

    acc = _make_checking(client, opening=6000)
    cat = client.post("/api/v1/categories", json={"name": "Expenses", "type": "expense"}).json()
    # 3 expenses of 500 in previous months
    today = dt.date.today()
    current_month_index = today.year * 12 + today.month - 1
    for months_ago in (1, 2, 3):
        year, zero_based_month = divmod(current_month_index - months_ago, 12)
        # First day of three distinct calendar months: subtracting 30-day blocks
        # can land twice in the same month (for example on August 30),
        # making the test depend on its execution date.
        date = dt.date(year, zero_based_month + 1, 1)
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc,
                "category_id": cat["id"],
                "date": date.isoformat(),
                "amount": -500,
                "currency": "EUR",
            },
        )

    body = client.get("/api/v1/reports/net-worth").json()
    # 1500 spent over an approximately 12-month window = 125/month
    assert round(float(body["average_monthly_expenses"]), 0) == 125.0
    assert float(body["liquid_balance"]) == 4500.0
    assert round(float(body["runway_months"]), 1) == 36.0


def test_average_expenses_uses_calendar_boundaries_and_the_as_of_cutoff(client):
    account_id = _make_checking(client, opening=10_000)
    category_id = client.post(
        "/api/v1/categories", json={"name": "Calendar expenses", "type": "expense"}
    ).json()["id"]

    # As of 2025-08-15, the window is 2024-09-01–2025-08-15.
    # The two outside movements protect both boundaries.
    for date, amount in (
        ("2024-08-31", -900),
        ("2024-09-01", -100),
        ("2025-08-15", -300),
        ("2025-08-16", -700),
    ):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": date,
                "amount": amount,
                "currency": "EUR",
            },
        )
        assert response.status_code == 201

    body = client.get("/api/v1/reports/net-worth", params={"as_of_date": "2025-08-15"}).json()
    expected = winsorized_mean([Decimal("100"), Decimal("300"), *([Decimal("0")] * 10)])

    assert Decimal(body["average_monthly_expenses"]) == expected


def test_runway_ignores_securities_purchases_and_transfers(client):
    """Purchases and transfers between owned accounts are not expenses. Including them would understate runway specifically in months with investments."""
    import datetime as dt

    ref = _make_checking(client, opening=10000)
    other = _make_checking(client, name="Deposit")
    acc = _make_investment(client, ref)
    sec = _make_security(client, "ENI.MI")
    recent = dt.date.today() - dt.timedelta(days=30)

    cat = client.post("/api/v1/categories", json={"name": "Expenses", "type": "expense"}).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": ref,
            "category_id": cat["id"],
            "date": recent.isoformat(),
            "amount": -200,
            "currency": "EUR",
        },
    )
    # security purchase: creates a cash outflow, but is not an expense
    _buy(client, sec, acc, 100, 20, date=recent.isoformat())
    # transfer between owned accounts
    client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": ref,
            "to_account_id": other,
            "date": recent.isoformat(),
            "amount": 1000,
            "currency": "EUR",
        },
    )

    body = client.get("/api/v1/reports/net-worth").json()
    # Only the 200 of actual expenses enter the 12 monthly values. As the
    # sole peak among eleven zeros, P95 winsorization caps it at 90
    # (45% of 200) and retains all twelve months in the average.
    monthly = float(body["average_monthly_expenses"])
    assert monthly == 7.5


def test_runway_is_null_without_expenses(client):
    _make_checking(client, opening=5000)
    body = client.get("/api/v1/reports/net-worth").json()
    assert body["average_monthly_expenses"] is None
    assert body["runway_months"] is None
    assert float(body["liquid_balance"]) == 5000.0


def test_liquid_balance_excludes_investment_accounts(client):
    ref = _make_checking(client, opening=3000)
    _make_investment(client, ref)
    body = client.get("/api/v1/reports/net-worth").json()
    assert float(body["liquid_balance"]) == 3000.0


# --- Actual net-worth history ---------------------------------------------


def test_net_worth_history_includes_portfolio_value(client):
    """Buying securities reduces cash but not net worth: history must show both separately."""
    ref = _make_checking(client, opening=5000)
    acc = _make_investment(client, ref)
    sec = _make_security(client, "ENI.MI")
    _buy(client, sec, acc, 100, 20, date="2026-02-10")

    points = client.get("/api/v1/reports/net-worth/history").json()
    last = points[-1]

    # cash fell by 2000 for the purchase...
    assert float(last["total_balance"]) == 3000.0
    # ...but became securities, leaving net worth unchanged
    assert float(last["portfolio_value"]) == 2000.0
    assert float(last["net_worth"]) == 5000.0
