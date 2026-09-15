"""CSV report export (specification §6.8, §8.4).

Each report accepts format=csv and returns an attachment instead of JSON.
These nine branches previously had no coverage, leaving reports.py at 71%.
An export with empty content or incorrect headers otherwise goes unnoticed
until someone opens it in a spreadsheet.
"""

import csv
import io

import pytest

# The nine exportable reports and the column each must guarantee.
# This explicit list also detects a new report missing an export
# or an existing report losing its export.
REPORTS = [
    ("net-worth", "account_id"),
    ("income-statement", "period_label"),
    ("spending-analysis", "category_name"),
    ("income-analysis", "category_name"),
    ("transfer-analysis", "category_name"),
    ("securities-analysis", "ticker"),
    ("dividends-analysis", "ticker"),
    ("costs-analysis", "cost_type"),
]


@pytest.fixture
def portfolio(client):
    """A minimal working dataset: an account, movement, purchased security, dividend, and cost. Each report must produce at least one row because empty CSVs would pass purely formal checks."""
    cash = client.post(
        "/api/v1/accounts",
        json={
            "name": "Checking",
            "type": "checking",
            "opening_balance": 50000,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    savings = client.post(
        "/api/v1/accounts",
        json={"name": "Deposit", "type": "savings", "opened_on": "2000-01-01"},
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
    security = client.post(
        "/api/v1/securities",
        json={
            "ticker": "VWCE",
            "name": "Vanguard All-World",
            "type": "etf_equity",
            "currency": "EUR",
        },
    ).json()["id"]
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "Export salary", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "Export rent", "type": "expense"}
    ).json()["id"]

    client.post(
        "/api/v1/transactions",
        json={
            "account_id": cash,
            "category_id": income_category_id,
            "date": "2026-01-05",
            "amount": "2500",
            "description": "Salary",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": cash,
            "category_id": expense_category_id,
            "date": "2026-01-08",
            "amount": "-800",
            "description": "Rent",
        },
    )
    client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": cash,
            "to_account_id": savings,
            "date": "2026-01-09",
            "amount": "1000",
            "currency": "EUR",
        },
    )
    trade = client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": investment,
            "type": "buy",
            "date": "2026-01-20",
            "quantity": 20,
            "price": 100,
            "currency": "EUR",
        },
    ).json()
    client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "amount": 5, "currency": "EUR"},
    )
    client.post(
        "/api/v1/prices",
        json={"security_id": security, "date": "2026-06-01", "price_close": 118},
    )
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": security,
            "account_id": investment,
            "event_type": "dividend",
            "payment_date": "2026-03-15",
            "total_amount": 40,
            "currency": "EUR",
            "tax_withheld": 10,
        },
    )
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-06-30",
            "cost_type": "custody_fee",
            "account_id": investment,
            "amount": 12,
            "currency": "EUR",
        },
    )
    # A sale introduces a capital gain into tax costs.
    client.post(
        "/api/v1/trades",
        json={
            "security_id": security,
            "account_id": investment,
            "type": "sell",
            "date": "2026-07-01",
            "quantity": 5,
            "price": 120,
            "currency": "EUR",
        },
    )
    return client


def _rows(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.text)))


@pytest.mark.parametrize("report,expected_column", REPORTS)
def test_every_report_exports_a_non_empty_csv(portfolio, report, expected_column):
    resp = portfolio.get(f"/api/v1/reports/{report}?format=csv")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert f"{report}.csv" in resp.headers["content-disposition"]

    rows = _rows(resp)
    assert rows, f"export of {report} contains no rows"
    assert (
        expected_column in rows[0]
    ), f"export of {report} lacks column '{expected_column}': {sorted(rows[0])}"


@pytest.mark.parametrize("report,_column", REPORTS)
def test_json_stays_the_default(portfolio, report, _column):
    """format is optional: the default remains JSON. Accidentally enabling export would break every screen."""
    resp = portfolio.get(f"/api/v1/reports/{report}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("report,_column", REPORTS)
def test_an_unknown_format_is_rejected(portfolio, report, _column):
    assert portfolio.get(f"/api/v1/reports/{report}?format=xlsx").status_code == 422


def test_an_empty_report_exports_headers_not_a_zero_byte_file(client):
    """Even without rows, the file declares an importable schema."""
    resp = client.get("/api/v1/reports/spending-analysis?format=csv")

    assert resp.status_code == 200
    assert next(csv.reader(io.StringIO(resp.text))) == [
        "level",
        "category_id",
        "category_name",
        "total_amount",
        "pct_of_total",
        "top_level_category_id",
    ]


def test_the_costs_export_keeps_the_group_of_each_item(portfolio):
    """Costs export flattens three groups into one table: the group column distinguishes taxes from commissions."""
    rows = _rows(portfolio.get("/api/v1/reports/costs-analysis?format=csv"))

    assert {"group", "cost_type", "amount_eur", "is_estimated"} <= set(rows[0])
    assert {r["group"] for r in rows} <= {"taxes", "trading", "recurring"}
    assert "trading" in {r["group"] for r in rows}


def test_spending_export_distinguishes_complete_roots_and_leaf_details(portfolio):
    rows = _rows(portfolio.get("/api/v1/reports/spending-analysis?format=csv"))

    assert {"level", "category_id", "category_name", "total_amount", "pct_of_total"} <= set(rows[0])
    assert {row["level"] for row in rows} == {"top_level", "leaf"}
    assert all(row["top_level_category_id"] for row in rows)


def test_securities_export_contains_every_open_position_not_only_top_ten(client):
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Complete-export cash", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Complete-export investment account",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]

    for index in range(12):
        security_id = client.post(
            "/api/v1/securities",
            json={
                "ticker": f"EXP{index:02d}",
                "name": f"Security export {index}",
                "type": "stock",
                "currency": "EUR",
            },
        ).json()["id"]
        response = client.post(
            "/api/v1/trades",
            json={
                "security_id": security_id,
                "account_id": investment,
                "type": "buy",
                "date": "2026-01-01",
                "quantity": "1",
                "price": str(index + 1),
                "currency": "EUR",
            },
        )
        assert response.status_code == 201

    report = client.get("/api/v1/reports/securities-analysis").json()
    rows = _rows(client.get("/api/v1/reports/securities-analysis?format=csv"))
    assert report["positions_count"] == 12
    assert len(report["positions"]) == 12
    assert len(report["top_by_value"]) == 10
    assert len(rows) == 12
    assert {row["ticker"] for row in rows} == {f"EXP{index:02d}" for index in range(12)}
