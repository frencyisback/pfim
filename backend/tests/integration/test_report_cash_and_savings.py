"""Report regressions: cash, average savings rate, and category details.

Shared fixtures create only synthetic data in an in-memory SQLite database.
"""

import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy import delete

from app.models.income_event import IncomeEvent
from app.models.portfolio_cost import PortfolioCost
from app.models.transaction import Transaction

from .conftest import TestingSessionLocal


def _create(client, resource, **payload):
    response = client.post(f"/api/v1/{resource}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _account(client, name="Checking", type="checking", opening_balance=0, **extra):
    return _create(
        client,
        "accounts",
        name=name,
        type=type,
        opening_balance=opening_balance,
        opened_on="2000-01-01",
        **extra,
    )


def _transaction(client, account_id, category_id, amount, date="2026-01-15"):
    return _create(
        client,
        "transactions",
        account_id=account_id,
        category_id=category_id,
        amount=str(amount),
        date=date,
        currency="EUR",
    )


def test_available_liquidity_sums_only_checking_accounts_with_their_signed_balance(client):
    checking = _account(client, opening_balance=3000)
    _account(client, name="Overdrawn checking account", opening_balance=-250)
    _account(client, name="Deposit", type="savings", opening_balance=10000)
    _account(client, name="Cash", type="cash", opening_balance=900)
    _account(client, name="Securities", type="investment", reference_account_id=checking)
    income = _create(client, "categories", name="Income", type="income")
    _transaction(client, checking, income, 50)
    _transaction(client, checking, income, 200, date="2026-02-01")

    report = client.get("/api/v1/reports/net-worth", params={"as_of_date": "2026-01-31"}).json()

    assert Decimal(report["liquid_balance"]) == 2800
    assert Decimal(report["total_accounts_balance"]) == 13700
    assert Decimal(report["net_worth"]) == 13700
    assert len(report["by_account"]) == 5


def test_savings_rate_average_excludes_undefined_months_and_keeps_single_values(client):
    account = _account(client, opening_balance=10000)
    income = _create(client, "categories", name="Income", type="income")
    expense = _create(client, "categories", name="Expense", type="expense")
    for date, category, amount in (
        ("2026-01-01", income, 100),
        ("2026-01-31", expense, -50),
        ("2026-02-01", income, 1000),
        ("2026-02-28", expense, -1100),
        ("2026-03-15", expense, -500),
        ("2026-05-01", income, 100),
    ):
        _transaction(client, account, category, amount, date)

    report = client.get(
        "/api/v1/reports/income-statement",
        params={"date_from": "2026-01-01", "date_to": "2026-04-30"},
    ).json()
    periods = {period["period_label"]: period for period in report["periods"]}

    assert Decimal(periods["2026-01"]["savings_rate_pct"]) == 50
    assert Decimal(periods["2026-02"]["savings_rate_pct"]) == -10
    assert periods["2026-03"]["savings_rate_pct"] is None
    assert "2026-04" not in periods
    assert Decimal(report["average_savings_rate_pct"]) == 20
    assert report["savings_rate_months"] == 2
    # The ratio of totals is -50%, not the required mean of rates.
    assert Decimal(report["net"]) / Decimal(report["total_income"]) * 100 == -50
    assert Decimal(report["economic_savings_rate_pct"]) == -50
    assert Decimal(report["economic_savings"]) == -550

    february = client.get(
        "/api/v1/reports/income-statement",
        params={"date_from": "2026-02-01", "date_to": "2026-02-28"},
    ).json()
    assert Decimal(february["average_savings_rate_pct"]) == -10
    assert february["savings_rate_months"] == 1


def test_household_savings_exclude_principal_and_include_fees_even_on_a_zero_cash_sale(client):
    cash = _account(client)
    investment = _account(client, "Broker", type="investment", reference_account_id=cash)
    security = _create(client, "securities", name="Index", ticker="IDX", type="etf", currency="EUR")
    income = _create(client, "categories", name="Salary", type="income")
    expense = _create(client, "categories", name="Living costs", type="expense")
    _transaction(client, cash, income, 2000)
    _transaction(client, cash, expense, -1000)
    trade_fields = dict(account_id=investment, security_id=security, currency="EUR", price=100)
    buy = _create(client, "trades", type="buy", quantity=10, date="2026-01-15", **trade_fields)
    path = "/api/v1/reports/income-statement"
    jan = client.get(path).json()["periods"][0]
    assert Decimal(jan["savings_rate_pct"]) == 0
    assert Decimal(jan["economic_savings"]) == 1000
    assert Decimal(jan["economic_savings_rate_pct"]) == 50

    _create(client, f"trades/{buy}/costs", cost_type="commission", amount=10)
    for kind, gross, tax in [("dividend", 22, 2), ("return_of_capital", 25, 5)]:
        _create(
            client,
            "income-events",
            account_id=investment,
            security_id=security,
            payment_date="2026-01-20",
            event_type=kind,
            total_amount=gross,
            currency="EUR",
            tax_withheld=tax,
        )
    sale = _create(client, "trades", type="sell", quantity=1, date="2026-02-01", **trade_fields)
    _create(client, f"trades/{sale}/costs", cost_type="commission", amount=100)
    report = client.get(path).json()
    january, february = report["periods"]
    assert Decimal(january["economic_income"]) == 2020
    income_report = client.get("/api/v1/reports/income-analysis").json()
    assert Decimal(income_report["total_amount"]) == 2020
    assert all(
        item["category_name"] != "Principal repayment" for item in income_report["by_category"]
    )
    assert Decimal(january["economic_spending"]) == 1015
    assert Decimal(january["economic_savings"]) == 1005
    assert Decimal(february["net"]) == 0
    assert Decimal(february["economic_savings"]) == -100
    assert february["economic_savings_rate_pct"] is None
    assert Decimal(report["economic_savings"]) == 905
    assert Decimal(report["economic_savings_rate_pct"]) == Decimal(905) / 2020 * 100
    # A date-filtered CSV includes only the loss from the zero-net sale.
    rows = list(
        csv.DictReader(
            io.StringIO(client.get(path, params={"date_from": "2026-02-01", "format": "csv"}).text)
        )
    )
    assert len(rows) == 1
    assert Decimal(rows[0]["economic_spending"]) == 100


@pytest.mark.parametrize("linked", [True, False])
def test_household_savings_count_custody_fees_once_with_or_without_linked_cash(client, linked):
    cash = _account(client)
    broker = _account(client, "Broker", type="investment", reference_account_id=cash)
    security = _create(client, "securities", name="Bond", ticker="BND", type="bond", currency="EUR")
    event = _create(
        client,
        "income-events",
        account_id=broker,
        security_id=security,
        payment_date="2026-01-12",
        event_type="coupon",
        total_amount=100,
        currency="EUR",
    )
    fee = _create(
        client,
        "portfolio-costs",
        account_id=broker,
        date="2026-01-15",
        cost_type="custody_fee",
        amount=100,
        currency="EUR",
    )
    if not linked:
        # Older records can retain the event and charge with no recoverable cash origin.
        with TestingSessionLocal.begin() as db:
            db.execute(delete(Transaction).where(Transaction.income_event_id == event))
            db.execute(delete(Transaction).where(Transaction.portfolio_cost_id == fee))
            db.get(IncomeEvent, event).cash_account_id = None
            db.get(PortfolioCost, fee).cash_account_id = None

    report = client.get("/api/v1/reports/income-statement").json()
    assert Decimal(report["economic_income"]) == 100
    assert Decimal(report["economic_spending"]) == 100
    assert Decimal(report["economic_savings"]) == 0
    assert Decimal(report["total_income"]) == (100 if linked else 0)
    assert Decimal(report["total_expense"]) == (-100 if linked else 0)


@pytest.mark.parametrize(("starting", "expected"), [(4000, 3), (1000, 0), (500, 0)])
def test_sparse_runway_uses_observed_month_and_recognises_exhausted_cash(
    client, starting, expected
):
    checking = _account(client, opening_balance=starting)
    expense = _create(client, "categories", name="Rent", type="expense")
    _transaction(client, checking, expense, -1000, date="2026-01-05")
    short = client.get("/api/v1/reports/net-worth", params={"as_of_date": "2026-01-06"}).json()
    assert short["average_monthly_expenses"] is None
    if expected:
        assert short["runway_months"] is None
    else:
        assert Decimal(short["runway_months"]) == 0
    assert short["spending_coverage"]["months_with_recorded_expenses"] == 0
    assert Decimal(short["spending_coverage"]["partial_month_spending"]) == 1000
    month_end = client.get("/api/v1/reports/net-worth", params={"as_of_date": "2026-01-31"}).json()
    assert Decimal(month_end["average_monthly_expenses"]) == 1000
    assert Decimal(month_end["runway_months"]) == expected
    assert month_end["spending_coverage"]["months_with_recorded_expenses"] == 1
    assert month_end["spending_coverage"]["partial_month_spending"] is None


def test_savings_rate_average_limits_both_percentile_tails_without_changing_months(client):
    account = _account(client, opening_balance=10000)
    income = _create(client, "categories", name="Income", type="income")
    expense = _create(client, "categories", name="Expense", type="expense")
    for month, spending in ((1, 0), (2, 300), (3, 100), (5, 80), (6, 60)):
        _transaction(client, account, income, 100, date=f"2026-{month:02}-01")
        if spending:
            _transaction(client, account, expense, -spending, date=f"2026-{month:02}-02")
    # April has no income, July no movements, and August is outside the period.
    _transaction(client, account, expense, -500, date="2026-04-01")
    _transaction(client, account, income, 100, date="2026-08-01")

    response = client.get(
        "/api/v1/reports/income-statement",
        params={"date_from": "2026-01-01", "date_to": "2026-07-31"},
    )
    assert response.status_code == 200, response.text
    report = response.json()
    rates = {
        period["period_label"]: (
            Decimal(period["savings_rate_pct"]) if period["savings_rate_pct"] is not None else None
        )
        for period in report["periods"]
    }
    assert rates == {
        "2026-01": Decimal("100"),
        "2026-02": Decimal("-200"),
        "2026-03": Decimal("0"),
        "2026-04": None,
        "2026-05": Decimal("20"),
        "2026-06": Decimal("40"),
    }
    # Sorted sample [-200, 0, 20, 40, 100]: P5=-160, P95=88.
    # The capped mean is -2.4%; the uncapped mean would be -8%.
    assert Decimal(report["average_savings_rate_pct"]) == Decimal("-2.4")
    assert report["savings_rate_months"] == 5
    assert Decimal(report["total_income"]) == 500
    assert Decimal(report["total_expense"]) == -1040
    assert Decimal(report["net"]) == -540


@pytest.mark.parametrize("with_expense", [False, True])
def test_savings_rate_average_is_unavailable_without_a_month_with_income(client, with_expense):
    if with_expense:
        account = _account(client, opening_balance=1000)
        category = _create(client, "categories", name="Expense", type="expense")
        _transaction(client, account, category, -100)

    report = client.get("/api/v1/reports/income-statement").json()
    assert report["average_savings_rate_pct"] is None
    assert report["savings_rate_months"] == 0


def test_category_detail_keeps_every_child_of_a_root_and_the_requested_period(client):
    account = _account(client, opening_balance=10000)
    root = _create(client, "categories", name="Home", type="expense")
    other = _create(client, "categories", name="Other", type="expense")
    children = []
    for index in range(12):
        child = _create(
            client, "categories", name=f"Household expense {index}", type="expense", parent_id=root
        )
        children.append(child)
        _transaction(client, account, child, -(index + 1))
    _transaction(client, account, children[0], -2, date="2026-01-31")
    _transaction(client, account, children[0], -999, date="2026-02-01")
    _transaction(client, account, other, -200)

    report = client.get(
        "/api/v1/reports/spending-analysis",
        params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
    ).json()
    detail = report["by_category_detail"]
    home = [row for row in detail if row["top_level_category_id"] == root]
    roots = {row["category_id"]: row for row in report["by_top_level_category"]}

    assert len(report["by_category"]) == 10
    assert len(detail) == 13
    assert len(home) == 12
    assert {row["category_id"] for row in home} == set(children)
    assert sum(Decimal(row["total_amount"]) for row in home) == -80
    assert Decimal(roots[root]["total_amount"]) == -80
    assert Decimal(report["total_amount"]) == -280
    assert detail[0]["category_id"] == other
    assert detail[0]["top_level_category_id"] == other
    amounts = [abs(Decimal(row["total_amount"])) for row in detail]
    assert amounts == sorted(amounts, reverse=True)

    export = client.get(
        "/api/v1/reports/spending-analysis",
        params={"date_from": "2026-01-01", "date_to": "2026-01-31", "format": "csv"},
    )
    assert export.status_code == 200, export.text
    rows = list(csv.DictReader(io.StringIO(export.text)))
    leaves = [row for row in rows if row["level"] == "leaf"]
    assert len(leaves) == 13
    assert len([row for row in rows if row["level"] == "top_level"]) == 2
    exported_home = [row for row in leaves if row["top_level_category_id"] == str(root)]
    assert len(exported_home) == 12
    assert sum(Decimal(row["total_amount"]) for row in exported_home) == -80
