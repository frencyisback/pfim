"""Per-account holdings with unchanged global FIFO, using in-memory SQLite."""

import datetime as dt
from decimal import Decimal

import pytest

from app.models.trade import Trade
from tests.integration.conftest import TestingSessionLocal


def _post(client, path, payload):
    response = client.post(f"/api/v1/{path}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def portfolio(client):
    cash = _post(
        client,
        "accounts",
        {"name": "Shared cash", "type": "checking", "opened_on": "2000-01-01"},
    )
    accounts = [
        _post(
            client,
            "accounts",
            {
                "name": name,
                "type": "investment",
                "reference_account_id": cash["id"],
                "opened_on": "2000-01-01",
            },
        )["id"]
        for name in ("Investment account A", "Investment account B")
    ]
    security = _post(
        client,
        "securities",
        {"ticker": "PAIR", "name": "Shared security", "type": "stock", "currency": "EUR"},
    )
    return security["id"], *accounts


def _trade(client, security_id, account_id, type_, date, quantity="1", price="100"):
    return client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": account_id,
            "type": type_,
            "date": date,
            "quantity": quantity,
            "price": price,
            "currency": "EUR",
        },
    )


def _accepted_trade(*args, **kwargs):
    response = _trade(*args, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def _snapshot(client, security_id):
    """Include all composite writes, including costs and the cash account."""
    paths = ("trades", "transactions", "tax-events", f"prices/{security_id}", "accounts")
    result = {}
    for path in paths:
        response = client.get(f"/api/v1/{path}")
        assert response.status_code == 200, response.text
        result[path] = response.json()
    for trade in result["trades"]:
        response = client.get(f"/api/v1/trades/{trade['id']}/costs")
        assert response.status_code == 200, response.text
        result[f"costs/{trade['id']}"] = response.json()
    return result


def _conflict(response, account_id, security_id, date, requested, available, trade_id=None):
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error_code"] == "CONFLICT"
    detail = body["detail"]
    assert detail["account_id"] == account_id
    assert detail["security_id"] == security_id
    assert detail["date"] == date
    assert Decimal(detail["requested_quantity"]) == Decimal(requested)
    assert Decimal(detail["available_quantity"]) == Decimal(available)
    assert detail["first_invalid_trade_id"] == trade_id
    assert detail["first_invalid_is_candidate"] is (trade_id is None)


def test_other_dossier_purchase_cannot_fund_sale_and_rejection_is_atomic(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01", quantity="10")
    before = _snapshot(client, security)

    response = _trade(client, security, account_b, "sell", "2026-01-02", price="120")

    _conflict(response, account_b, security, "2026-01-02", "1", "0")
    assert _snapshot(client, security) == before


def test_other_dossier_purchase_cannot_cover_deleted_buy_and_keeps_all_links(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01", quantity="10")
    buy = _accepted_trade(client, security, account_b, "buy", "2026-01-02")
    _post(client, f"trades/{buy['id']}/costs", {"cost_type": "commission", "amount": "2"})
    sell = _accepted_trade(client, security, account_b, "sell", "2026-01-03", price="120")
    before = _snapshot(client, security)

    response = client.delete(f"/api/v1/trades/{buy['id']}")

    _conflict(response, account_b, security, "2026-01-03", "1", "0", sell["id"])
    assert _snapshot(client, security) == before


def test_same_day_purchase_precedes_new_sale_and_fractional_quantities_are_exact(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01")
    _accepted_trade(client, security, account_b, "buy", "2026-01-02", quantity="0.1")
    _accepted_trade(client, security, account_b, "buy", "2026-01-02", quantity="0.2")
    _accepted_trade(client, security, account_b, "sell", "2026-01-02", quantity="0.299999")
    _accepted_trade(client, security, account_b, "sell", "2026-01-02", quantity="0.000001")

    response = _trade(client, security, account_b, "sell", "2026-01-02", quantity="0.000001")

    _conflict(response, account_b, security, "2026-01-02", "0.000001", "0")


def test_later_same_day_buy_cannot_replace_buy_preceding_an_existing_sale(client, portfolio):
    security, _, account_b = portfolio
    first = _accepted_trade(client, security, account_b, "buy", "2026-01-02")
    sell = _accepted_trade(client, security, account_b, "sell", "2026-01-02")
    _accepted_trade(client, security, account_b, "buy", "2026-01-02")

    response = client.delete(f"/api/v1/trades/{first['id']}")

    _conflict(response, account_b, security, "2026-01-02", "1", "0", sell["id"])


def test_backdated_sale_is_checked_against_future_sales_in_the_same_dossier(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01", quantity="10")
    _accepted_trade(client, security, account_b, "buy", "2026-01-01", quantity="2")
    future_date = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    future_sell = _accepted_trade(client, security, account_b, "sell", future_date, quantity="2")
    before = _snapshot(client, security)

    response = _trade(client, security, account_b, "sell", "2026-02-01")

    _conflict(response, account_b, security, future_date, "2", "1", future_sell["id"])
    assert _snapshot(client, security) == before


def test_future_purchase_cannot_cover_an_earlier_sale(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01")
    future_date = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    _accepted_trade(client, security, account_b, "buy", future_date)

    response = _trade(client, security, account_b, "sell", "2026-02-01")

    _conflict(response, account_b, security, "2026-02-01", "1", "0")


def test_valid_accounts_keep_global_fifo_cost_and_fiscal_result(client, portfolio):
    security, account_a, account_b = portfolio
    _accepted_trade(client, security, account_a, "buy", "2026-01-01", price="10")
    _accepted_trade(client, security, account_b, "buy", "2026-01-02", price="100")
    sell = _accepted_trade(client, security, account_b, "sell", "2026-01-03", price="150")

    position = client.get(f"/api/v1/portfolio/{security}").json()
    assert Decimal(position["quantity"]) == 1
    assert Decimal(position["average_cost"]) == 100
    assert Decimal(position["realized_gain_loss"]) == 140
    events = client.get("/api/v1/tax-events").json()
    automatic = [e for e in events if e["related_trade_id"] == sell["id"]]
    assert len(automatic) == 1
    assert automatic[0]["origin"] == "automatic_trade"
    assert Decimal(automatic[0]["gross_amount"]) == 140
    assert client.post(f"/api/v1/accounts/{account_b}/deactivate").status_code == 200


def _legacy_dossier_trades(client, security, account_a, account_b):
    """Set up the case accepted by old code only in the synthetic database."""
    _accepted_trade(client, security, account_a, "buy", "2026-01-01", quantity="10")
    sells = [
        _accepted_trade(client, security, account_a, "sell", date, quantity="2")
        for date in ("2026-01-02", "2026-01-03")
    ]
    with TestingSessionLocal() as db:
        assert db.get_bind().url.database == ":memory:"
        for sell in sells:
            db.get(Trade, sell["id"]).account_id = account_b
        db.commit()
    return sells


def test_legacy_deficit_stays_readable_and_nonworsening_writes_remain_available(client, portfolio):
    security, account_a, account_b = portfolio
    sells = _legacy_dossier_trades(client, security, account_a, account_b)
    assert client.get("/api/v1/trades").status_code == 200
    assert client.get(f"/api/v1/portfolio/{security}").status_code == 200

    # A deficit remains, but adding units or removing a sale reduces it.
    _accepted_trade(client, security, account_b, "buy", "2026-02-01")
    assert client.delete(f"/api/v1/trades/{sells[0]['id']}").status_code == 204
    assert client.get(f"/api/v1/portfolio/{security}").status_code == 200
    # Account A is valid: B's deficit does not block other pairs.
    _accepted_trade(client, security, account_a, "sell", "2026-02-02")
    response = _trade(client, security, account_b, "sell", "2026-02-02")
    _conflict(response, account_b, security, "2026-01-03", "2", "0", sells[1]["id"])


def test_legacy_deficit_blocks_new_sale_and_buy_deletion_without_automatic_repairs(
    client, portfolio
):
    security, account_a, account_b = portfolio
    sells = _legacy_dossier_trades(client, security, account_a, account_b)
    buy = _accepted_trade(client, security, account_b, "buy", "2026-02-01", quantity="10")
    before = _snapshot(client, security)

    sale_response = _trade(client, security, account_b, "sell", "2026-03-01")
    _conflict(sale_response, account_b, security, "2026-01-02", "2", "0", sells[0]["id"])
    delete_response = client.delete(f"/api/v1/trades/{buy['id']}")
    _conflict(delete_response, account_b, security, "2026-01-02", "2", "0", sells[0]["id"])
    assert _snapshot(client, security) == before


def test_nonworsening_delete_keeps_existing_fiscal_source_guard(client, portfolio):
    security, account_a, account_b = portfolio
    sells = _legacy_dossier_trades(client, security, account_a, account_b)
    _post(
        client,
        "tax-events",
        {
            "event_date": "2026-01-02",
            "event_type": "other",
            "description": "Manual tax annotation",
            "related_trade_id": sells[0]["id"],
        },
    )
    before = _snapshot(client, security)

    response = client.delete(f"/api/v1/trades/{sells[0]['id']}")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["trade_id"] == sells[0]["id"]
    assert _snapshot(client, security) == before
