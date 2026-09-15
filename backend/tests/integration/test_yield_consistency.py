"""Yield on Cost and Current Yield: one consistent number everywhere.

These indicators divide received income by capital, meaning the entire
position, not one unit's cost. Using unit cost multiplied the result by
units held: 5% became 500% on 100 shares, and /performance/{id} reported
100 times the yield shown by /reports/dividends-analysis for the same
security and dates.

The tests enforce the correct value and independence from how an
investment is divided into units.
"""

import datetime as dt
from decimal import Decimal


def _accounts(client):
    cash = client.post(
        "/api/v1/accounts",
        json={
            "name": "Checking",
            "type": "checking",
            "opening_balance": 100000,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    return cash, investment


def _security(client, ticker: str) -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]


# Use dates relative to today: indicators examine the last 12 months,
# so fixed dates would eventually stop testing
# the intended behavior.
TODAY = dt.date.today()
BUY_DATE = (TODAY - dt.timedelta(days=200)).isoformat()
DIVIDEND_DATE = (TODAY - dt.timedelta(days=30)).isoformat()
PRICE_DATE = (TODAY - dt.timedelta(days=10)).isoformat()


def _position_with_dividend(client, ticker: str, quantity, price, dividend, current_price):
    """An open position with received income and a market price."""
    _, investment = _accounts(client)
    security_id = _security(client, ticker)
    client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": investment,
            "type": "buy",
            "date": BUY_DATE,
            "quantity": quantity,
            "price": price,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/prices",
        json={"security_id": security_id, "date": PRICE_DATE, "price_close": current_price},
    )
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": security_id,
            "account_id": investment,
            "event_type": "dividend",
            "payment_date": DIVIDEND_DATE,
            "total_amount": dividend,
            "currency": "EUR",
        },
    )
    return security_id


def test_yield_on_cost_is_income_over_total_invested(client):
    """EUR 1,000 invested and EUR 50 net dividends -> 5.00%, not 500%."""
    security_id = _position_with_dividend(
        client, "AAA", quantity=100, price=10, dividend=50, current_price=12
    )

    metrics = client.get(f"/api/v1/performance/{security_id}").json()
    assert Decimal(metrics["yield_on_cost"]) == Decimal("5")


def test_current_yield_is_income_over_current_value(client):
    """100 units at EUR 12 are worth EUR 1,200: 50 / 1,200 = 4.1666...%."""
    security_id = _position_with_dividend(
        client, "BBB", quantity=100, price=10, dividend=50, current_price=12
    )

    metrics = client.get(f"/api/v1/performance/{security_id}").json()
    assert round(Decimal(metrics["current_yield"]), 4) == round(Decimal("50") / 12 / 100 * 100, 4)


def test_yield_does_not_depend_on_how_the_position_is_split(client):
    """Equal capital and income must yield the same return whether held as 100 units at EUR 10 or 10 units at EUR 100.

    Dividing by per-unit cost previously returned 500% in the first case
    and 50% in the second.
    """
    many = _position_with_dividend(
        client, "MANY", quantity=100, price=10, dividend=50, current_price=12
    )
    few = _position_with_dividend(
        client, "FEW", quantity=10, price=100, dividend=50, current_price=120
    )

    metrics_many = client.get(f"/api/v1/performance/{many}").json()
    metrics_few = client.get(f"/api/v1/performance/{few}").json()

    assert Decimal(metrics_many["yield_on_cost"]) == Decimal(metrics_few["yield_on_cost"])
    assert Decimal(metrics_many["current_yield"]) == Decimal(metrics_few["current_yield"])


def test_performance_and_dividends_analysis_agree(client):
    """Both endpoints exposing YoC must report the same number.

    Two separate calculations have been replaced by one function,
    app.finance.income.yield_on_cost, called by both. This test prevents
    them from diverging again.
    """
    security_id = _position_with_dividend(
        client, "CCC", quantity=100, price=10, dividend=50, current_price=12
    )

    from_performance = Decimal(
        client.get(f"/api/v1/performance/{security_id}").json()["yield_on_cost"]
    )
    analysis = client.get("/api/v1/reports/dividends-analysis").json()
    from_analysis = Decimal(analysis["by_security"][0]["yield_on_cost_pct"])

    assert from_performance == from_analysis
    # With one security, aggregate YoC also matches.
    assert Decimal(analysis["portfolio_yield_on_cost_pct"]) == from_performance
