"""Integration tests for CONVERSION AT ENTRY
(docs/multi-currency.md, specification §9.8).

Every incoming amount declares its currency and, for non-EUR amounts, the
exchange rate at that time. Its euro value is frozen at save time; all
subsequent totals simply sum euros.

These tests cover:
  1. REJECTION of missing or invalid rates;
  2. correct CONVERSION for every entity accepting amounts;
  3. CONSISTENCY across reports exposing the same data, where discrepancies
     occurred before this rule.
"""

import datetime as dt
import io
from decimal import Decimal

import pytest

from app.services.performance_service import PerformanceService

from .conftest import TestingSessionLocal

USD_RATE = 0.92


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------
def _checking(client, name="Checking Account") -> int:
    return client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]


def _investment(client, ref_id: int, name="Deposit") -> int:
    return client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "investment",
            "reference_account_id": ref_id,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _security(client, ticker: str, currency: str) -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": ticker, "name": ticker, "type": "stock", "currency": currency},
    ).json()["id"]


def _trade(client, security_id, account_id, **kwargs):
    payload = {
        "security_id": security_id,
        "account_id": account_id,
        "type": "buy",
        "date": "2026-01-01",
        "quantity": 10,
        "price": 100,
        "currency": "EUR",
        **kwargs,
    }
    return client.post("/api/v1/trades", json=payload)


def _import_prices(client, rows: str):
    """rows: already formatted rows, without a header."""
    csv_content = "date;ticker;close;fx_rate\n" + rows
    return client.post(
        "/api/v1/prices/import",
        files={"file": ("p.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )


def _import_fx(client, from_ccy="USD", rate=USD_RATE, date="2026-01-01"):
    csv_content = f"date;from;to;rate\n{date};{from_ccy};EUR;{rate}\n"
    return client.post(
        "/api/v1/fx-rates/import",
        files={"file": ("fx.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")},
    )


# --------------------------------------------------------------------------
# 1. Exchange rates are required, and implicit for euros
# --------------------------------------------------------------------------
class TestRuleIsEnforced:
    def test_foreign_trade_without_rate_is_rejected(self, client):
        """Previously accepted: the rate was looked up at runtime; if missing, the operation had no converted value and did not move cash."""
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")

        resp = _trade(client, sec, acc, currency="USD")

        assert resp.status_code == 400
        body = resp.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert "USD" in body["message"]
        assert body["detail"]["currency"] == "USD"

    def test_eur_trade_without_rate_is_accepted_with_rate_one(self, client):
        """The normal case must not require extra user input."""
        acc = _investment(client, _checking(client))
        sec = _security(client, "ENI.MI", "EUR")

        resp = _trade(client, sec, acc)

        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["fx_rate"]) == 1
        assert Decimal(body["total_eur"]) == Decimal(body["total_amount"])

    def test_eur_trade_with_a_rate_other_than_one_is_rejected(self, client):
        acc = _investment(client, _checking(client))
        sec = _security(client, "ENI.MI", "EUR")

        resp = _trade(client, sec, acc, fx_rate=0.92)

        assert resp.status_code == 400
        assert "does not need an exchange rate" in resp.json()["message"]

    @pytest.mark.parametrize("rate", [0, -1])
    def test_non_positive_rate_is_rejected(self, client, rate):
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")

        resp = _trade(client, sec, acc, currency="USD", fx_rate=rate)

        assert resp.status_code == 422  # schema gt=0 constraint violated

    def test_foreign_transaction_without_rate_is_rejected(self, client):
        acc = _checking(client)
        category_id = client.post(
            "/api/v1/categories",
            json={"name": "USD expense without exchange rate", "type": "expense"},
        ).json()["id"]
        resp = client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc,
                "category_id": category_id,
                "date": "2026-01-01",
                "amount": -100,
                "currency": "USD",
            },
        )
        assert resp.status_code == 400

    def test_foreign_income_event_without_rate_is_rejected(self, client):
        ref = _checking(client)
        acc = _investment(client, ref)
        sec = _security(client, "AAPL", "USD")
        resp = client.post(
            "/api/v1/income-events",
            json={
                "security_id": sec,
                "account_id": acc,
                "event_type": "dividend",
                "payment_date": "2026-05-01",
                "total_amount": 50,
                "currency": "USD",
            },
        )
        assert resp.status_code == 400

    def test_foreign_portfolio_cost_without_rate_is_rejected(self, client):
        ref = _checking(client)
        acc = _investment(client, ref)
        resp = client.post(
            "/api/v1/portfolio-costs",
            json={
                "date": "2026-01-01",
                "cost_type": "custody_fee",
                "account_id": acc,
                "amount": 10,
                "currency": "USD",
            },
        )
        assert resp.status_code == 400

    def test_accounts_are_eur_only(self, client):
        """An account balance sums already converted movements: a dollar account would mix a euro balance with a dollar opening amount."""
        resp = client.post(
            "/api/v1/accounts",
            json={"name": "USD account", "type": "checking", "currency": "USD"},
        )
        assert resp.status_code == 400
        assert "in EUR only" in resp.json()["message"]


# --------------------------------------------------------------------------
# 2. Conversion happens using the declared rate
# --------------------------------------------------------------------------
class TestConversionIsFrozenOnTheRecord:
    def test_trade_stores_both_native_and_eur(self, client):
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")

        body = _trade(client, sec, acc, currency="USD", fx_rate=USD_RATE).json()

        assert Decimal(body["total_amount"]) == 1000  # 10 x 100 USD
        assert Decimal(body["total_eur"]) == Decimal("920.00")
        assert Decimal(body["price_eur"]) == Decimal("92.00")

    def test_later_rate_changes_do_not_rewrite_history(self, client):
        """Cost basis is the historical cost: importing a different rate later must not change the past."""
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")
        _trade(client, sec, acc, currency="USD", fx_rate=USD_RATE)

        _import_fx(client, rate=0.50, date="2026-06-01")

        body = client.get("/api/v1/trades").json()[0]
        assert Decimal(body["total_eur"]) == Decimal("920.00")

    def test_foreign_trade_moves_cash_in_eur(self, client):
        """Previously, the operation was recorded without moving cash."""
        ref = _checking(client)
        acc = _investment(client, ref)
        sec = _security(client, "AAPL", "USD")

        _trade(client, sec, acc, currency="USD", fx_rate=USD_RATE)

        balance = client.get(f"/api/v1/accounts/{ref}/balance").json()
        assert Decimal(balance["balance"]) == Decimal("-920.00")
        assert balance["currency"] == "EUR"

    def test_foreign_transaction_counts_in_eur_in_the_balance(self, client):
        acc = _checking(client)
        category_id = client.post(
            "/api/v1/categories", json={"name": "USD expense", "type": "expense"}
        ).json()["id"]
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc,
                "category_id": category_id,
                "date": "2026-01-01",
                "amount": -100,
                "currency": "USD",
                "fx_rate": USD_RATE,
            },
        )
        balance = client.get(f"/api/v1/accounts/{acc}/balance").json()
        # -92 EUR, not -100: dollars are not euros
        assert Decimal(balance["balance"]) == Decimal("-92.00")

    def test_transfer_uses_one_rate_for_both_sides(self, client):
        """Different rates on each side would create an unexplained euro difference between outgoing and incoming amounts."""
        a, b = _checking(client, "A"), _checking(client, "B")
        body = client.post(
            "/api/v1/transactions/transfer",
            json={
                "from_account_id": a,
                "to_account_id": b,
                "date": "2026-01-01",
                "amount": 100,
                "currency": "USD",
                "fx_rate": USD_RATE,
            },
        ).json()

        out = Decimal(body["from_transaction"]["amount_eur"])
        into = Decimal(body["to_transaction"]["amount_eur"])
        assert out == -Decimal("92.00")
        assert into == Decimal("92.00")
        assert out + into == 0

    def test_income_event_converts_gross_and_withholding_together(self, client):
        ref = _checking(client)
        acc = _investment(client, ref)
        sec = _security(client, "AAPL", "USD")

        body = client.post(
            "/api/v1/income-events",
            json={
                "security_id": sec,
                "account_id": acc,
                "event_type": "dividend",
                "payment_date": "2026-05-01",
                "total_amount": 100,
                "currency": "USD",
                "tax_withheld": 15,
                "fx_rate": USD_RATE,
            },
        ).json()

        assert Decimal(body["total_eur"]) == Decimal("92.00")
        assert Decimal(body["net_amount_eur"]) == Decimal("78.20")  # (100-15) x 0.92

    def test_percentage_cost_inherits_the_trade_rate(self, client):
        """A 1% fee on a dollar trade is a fraction of that converted value: requiring a separate rate would make it inconsistent with its trade."""
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")
        trade = _trade(client, sec, acc, currency="USD", fx_rate=USD_RATE).json()

        cost = client.post(
            f"/api/v1/trades/{trade['id']}/costs",
            json={"cost_type": "commission", "percentage": 1},
        ).json()

        assert cost["currency"] == "USD"
        assert Decimal(cost["amount"]) == 10  # 1% of 1000 USD
        assert Decimal(cost["fx_rate"]) == Decimal(str(USD_RATE))
        assert Decimal(cost["amount_eur"]) == Decimal("9.20")

    def test_price_import_requires_the_rate_for_foreign_securities(self, client):
        _security(client, "AAPL", "USD")
        result = _import_prices(client, "2026-07-10;AAPL;110;\n").json()
        assert result["errors"] == 1
        assert result["imported"] == 0

    def test_price_import_accepts_the_rate_column(self, client):
        _security(client, "AAPL", "USD")
        result = _import_prices(client, f"2026-07-10;AAPL;110;{USD_RATE}\n").json()
        assert result["imported"] == 1

    def test_price_import_for_eur_securities_needs_no_rate_column(self, client):
        """Existing files must continue working unchanged."""
        _security(client, "ENI.MI", "EUR")
        csv_content = "date;ticker;close\n2026-07-10;ENI.MI;12\n"
        result = client.post(
            "/api/v1/prices/import",
            files={"file": ("p.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        ).json()
        assert result["imported"] == 1

    def test_price_preview_shows_which_rows_need_a_rate(self, client):
        _security(client, "AAPL", "USD")
        csv_content = "date;ticker;close\n2026-07-10;AAPL;110\n"
        body = client.post(
            "/api/v1/prices/import/preview",
            files={"file": ("p.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        ).json()
        row = body["rows"][0]
        assert row["currency"] == "USD"
        assert row["errors"]
        assert body["error_rows"] == 1

    def test_csv_transaction_import_requires_the_rate(self, client):
        acc = _checking(client)
        client.post("/api/v1/categories", json={"name": "Expense", "type": "expense"})
        csv_content = "date,description,amount,category\n2026-01-01,Expense,-10,Expense\n"
        resp = client.post(
            "/api/v1/transactions/import",
            files={"file": ("t.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            data={
                "account_id": str(acc),
                "default_currency": "USD",
                "category_column": "category",
            },
        )
        assert resp.status_code == 400


# --------------------------------------------------------------------------
# 3. Consistency across reports exposing the same data
# --------------------------------------------------------------------------
class TestReportsAgreeWithEachOther:
    @pytest.fixture
    def portfolio(self, client):
        """A mixed EUR/USD portfolio with a price for each security."""
        ref = _checking(client)
        acc = _investment(client, ref)
        eur = _security(client, "ENI.MI", "EUR")
        usd = _security(client, "AAPL", "USD")
        _trade(client, eur, acc, quantity=10, price=10, currency="EUR")
        _trade(client, usd, acc, quantity=10, price=100, currency="USD", fx_rate=USD_RATE)
        _import_prices(
            client,
            "2026-07-10;ENI.MI;12;\n" f"2026-07-10;AAPL;110;{USD_RATE}\n",
        )
        return {"ref": ref, "account": acc, "eur": eur, "usd": usd}

    def test_portfolio_summary_aggregates_in_eur(self, client, portfolio):
        body = client.get("/api/v1/portfolio/summary").json()
        # 10x10 EUR + 10x100x0.92 = 100 + 920
        assert Decimal(body["total_invested"]) == 1020
        # 10x12 EUR + 10x110x0.92 = 120 + 1012
        assert Decimal(body["total_current_value"]) == 1132

    def test_securities_analysis_matches_portfolio_summary(self, client, portfolio):
        """Regression: securities-analysis reconverted cost basis at TODAY'S rate and reported a different invested amount for the same portfolio."""
        summary = client.get("/api/v1/portfolio/summary").json()
        analysis = client.get("/api/v1/reports/securities-analysis").json()

        invested = sum(Decimal(str(i["total_invested"])) for i in analysis["top_by_value"])
        assert invested == Decimal(summary["total_invested"])
        assert Decimal(analysis["total_value"]) == Decimal(summary["total_current_value"])

    def test_performance_matches_portfolio_summary(self, client, portfolio):
        summary = client.get("/api/v1/portfolio/summary").json()
        perf = client.get("/api/v1/performance/portfolio").json()

        assert Decimal(perf["total_invested"]) == Decimal(summary["total_invested"])
        assert Decimal(perf["total_current_value"]) == Decimal(summary["total_current_value"])

    def test_foreign_position_is_not_valued_at_zero(self, client, portfolio):
        """Regression: without a runtime rate, the position counted fully toward invested capital but zero toward value, inventing a loss."""
        positions = {p["ticker"]: p for p in client.get("/api/v1/portfolio").json()}
        aapl = positions["AAPL"]

        assert Decimal(aapl["current_value_eur"]) == 1012
        assert Decimal(aapl["total_invested_eur"]) == 920
        assert Decimal(aapl["unrealized_gain_loss_eur"]) == 92

    def test_position_exposes_native_and_eur_side_by_side(self, client, portfolio):
        positions = {p["ticker"]: p for p in client.get("/api/v1/portfolio").json()}
        aapl = positions["AAPL"]

        assert aapl["currency"] == "USD"
        assert Decimal(aapl["current_price"]) == 110  # native
        assert Decimal(aapl["current_price_eur"]) == Decimal("101.20")
        assert Decimal(aapl["total_invested"]) == 1000  # native
        assert Decimal(aapl["total_invested_eur"]) == 920

    def test_fractional_market_price_is_multiplied_before_rounding(self, client):
        """A unit EUR price rounded to six decimals must not be multiplied back by a large quantity.

        A native price of 0.000003 USD at rate 0.5 is exactly 0.0000015 EUR.
        The informational six-decimal field holds 0.000002, which would
        yield 2 EUR instead of 1.5 EUR for one million units.
        """
        account = _investment(client, _checking(client))
        security = _security(client, "MICRO", "USD")
        trade = _trade(
            client,
            security,
            account,
            quantity=1_000_000,
            price="0.000003",
            currency="USD",
            fx_rate="0.5",
        )
        assert trade.status_code == 201, trade.text

        imported = _import_prices(client, "2026-01-02;MICRO;0.000003;0.5\n")
        assert imported.status_code == 200, imported.text
        stored_price = client.get(f"/api/v1/prices/{security}").json()[0]
        assert Decimal(stored_price["price_close_eur"]) == Decimal("0.000002")

        position = client.get(f"/api/v1/portfolio/{security}").json()
        assert Decimal(position["current_price_eur"]) == Decimal("0.0000015")
        assert Decimal(position["current_value_eur"]) == Decimal("1.5")
        assert Decimal(position["unrealized_gain_loss_eur"]) == 0

        summary = client.get("/api/v1/portfolio/summary").json()
        assert Decimal(summary["total_current_value"]) == Decimal("1.5")
        assert Decimal(summary["total_unrealized_gain_loss"]) == 0

        security_performance = client.get(f"/api/v1/performance/{security}").json()
        assert Decimal(security_performance["simple_return"]) == 0
        assert Decimal(security_performance["total_return"]) == 0

        portfolio_performance = client.get("/api/v1/performance/portfolio").json()
        assert Decimal(portfolio_performance["total_current_value"]) == Decimal("1.5")
        assert Decimal(portfolio_performance["total_return"]) == 0

        valuation_date = dt.date(2026, 1, 2)
        db = TestingSessionLocal()
        try:
            series = PerformanceService(db).portfolio_value_series(
                [valuation_date], include_same_day_trades=True
            )
        finally:
            db.close()
        assert series[valuation_date] == Decimal("1.5")

    def test_withholding_is_converted_once_and_consistently(self, client, portfolio):
        """Regression: withholding was summed in native currency in one place and converted elsewhere. One calculation now ensures the cost entry matches the fiscal-position total."""
        client.post(
            "/api/v1/income-events",
            json={
                "security_id": portfolio["usd"],
                "account_id": portfolio["account"],
                "event_type": "dividend",
                "payment_date": "2026-05-01",
                "total_amount": 100,
                "currency": "USD",
                "tax_withheld": 15,
                "fx_rate": USD_RATE,
            },
        )

        costs = client.get("/api/v1/reports/costs-analysis").json()
        withholding_in_costs = sum(
            Decimal(str(i["amount_eur"]))
            for g in costs["groups"]
            for i in g["items"]
            if i["cost_type"] == "withholding_tax"
        )

        assert Decimal(costs["fiscal"]["dividend_withholding"]) == Decimal("13.80")  # 15 x 0.92
        assert withholding_in_costs == Decimal(costs["fiscal"]["dividend_withholding"])

    def test_realized_loss_is_converted_to_eur(self, client):
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")
        _trade(client, sec, acc, quantity=10, price=200, currency="USD", fx_rate=USD_RATE)
        _trade(
            client,
            sec,
            acc,
            type="sell",
            date="2026-06-01",
            quantity=10,
            price=150,
            currency="USD",
            fx_rate=USD_RATE,
        )

        body = client.get("/api/v1/reports/costs-analysis").json()
        # -500 USD x 0.92 = -460 EUR
        assert Decimal(body["fiscal"]["capital_losses"]) == -460

    def test_net_worth_and_income_statement_are_in_eur(self, client):
        acc = _checking(client)
        category_id = client.post(
            "/api/v1/categories", json={"name": "USD income", "type": "income"}
        ).json()["id"]
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": acc,
                "category_id": category_id,
                "date": "2026-01-01",
                "amount": 1000,
                "currency": "USD",
                "fx_rate": USD_RATE,
            },
        )

        net_worth = client.get("/api/v1/reports/net-worth").json()
        statement = client.get("/api/v1/reports/income-statement").json()

        assert Decimal(net_worth["total_accounts_balance"]) == 920
        assert Decimal(statement["total_income"]) == 920


# --------------------------------------------------------------------------
# 4. Rate archive: an aid, not a dependency
# --------------------------------------------------------------------------
class TestRateArchiveIsOnlyASuggestion:
    def test_suggest_returns_the_latest_archived_rate(self, client):
        _import_fx(client, rate=0.90, date="2026-01-01")
        _import_fx(client, rate=0.95, date="2026-03-01")

        body = client.get(
            "/api/v1/fx-rates/suggest", params={"currency": "USD", "date": "2026-06-01"}
        ).json()

        assert Decimal(body["rate"]) == Decimal("0.95")
        assert body["rate_date"] == "2026-03-01"

    def test_suggest_ignores_rates_after_the_requested_date(self, client):
        _import_fx(client, rate=0.90, date="2026-01-01")
        _import_fx(client, rate=0.50, date="2026-12-01")

        body = client.get(
            "/api/v1/fx-rates/suggest", params={"currency": "USD", "date": "2026-06-01"}
        ).json()

        assert Decimal(body["rate"]) == Decimal("0.90")

    def test_suggest_returns_null_when_nothing_is_archived(self, client):
        """No suggestion is not an error: fill in the field manually."""
        body = client.get(
            "/api/v1/fx-rates/suggest", params={"currency": "GBP", "date": "2026-06-01"}
        ).json()
        assert body["rate"] is None

    def test_suggest_for_eur_is_always_one(self, client):
        body = client.get(
            "/api/v1/fx-rates/suggest", params={"currency": "EUR", "date": "2026-06-01"}
        ).json()
        assert Decimal(body["rate"]) == 1

    def test_an_archived_rate_does_not_make_the_field_optional(self, client):
        """Even with a populated archive, declare the exchange rate: this distinguishes conversion at entry from the old runtime lookup."""
        _import_fx(client, rate=USD_RATE)
        acc = _investment(client, _checking(client))
        sec = _security(client, "AAPL", "USD")

        assert _trade(client, sec, acc, currency="USD").status_code == 400
