"""The cost of /performance/portfolio must not depend on the security count.

The aggregate preloaded trades but delegated to security_performance,
which reread income, latest prices, and trades for each security. Ten
securities caused 64 queries and linear growth: the same pattern removed
from net-worth history had returned through another path.

As in test_portfolio_value_series.py, the constraint is explicit because
such a regression is detected by counting, not by reading a diff.
"""

from sqlalchemy import event

from .conftest import engine


def _accounts(client) -> int:
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opening_balance": 1000000},
    ).json()["id"]
    return client.post(
        "/api/v1/accounts",
        json={"name": "Investment account", "type": "investment", "reference_account_id": cash},
    ).json()["id"]


def _security_with_activity(client, investment_account: int, ticker: str) -> int:
    """A security with a trade, price, and income: everything return metrics need to read."""
    security_id = client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]
    client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": investment_account,
            "type": "buy",
            "date": "2026-01-05",
            "quantity": 10,
            "price": 100,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/prices",
        json={"security_id": security_id, "date": "2026-06-01", "price_close": 120},
    )
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": security_id,
            "account_id": investment_account,
            "event_type": "dividend",
            "payment_date": "2026-03-01",
            "total_amount": 25,
            "currency": "EUR",
        },
    )
    return security_id


def _count_queries_of(client, path: str) -> int:
    counter = {"n": 0}

    def _tick(*args, **kwargs):
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _tick)
    try:
        assert client.get(path).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", _tick)
    return counter["n"]


def test_portfolio_performance_cost_does_not_grow_with_the_number_of_securities(client):
    investment = _accounts(client)
    for i in range(2):
        _security_with_activity(client, investment, f"A{i}")
    few = _count_queries_of(client, "/api/v1/performance/portfolio")

    for i in range(8):
        _security_with_activity(client, investment, f"B{i}")
    many = _count_queries_of(client, "/api/v1/performance/portfolio")

    assert (
        few == many
    ), f"{few} queries with 2 securities, {many} with 10: cost scales with security count"


def test_portfolio_performance_stays_within_a_handful_of_queries(client):
    """An absolute ceiling supplements comparison: a constant but enormous query count would pass the previous test."""
    investment = _accounts(client)
    for i in range(4):
        _security_with_activity(client, investment, f"C{i}")

    assert _count_queries_of(client, "/api/v1/performance/portfolio") <= 20
