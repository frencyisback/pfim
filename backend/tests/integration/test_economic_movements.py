"""Income-statement cash flows and category-analysis expenses (§5.4, §7.5).

The income statement includes cash from security trades. Category analysis
and runway remain based on economic expenses. Both views exclude
transfers between the user's own accounts.
"""

from decimal import Decimal

import pytest


def _checking(client, name="Checking", opening=0) -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "checking",
            "opening_balance": opening,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _investment(client, ref, name="Investment account") -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "investment",
            "reference_account_id": ref,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _security(client, ticker="AAA") -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _tx(client, account_id, category_id, amount, date="2026-03-10", description="movement"):
    return client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": date,
            "amount": str(amount),
            "description": description,
        },
    ).json()


@pytest.fixture
def scenario(client):
    """One month with a salary, an expense, a security purchase, a transfer, a coupon, and a recurring cost."""
    cc = _checking(client, opening=10_000)
    savings = _checking(client, name="Savings")
    dep = _investment(client, cc)
    sec = _security(client)
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "Salary", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "Expense", "type": "expense"}
    ).json()["id"]

    _tx(client, cc, income_category_id, 2000, description="Salary")
    _tx(client, cc, expense_category_id, -300, description="Expense")

    # Security purchase: creates a cash outflow of 1,000
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec,
            "account_id": dep,
            "type": "buy",
            "date": "2026-03-12",
            "quantity": 10,
            "price": 100,
            "currency": "EUR",
        },
    )
    # Transfer: -500 from cc, +500 to savings
    client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": cc,
            "to_account_id": savings,
            "date": "2026-03-15",
            "amount": 500,
            "currency": "EUR",
        },
    )
    # Coupon received: REAL income
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec,
            "account_id": dep,
            "event_type": "dividend",
            "payment_date": "2026-03-20",
            "total_amount": 50,
            "currency": "EUR",
        },
    )
    # Recurring cost: REAL expense
    client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-03-25",
            "cost_type": "custody_fee",
            "account_id": dep,
            "amount": 20,
            "currency": "EUR",
        },
    )
    return {"cc": cc, "savings": savings, "dep": dep, "security": sec}


class TestIncomeStatement:
    def test_includes_securities_purchases(self, client, scenario):
        """Purchase cash appears in the month of the linked movement."""
        body = client.get("/api/v1/reports/income-statement").json()
        # 300 expense + 20 custody + 1,000 security purchase.
        assert Decimal(body["total_expense"]) == -1320

    def test_excludes_both_legs_of_a_transfer(self, client, scenario):
        """Exclude both sides, not just the net: previously they canceled in the total but inflated gross income and expenses and therefore the savings rate."""
        body = client.get("/api/v1/reports/income-statement").json()
        # real income: 2000 (salary) + 50 (coupon) = 2050, not 2,550
        assert Decimal(body["total_income"]) == 2050

    def test_keeps_dividends_and_recurring_costs(self, client, scenario):
        """Coupons and custody costs are real income and expenses: retain them."""
        body = client.get("/api/v1/reports/income-statement").json()
        assert Decimal(body["total_income"]) == 2050  # includes the coupon
        assert Decimal(body["total_expense"]) == -1320  # includes custody

    def test_savings_rate_includes_the_securities_cash_flow(self, client, scenario):
        period = client.get("/api/v1/reports/income-statement").json()["periods"][0]
        # (2050 - 1320) / 2050 = 35.61%.
        assert Decimal(period["savings_rate_pct"]).quantize(Decimal("0.01")) == Decimal("35.61")

    def test_net_is_unaffected_by_transfers(self, client, scenario):
        """The two sides already canceled in the net: that number stays unchanged."""
        body = client.get("/api/v1/reports/income-statement").json()
        assert Decimal(body["net"]) == 730  # 2050 - 1320

    def test_trade_costs_are_counted_once_in_the_linked_cash_movement(self, client, scenario):
        trades = client.get("/api/v1/trades").json()
        buy_id = trades[0]["id"]
        cost = client.post(
            f"/api/v1/trades/{buy_id}/costs",
            json={"cost_type": "commission", "amount": 10, "currency": "EUR"},
        )
        assert cost.status_code == 201, cost.text
        sale = client.post(
            "/api/v1/trades",
            json={
                "security_id": scenario["security"],
                "account_id": scenario["dep"],
                "type": "sell",
                "date": "2026-04-01",
                "quantity": 10,
                "price": 120,
                "currency": "EUR",
            },
        )
        assert sale.status_code == 201, sale.text
        cost = client.post(
            f"/api/v1/trades/{sale.json()['id']}/costs",
            json={"cost_type": "commission", "amount": 20, "currency": "USD", "fx_rate": "0.9"},
        )
        assert cost.status_code == 201, cost.text

        report = client.get("/api/v1/reports/income-statement").json()
        periods = {period["period_label"]: period for period in report["periods"]}
        assert Decimal(periods["2026-03"]["total_expense"]) == -1330
        assert Decimal(periods["2026-04"]["total_income"]) == 1182
        assert Decimal(report["total_income"]) == 3232
        assert Decimal(report["total_expense"]) == -1330

        april = client.get(
            "/api/v1/reports/income-statement",
            params={"date_from": "2026-04-01", "date_to": "2026-04-30"},
        ).json()
        assert Decimal(april["total_income"]) == 1182
        assert Decimal(april["total_expense"]) == 0


class TestCategoryAnalyses:
    def test_spending_analysis_excludes_securities_purchases(self, client, scenario):
        body = client.get("/api/v1/reports/spending-analysis").json()
        categories = {c["category_name"] for c in body["by_category"]}
        assert "Security Purchase" not in categories
        assert Decimal(body["total_amount"]) == -320

    def test_transfer_analysis_still_shows_transfers(self, client, scenario):
        """This is the report that must include transfers: excluding them here would leave it empty."""
        body = client.get("/api/v1/reports/transfer-analysis").json()
        assert body["by_category"]
        assert body["by_month"]

    def test_transfer_analysis_reports_the_volume_moved(self, client, scenario):
        """Both sides of a transfer cancel: summing them would ALWAYS produce zero, displaying EUR 0.00 regardless of the amount transferred. Count only the outgoing side, in absolute value."""
        body = client.get("/api/v1/reports/transfer-analysis").json()
        assert Decimal(body["total_amount"]) == 500

    def test_a_transfer_is_counted_once_not_twice(self, client, scenario):
        """Counting both sides in absolute value would double the volume: transferring 500 does not mean moving 1,000."""
        body = client.get("/api/v1/reports/transfer-analysis").json()
        assert len(body["top_transactions"]) == 1

    def test_income_analysis_excludes_securities_sales(self, client, scenario):
        client.post(
            "/api/v1/trades",
            json={
                "security_id": scenario["security"],
                "account_id": scenario["dep"],
                "type": "sell",
                "date": "2026-04-01",
                "quantity": 10,
                "price": 120,
                "currency": "EUR",
            },
        )
        body = client.get("/api/v1/reports/income-analysis").json()
        categories = {c["category_name"] for c in body["by_category"]}
        assert "Security Sale" not in categories


class TestReportScopes:
    def test_statement_adds_trade_cash_to_economic_expenses(self, client, scenario):
        statement = client.get("/api/v1/reports/income-statement").json()
        analysis = client.get("/api/v1/reports/spending-analysis").json()
        assert Decimal(statement["total_expense"]) == Decimal(analysis["total_amount"]) - 1000

    def test_average_monthly_expenses_keeps_the_economic_definition(self, client, scenario):
        net_worth = client.get(
            "/api/v1/reports/net-worth", params={"as_of_date": "2026-03-31"}
        ).json()
        analysis = client.get("/api/v1/reports/spending-analysis").json()

        # The average is winsorized over 12 months (eleven zero months here),
        # so the sole nonzero month's peak is capped at P95. Both views
        # must still start from the same economic expense of 320 euros.
        assert net_worth["average_monthly_expenses"] is not None
        monthly_spend = abs(Decimal(analysis["total_amount"]))
        # With 11 zeros and one peak, P95 = 45% of the peak; all 12 months remain.
        expected = monthly_spend * Decimal("0.45") / 12
        assert Decimal(net_worth["average_monthly_expenses"]) == expected

    def test_cash_balance_still_counts_everything(self, client, scenario):
        """The account BALANCE remains a cash view: purchases and transfers must appear there to reconcile with the bank statement."""
        balance = client.get(f"/api/v1/accounts/{scenario['cc']}/balance").json()
        # 10000 + 2000 - 300 - 1000 (purchase) - 500 (transfer) + 50 - 20
        assert Decimal(balance["balance"]) == 10230
