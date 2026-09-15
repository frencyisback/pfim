"""Separate native quote, automatic price ownership, and FIFO fallback."""

from decimal import Decimal

from sqlalchemy import delete

from app.models.price import Price

from .conftest import TestingSessionLocal


def _account(client) -> int:
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Quote cash", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    return client.post(
        "/api/v1/accounts",
        json={
            "name": "Quote investment account",
            "type": "investment",
            "reference_account_id": cash,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]


def _security(client, *, ticker: str = "QUOTE", currency: str = "USD") -> int:
    return client.post(
        "/api/v1/securities",
        json={
            "ticker": ticker,
            "name": ticker,
            "type": "stock",
            "currency": currency,
        },
    ).json()["id"]


def _trade(client, security_id: int, account_id: int, **overrides):
    payload = {
        "security_id": security_id,
        "account_id": account_id,
        "type": "buy",
        "date": "2026-01-10",
        "quantity": "10",
        "price": "90",
        "quote_price": "100",
        "currency": "EUR",
    }
    payload.update(overrides)
    return client.post("/api/v1/trades", json=payload)


def test_cross_currency_trade_requires_and_uses_quote_price(client):
    security_id = _security(client)
    account_id = _account(client)

    missing = _trade(client, security_id, account_id, quote_price=None)
    assert missing.status_code == 400
    assert missing.json()["error_code"] == "VALIDATION_ERROR"

    response = _trade(client, security_id, account_id)
    assert response.status_code == 201
    trade = response.json()
    assert Decimal(trade["price"]) == Decimal("90")
    assert Decimal(trade["quote_price"]) == Decimal("100")
    assert Decimal(trade["price_eur"]) == Decimal("90")

    price = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(price["price_close"]) == Decimal("100")
    assert Decimal(price["price_close_eur"]) == Decimal("90")
    assert Decimal(price["fx_rate"]) == Decimal("0.9")
    assert price["origin_trade_id"] == trade["id"]

    position = client.get(f"/api/v1/portfolio/{security_id}").json()
    assert Decimal(position["average_cost"]) == Decimal("100")
    assert Decimal(position["total_invested"]) == Decimal("1000")
    assert Decimal(position["average_cost_eur"]) == Decimal("90")
    assert Decimal(position["total_invested_eur"]) == Decimal("900")


def test_eur_quoted_trade_settled_abroad_requires_consistent_conversion(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)

    inconsistent = _trade(
        client,
        security_id,
        account_id,
        price="100",
        currency="USD",
        fx_rate="0.9",
        quote_price="91",
    )
    assert inconsistent.status_code == 400

    accepted = _trade(
        client,
        security_id,
        account_id,
        price="100",
        currency="USD",
        fx_rate="0.9",
        quote_price="90",
    )
    assert accepted.status_code == 201
    price = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(price["price_close"]) == Decimal("90")
    assert Decimal(price["price_close_eur"]) == Decimal("90")
    assert Decimal(price["fx_rate"]) == Decimal("1")


def test_same_currency_canonicalizes_omitted_quote_price_and_rejects_mismatch(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)

    mismatch = _trade(
        client,
        security_id,
        account_id,
        price="10",
        quote_price="11",
    )
    assert mismatch.status_code == 400

    accepted = _trade(
        client,
        security_id,
        account_id,
        price="10",
        quote_price=None,
    )
    assert accepted.status_code == 201
    assert Decimal(accepted.json()["quote_price"]) == Decimal("10")


def test_same_foreign_currency_price_keeps_the_trade_fx_rate(client):
    security_id = _security(client, currency="USD")
    account_id = _account(client)

    response = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="3",
        quote_price=None,
        currency="USD",
        fx_rate="0.123456789",
    )

    assert response.status_code == 201, response.text
    trade = response.json()
    price = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(trade["fx_rate"]) == Decimal("0.12345679")
    assert Decimal(trade["price_eur"]) == Decimal("0.370370")
    assert Decimal(price["fx_rate"]) == Decimal("0.12345679")
    assert Decimal(price["price_close_eur"]) == Decimal("0.370370")


def test_implicit_quote_fx_is_validated_even_when_a_price_already_exists(client):
    security_id = _security(client, currency="USD")
    account_id = _account(client)
    manual = client.post(
        "/api/v1/prices",
        json={
            "security_id": security_id,
            "date": "2026-01-10",
            "price_close": "10",
            "fx_rate": "0.9",
        },
    )
    assert manual.status_code == 201

    # 0.000001 EUR / 999999999 USD yields an implicit rate
    # below the NUMERIC(18, 8) minimum. Previously a manual price
    # caused this check in _record_trade_price to be skipped.
    rejected = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="0.000001",
        quote_price="999999999",
        currency="EUR",
    )
    assert rejected.status_code == 400
    assert rejected.json()["error_code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/trades").json() == []
    assert client.get(f"/api/v1/prices/{security_id}").json() == [manual.json()]


def test_trade_rejects_derived_values_outside_numeric_18_6(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)

    overflow = _trade(
        client,
        security_id,
        account_id,
        quantity="999999999",
        price="2",
        quote_price=None,
    )
    assert overflow.status_code == 400
    assert overflow.json()["detail"]["field"] == "total_amount"

    underflow = _trade(
        client,
        security_id,
        account_id,
        quantity="0.000001",
        price="0.000001",
        quote_price=None,
    )
    assert underflow.status_code == 400
    assert underflow.json()["detail"]["field"] == "total_amount"

    unrepresentable_quantity = _trade(
        client,
        account_id=account_id,
        security_id=security_id,
        quantity="0.0000001",
        price="1",
        quote_price=None,
    )
    assert unrepresentable_quantity.status_code == 422
    assert client.get("/api/v1/trades").json() == []


def test_trade_persists_the_values_used_by_its_derived_fields(client):
    security_id = _security(client, currency="GBP")
    account_id = _account(client)

    response = _trade(
        client,
        security_id,
        account_id,
        quantity="1.0000005",
        price="100.0000005",
        quote_price="123.4567895",
        currency="USD",
        fx_rate="0.123456789",
    )

    assert response.status_code == 201, response.text
    trade_id = response.json()["id"]
    trade = next(row for row in client.get("/api/v1/trades").json() if row["id"] == trade_id)
    assert Decimal(trade["quantity"]) == Decimal("1.000000")
    assert Decimal(trade["price"]) == Decimal("100.000000")
    assert Decimal(trade["quote_price"]) == Decimal("123.456790")
    assert Decimal(trade["fx_rate"]) == Decimal("0.12345679")
    assert Decimal(trade["price_eur"]) == Decimal("12.345679")
    assert Decimal(trade["total_amount"]) == Decimal("100.000000")
    assert Decimal(trade["total_eur"]) == Decimal("12.345679")
    price = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(price["price_close"]) == Decimal("123.456790")
    assert Decimal(price["fx_rate"]) == Decimal("0.10000000")
    assert Decimal(price["price_close_eur"]) == Decimal("12.345679")


def test_trade_cost_cannot_overflow_the_linked_cash_movement(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="999999999",
        quote_price=None,
    )
    assert trade.status_code == 201

    rejected = client.post(
        f"/api/v1/trades/{trade.json()['id']}/costs",
        json={"cost_type": "commission", "amount": "1", "currency": "EUR"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["field"] == "amount_eur"
    assert client.get(f"/api/v1/trades/{trade.json()['id']}/costs").json() == []

    cash_movements = client.get("/api/v1/transactions").json()["items"]
    assert len(cash_movements) == 1
    assert Decimal(cash_movements[0]["amount_eur"]) == Decimal("-999999999")


def test_trade_cost_uses_its_normalized_native_amount(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="10",
        quote_price=None,
    ).json()

    response = client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "amount": "1.0000005", "currency": "EUR"},
    )

    assert response.status_code == 201, response.text
    assert Decimal(response.json()["amount"]) == Decimal("1.000000")
    assert Decimal(response.json()["amount_eur"]) == Decimal("1.000000")


def test_trade_cost_percentage_is_normalized_before_deriving_the_amount(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="10",
        price="10",
        quote_price=None,
    ).json()

    response = client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "percentage": "0.123456"},
    )

    assert response.status_code == 201, response.text
    cost = response.json()
    assert Decimal(cost["percentage_used"]) == Decimal("0.1235")
    assert Decimal(cost["amount"]) == Decimal("0.123500")
    assert Decimal(cost["amount_eur"]) == Decimal("0.123500")


def test_trade_cost_rejects_a_percentage_that_disappears_at_declared_scale(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="10",
        price="10",
        quote_price=None,
    ).json()
    before_cash = client.get("/api/v1/transactions").json()["items"]

    response = client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "percentage": "0.00005"},
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/v1/trades/{trade['id']}/costs").json() == []
    assert client.get("/api/v1/transactions").json()["items"] == before_cash


def test_deleting_trade_reassigns_or_removes_only_its_owned_price(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    first = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="10",
        quote_price=None,
    ).json()
    second = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="12",
        quote_price=None,
    ).json()

    initial = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(initial["price_close"]) == Decimal("10")
    assert initial["origin_trade_id"] == first["id"]

    assert client.delete(f"/api/v1/trades/{second['id']}").status_code == 204
    unchanged = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert unchanged["origin_trade_id"] == first["id"]

    replacement = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="13",
        quote_price=None,
    ).json()
    assert client.delete(f"/api/v1/trades/{first['id']}").status_code == 204
    reassigned = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(reassigned["price_close"]) == Decimal("13")
    assert reassigned["origin_trade_id"] == replacement["id"]

    assert client.delete(f"/api/v1/trades/{replacement['id']}").status_code == 204
    assert client.get(f"/api/v1/prices/{security_id}").json() == []


def test_manual_price_detaches_from_trade_and_survives_its_deletion(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="1",
        price="10",
        quote_price=None,
    ).json()

    manual = client.post(
        "/api/v1/prices",
        json={
            "security_id": security_id,
            "date": "2026-01-10",
            "price_close": "15",
        },
    )
    assert manual.status_code == 201
    assert manual.json()["source"] == "manual"
    assert manual.json()["origin_trade_id"] is None

    assert client.delete(f"/api/v1/trades/{trade['id']}").status_code == 204
    remaining = client.get(f"/api/v1/prices/{security_id}").json()
    assert len(remaining) == 1
    assert remaining[0]["source"] == "manual"


def test_unpriced_open_position_uses_declared_fifo_fallback_everywhere(client):
    security_id = _security(client, currency="EUR")
    account_id = _account(client)
    trade = _trade(
        client,
        security_id,
        account_id,
        quantity="2",
        price="50",
        quote_price=None,
    ).json()

    with TestingSessionLocal.begin() as db:
        db.execute(delete(Price).where(Price.origin_trade_id == trade["id"]))

    position = client.get(f"/api/v1/portfolio/{security_id}").json()
    assert position["current_price"] is None
    assert position["current_price_eur"] is None
    assert position["current_price_date"] is None
    assert Decimal(position["current_value"]) == Decimal("100")
    assert Decimal(position["current_value_eur"]) == Decimal("100")
    assert Decimal(position["unrealized_gain_loss_eur"]) == 0
    assert position["valuation_source"] == "fifo_cost"

    summary = client.get("/api/v1/portfolio/summary").json()
    assert Decimal(summary["total_current_value"]) == Decimal("100")
    assert Decimal(summary["total_unrealized_gain_loss"]) == 0
    assert summary["portfolio_valuation"]["cost_fallback_used"] is True
    assert (
        summary["portfolio_valuation"]["cost_fallback_securities"][0]["security_id"] == security_id
    )

    report = client.get("/api/v1/reports/securities-analysis").json()
    assert report["positions_count"] == 1
    assert report["positions"][0]["security_id"] == security_id
    assert report["positions"][0]["valuation_source"] == "fifo_cost"
    assert report["portfolio_valuation"]["cost_fallback_used"] is True

    performance = client.get("/api/v1/performance/portfolio").json()
    assert Decimal(performance["total_current_value"]) == Decimal("100")
    assert Decimal(performance["total_return"]) == 0
    assert performance["portfolio_valuation"]["cost_fallback_used"] is True
