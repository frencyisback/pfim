"""The cost of /performance/portfolio must not depend on the security count.

The aggregate preloaded trades but delegated to security_performance,
which reread income, latest prices, and trades for each security. Ten
securities caused 64 queries and linear growth: the same pattern removed
from net-worth history had returned through another path.

As in test_portfolio_value_series.py, the constraint is explicit because
such a regression is detected by counting, not by reading a diff.
"""

import datetime as dt

from sqlalchemy import event

from .conftest import engine


def _accounts(client) -> int:
    cash = client.post(
        "/api/v1/accounts",
        json={
            "name": "Checking",
            "type": "checking",
            "opening_balance": 1000000,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _security_with_activity(client, investment_account: int, ticker: str) -> int:
    """A security with a trade, price, and income: everything return metrics need to read."""
    security_id = client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]
    today = dt.date.today()
    trade = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": investment_account,
            "type": "buy",
            "date": (today - dt.timedelta(days=365)).isoformat(),
            "quantity": 10,
            "price": 100,
            "currency": "EUR",
        },
    )
    assert trade.status_code == 201, trade.text
    price = client.post(
        "/api/v1/prices",
        json={"security_id": security_id, "date": today.isoformat(), "price_close": 120},
    )
    assert price.status_code == 201, price.text
    income = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security_id,
            "account_id": investment_account,
            "event_type": "dividend",
            "payment_date": (today - dt.timedelta(days=100)).isoformat(),
            "total_amount": 25,
            "currency": "EUR",
        },
    )
    assert income.status_code == 201, income.text
    return security_id


def _count_queries_of(client, path: str, expected_positions: int) -> int:
    counter = {"n": 0}

    def _tick(*args, **kwargs):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _tick)
    try:
        response = client.get(path)
        assert response.status_code == 200
        assert len(response.json()["by_security"]) == expected_positions
    finally:
        event.remove(engine, "before_cursor_execute", _tick)
    return counter["n"]


def test_portfolio_performance_cost_does_not_grow_with_the_number_of_securities(client):
    investment = _accounts(client)
    for i in range(2):
        _security_with_activity(client, investment, f"A{i}")
    few = _count_queries_of(client, "/api/v1/performance/portfolio", 2)

    for i in range(8):
        _security_with_activity(client, investment, f"B{i}")
    many = _count_queries_of(client, "/api/v1/performance/portfolio", 10)

    assert (
        few == many
    ), f"{few} queries with 2 securities, {many} with 10: cost scales with security count"


def test_portfolio_performance_stays_within_a_handful_of_queries(client):
    """An absolute ceiling supplements comparison: a constant but enormous query count would pass the previous test."""
    investment = _accounts(client)
    for i in range(4):
        _security_with_activity(client, investment, f"C{i}")

    assert _count_queries_of(client, "/api/v1/performance/portfolio", 4) <= 20
