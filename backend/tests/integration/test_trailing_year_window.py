"""Last 12 months must mean the same thing everywhere.

app.finance.periods centralizes calendar conventions after one calculation
used 360 days and another 365. Unifying the constant still left different
comparisons: >= today - 365 versus > today - 365, giving 366- and 365-day
windows. Income exactly one year old appeared in security performance but
vanished from dividend analysis.

These tests compare both numbers directly to expose the discrepancy.
"""

import datetime as dt

from app.finance.periods import DAYS_PER_YEAR

TODAY = dt.date.today()


def _portfolio_with_one_dividend(client, days_ago: int) -> int:
    """A security with an open position and one income event dated days_ago days ago. Return its ID."""
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    invest = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": checking,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    security = client.post(
        "/api/v1/securities",
        json={"ticker": "AAA", "name": "Alpha", "type": "stock", "currency": "EUR"},
    ).json()["id"]
    client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": invest,
            "type": "buy",
            "date": (TODAY - dt.timedelta(days=DAYS_PER_YEAR * 3)).isoformat(),
            "quantity": 100,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/prices",
        json={"security_id": security, "date": TODAY.isoformat(), "price_close": 12},
    )
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": security,
            "account_id": invest,
            "event_type": "dividend",
            "payment_date": (TODAY - dt.timedelta(days=days_ago)).isoformat(),
            "total_amount": 50,
            "currency": "EUR",
        },
    )
    return security


def _both_views(client, security_id: int) -> tuple[bool, bool]:
    """(income counts for /performance, income counts for dividends-analysis)."""
    performance = client.get(f"/api/v1/performance/{security_id}").json()
    dividends = client.get("/api/v1/reports/dividends-analysis").json()
    return (
        performance["yield_on_cost"] is not None,
        float(dividends["trailing_12m_net"]) > 0,
    )


def test_a_payout_exactly_one_year_old_is_judged_the_same_by_both_reports(client):
    """The inconsistent case: exactly 365 days ago."""
    security_id = _portfolio_with_one_dividend(client, days_ago=DAYS_PER_YEAR)

    in_performance, in_dividends = _both_views(client, security_id)

    assert in_performance == in_dividends


def test_a_payout_just_inside_the_window_counts_in_both(client):
    security_id = _portfolio_with_one_dividend(client, days_ago=DAYS_PER_YEAR - 1)

    assert _both_views(client, security_id) == (True, True)


def test_a_payout_just_outside_the_window_counts_in_neither(client):
    security_id = _portfolio_with_one_dividend(client, days_ago=DAYS_PER_YEAR + 1)

    assert _both_views(client, security_id) == (False, False)


def test_the_window_is_exactly_one_year_long(client):
    """Fix the chosen convention: the window contains DAYS_PER_YEAR days including today, so the day exactly DAYS_PER_YEAR days ago is outside it."""
    security_id = _portfolio_with_one_dividend(client, days_ago=DAYS_PER_YEAR)

    assert _both_views(client, security_id) == (False, False)
