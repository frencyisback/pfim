"""Regression tests for account lifecycle and related movements.

These tests use only the in-memory SQLite database configured in
``tests/integration/conftest.py``.
"""

import datetime as dt

import pytest


def _create_cash_account(
    client,
    name: str,
    *,
    opening_balance: float = 0,
    opened_on: dt.date | None = dt.date(2000, 1, 1),
):
    payload = {
        "name": name,
        "type": "checking",
        "opening_balance": opening_balance,
    }
    if opened_on is not None:
        payload["opened_on"] = opened_on.isoformat()
    response = client.post(
        "/api/v1/accounts",
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def _create_investment_account(
    client,
    name: str,
    reference_account_id: int,
    *,
    opened_on: dt.date = dt.date(2000, 1, 1),
):
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": name,
            "type": "investment",
            "reference_account_id": reference_account_id,
            "opened_on": opened_on.isoformat(),
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_security(client, ticker: str = "LIFE.MI"):
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": ticker,
            "name": f"Security {ticker}",
            "type": "stock",
            "currency": "EUR",
        },
    )
    assert response.status_code == 201
    return response.json()


def _create_trade(client, *, security_id: int, account_id: int, date: str, price: float = 10):
    response = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": account_id,
            "type": "buy",
            "date": date,
            "quantity": 10,
            "price": price,
            "currency": "EUR",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_investment_opening_balance_must_remain_zero_on_create_and_partial_update(client):
    cash = _create_cash_account(client, "Cash")

    invalid_create = client.post(
        "/api/v1/accounts",
        json={
            "name": "Invalid investment account",
            "type": "investment",
            "reference_account_id": cash["id"],
            "opening_balance": 100,
        },
    )
    assert invalid_create.status_code == 422

    investment = _create_investment_account(client, "Investment account", cash["id"])
    invalid_update = client.put(
        f"/api/v1/accounts/{investment['id']}",
        json={"opening_balance": 1},
    )
    assert invalid_update.status_code == 400
    assert invalid_update.json()["error_code"] == "VALIDATION_ERROR"

    persisted = next(
        account
        for account in client.get("/api/v1/accounts").json()
        if account["id"] == investment["id"]
    )
    assert float(persisted["opening_balance"]) == 0


def test_inactive_account_cannot_be_created_or_selected_as_reference(client):
    inactive_reference = _create_cash_account(client, "Archived cash")
    assert client.post(f"/api/v1/accounts/{inactive_reference['id']}/deactivate").status_code == 200

    invalid_create = client.post(
        "/api/v1/accounts",
        json={
            "name": "New investment account",
            "type": "investment",
            "reference_account_id": inactive_reference["id"],
        },
    )
    assert invalid_create.status_code == 409
    assert invalid_create.json()["error_code"] == "CONFLICT"

    active_reference = _create_cash_account(client, "Active cash")
    investment = _create_investment_account(
        client, "Existing investment account", active_reference["id"]
    )
    invalid_update = client.put(
        f"/api/v1/accounts/{investment['id']}",
        json={"reference_account_id": inactive_reference["id"]},
    )
    assert invalid_update.status_code == 409
    assert invalid_update.json()["error_code"] == "CONFLICT"


def test_reference_deactivation_is_blocked_while_an_active_dossier_uses_it(client):
    cash = _create_cash_account(client, "Cash")
    _create_investment_account(client, "Investment account", cash["id"])

    via_action = client.post(f"/api/v1/accounts/{cash['id']}/deactivate")
    assert via_action.status_code == 409
    assert via_action.json()["detail"]["active_dependent_accounts_count"] == 1

    via_update = client.put(f"/api/v1/accounts/{cash['id']}", json={"is_active": False})
    assert via_update.status_code == 409
    assert via_update.json()["detail"]["active_dependent_accounts_count"] == 1

    persisted = next(
        account for account in client.get("/api/v1/accounts").json() if account["id"] == cash["id"]
    )
    assert persisted["is_active"] is True


def test_deactivation_requires_zero_balance_and_uses_put_projected_opening_balance(client):
    nonzero = _create_cash_account(client, "Balance to clear", opening_balance=100)

    blocked = client.post(f"/api/v1/accounts/{nonzero['id']}/deactivate")
    assert blocked.status_code == 409
    assert float(blocked.json()["detail"]["current_balance"]) == 100

    # The opening balance of an empty account can be corrected; the same PUT
    # must assess the resulting balance, rather than the pre-update value.
    projected_zero = client.put(
        f"/api/v1/accounts/{nonzero['id']}",
        json={"opening_balance": 0, "is_active": False},
    )
    assert projected_zero.status_code == 200
    assert projected_zero.json()["is_active"] is False

    balanced = _create_cash_account(client, "Closed history", opening_balance=100)
    expense = client.post(
        "/api/v1/categories",
        json={"name": "Lifecycle reset", "type": "expense"},
    ).json()
    movement = client.post(
        "/api/v1/transactions",
        json={
            "account_id": balanced["id"],
            "category_id": expense["id"],
            "date": (dt.date.today() - dt.timedelta(days=1)).isoformat(),
            "amount": -100,
        },
    )
    assert movement.status_code == 201

    # History remains readable, but with a zero balance it does not make the account
    # operationally open.
    assert client.post(f"/api/v1/accounts/{balanced['id']}/deactivate").status_code == 200


def test_deactivation_blocks_open_positions_and_future_trades_but_not_closed_history(client):
    today = dt.date.today()
    cash = _create_cash_account(client, "Position cash")
    investment = _create_investment_account(client, "Position investment account", cash["id"])
    security = _create_security(client, "OPEN.MI")
    _create_trade(
        client,
        security_id=security["id"],
        account_id=investment["id"],
        date=(today - dt.timedelta(days=2)).isoformat(),
    )

    open_position = client.post(f"/api/v1/accounts/{investment['id']}/deactivate")
    assert open_position.status_code == 409
    assert open_position.json()["detail"]["open_positions_count"] == 1

    close_position = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "sell",
            "date": (today - dt.timedelta(days=1)).isoformat(),
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    assert close_position.status_code == 201
    assert client.post(f"/api/v1/accounts/{investment['id']}/deactivate").status_code == 200

    future_cash = _create_cash_account(client, "Future cash")
    future_investment = _create_investment_account(
        client,
        "Future investment account",
        future_cash["id"],
    )
    future_security = _create_security(client, "FUTURE.MI")
    _create_trade(
        client,
        security_id=future_security["id"],
        account_id=future_investment["id"],
        date=(today + dt.timedelta(days=30)).isoformat(),
    )

    future_trade = client.post(f"/api/v1/accounts/{future_investment['id']}/deactivate")
    assert future_trade.status_code == 409
    assert future_trade.json()["detail"]["open_positions_count"] == 0
    assert future_trade.json()["detail"]["future_trades_count"] == 1


def test_deactivation_blocks_future_transactions_and_future_source_events(client):
    today = dt.date.today()
    future = (today + dt.timedelta(days=30)).isoformat()

    cash_with_future_tx = _create_cash_account(client, "Cash with future movement")
    income_category = client.post(
        "/api/v1/categories",
        json={"name": "Future lifecycle income", "type": "income"},
    ).json()
    assert (
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": cash_with_future_tx["id"],
                "category_id": income_category["id"],
                "date": future,
                "amount": 10,
            },
        ).status_code
        == 201
    )
    blocked_cash = client.post(f"/api/v1/accounts/{cash_with_future_tx['id']}/deactivate")
    assert blocked_cash.status_code == 409
    assert blocked_cash.json()["detail"]["current_balance"] == "0.000000"
    assert blocked_cash.json()["detail"]["future_transactions_count"] == 1

    cash = _create_cash_account(client, "Future-source cash")
    investment = _create_investment_account(client, "Future-source investment account", cash["id"])
    security = _create_security(client, "SOURCE-FUTURE.MI")

    # Zero net income creates no Transaction, so the guard must also inspect
    # the source instead of relying only on cash movements.
    income = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "event_type": "dividend",
            "payment_date": future,
            "total_amount": 10,
            "tax_withheld": 10,
            "currency": "EUR",
        },
    )
    assert income.status_code == 201
    cost = client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": future,
            "cost_type": "custody_fee",
            "account_id": investment["id"],
            "amount": 5,
        },
    )
    assert cost.status_code == 201

    blocked_investment = client.post(f"/api/v1/accounts/{investment['id']}/deactivate")
    assert blocked_investment.status_code == 409
    detail = blocked_investment.json()["detail"]
    assert detail["future_income_events_count"] == 1
    assert detail["future_portfolio_costs_count"] == 1


@pytest.mark.parametrize(
    "field",
    ["name", "type", "currency", "opening_balance", "is_active"],
)
def test_account_update_rejects_explicit_null_for_non_nullable_columns(client, field):
    account = _create_cash_account(client, f"Null {field}")

    response = client.put(f"/api/v1/accounts/{account['id']}", json={field: None})

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_type_and_opening_balance_are_mutable_only_before_financial_history(client):
    category = client.post(
        "/api/v1/categories",
        json={"name": "Identity history", "type": "income"},
    ).json()
    used = _create_cash_account(client, "Used account")
    assert (
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": used["id"],
                "category_id": category["id"],
                "date": (dt.date.today() - dt.timedelta(days=1)).isoformat(),
                "amount": 1,
            },
        ).status_code
        == 201
    )

    for payload, changed_field in (
        ({"type": "savings"}, "type"),
        ({"opening_balance": 10}, "opening_balance"),
    ):
        response = client.put(f"/api/v1/accounts/{used['id']}", json=payload)
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["changed_fields"] == [changed_field]
        assert detail["transactions_count"] == 1

    empty = _create_cash_account(client, "Still-empty account", opening_balance=10)
    allowed = client.put(
        f"/api/v1/accounts/{empty['id']}",
        json={"type": "savings", "opening_balance": 0},
    )
    assert allowed.status_code == 200
    assert allowed.json()["type"] == "savings"
    assert float(allowed.json()["opening_balance"]) == 0


def test_noninvestment_reference_is_rejected_instead_of_silently_discarded(client):
    reference = _create_cash_account(client, "Invalid reference")
    checking = _create_cash_account(client, "Ordinary account")

    invalid = client.put(
        f"/api/v1/accounts/{checking['id']}",
        json={"reference_account_id": reference["id"]},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "VALIDATION_ERROR"

    investment = _create_investment_account(
        client, "Still-empty investment account", reference["id"]
    )
    changed_type = client.put(
        f"/api/v1/accounts/{investment['id']}",
        json={"type": "checking"},
    )
    assert changed_type.status_code == 200
    assert changed_type.json()["type"] == "checking"
    assert changed_type.json()["reference_account_id"] is None


def test_account_history_does_not_anticipate_future_transactions(client):
    today = dt.date.today()
    past = today - dt.timedelta(days=1)
    future = today + dt.timedelta(days=1)
    account = _create_cash_account(
        client,
        "History with future entry",
        opening_balance=10,
        opened_on=past,
    )
    category = client.post(
        "/api/v1/categories",
        json={"name": "Historical cutoff income", "type": "income"},
    ).json()
    for date, amount in ((past, 5), (future, 20)):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"],
                "category_id": category["id"],
                "date": date.isoformat(),
                "amount": amount,
            },
        )
        assert response.status_code == 201

    history = client.get(f"/api/v1/accounts/{account['id']}/history")
    assert history.status_code == 200
    assert history.json() == [{"date": past.isoformat(), "balance": "15.000000"}]


def test_archived_dossier_keeps_historical_reference_but_cannot_be_reactivated_with_it(client):
    cash = _create_cash_account(client, "Cash")
    investment = _create_investment_account(client, "Investment account", cash["id"])

    assert client.post(f"/api/v1/accounts/{investment['id']}/deactivate").status_code == 200
    assert client.post(f"/api/v1/accounts/{cash['id']}/deactivate").status_code == 200

    reactivate = client.put(
        f"/api/v1/accounts/{investment['id']}",
        json={"is_active": True},
    )
    assert reactivate.status_code == 409

    # The historical reference remains a real FK: even if both accounts
    # are archived, the cash account cannot be deleted from under the portfolio account.
    delete_reference = client.delete(f"/api/v1/accounts/{cash['id']}")
    assert delete_reference.status_code == 409
    assert delete_reference.json()["detail"]["dependent_accounts_count"] == 1


def test_inactive_cash_account_rejects_transactions_and_both_transfer_directions(client):
    inactive = _create_cash_account(client, "Archived account")
    active = _create_cash_account(client, "Active account")
    assert client.post(f"/api/v1/accounts/{inactive['id']}/deactivate").status_code == 200
    category = client.post(
        "/api/v1/categories",
        json={"name": "Lifecycle income", "type": "income"},
    ).json()

    transaction = client.post(
        "/api/v1/transactions",
        json={
            "account_id": inactive["id"],
            "category_id": category["id"],
            "date": "2026-08-01",
            "amount": 10,
        },
    )
    assert transaction.status_code == 409

    for from_id, to_id in (
        (inactive["id"], active["id"]),
        (active["id"], inactive["id"]),
    ):
        transfer = client.post(
            "/api/v1/transactions/transfer",
            json={
                "from_account_id": from_id,
                "to_account_id": to_id,
                "date": "2026-08-02",
                "amount": 10,
            },
        )
        assert transfer.status_code == 409

    assert client.get("/api/v1/transactions").json()["total"] == 0


def test_inactive_investment_account_rejects_all_new_financial_writes(client):
    cash = _create_cash_account(client, "Cash")
    investment = _create_investment_account(client, "Investment account", cash["id"])
    security = _create_security(client)
    trade = _create_trade(
        client,
        security_id=security["id"],
        account_id=investment["id"],
        date="2026-07-01",
    )
    close_trade = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "sell",
            "date": "2026-07-02",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    assert close_trade.status_code == 201
    assert client.post(f"/api/v1/accounts/{investment['id']}/deactivate").status_code == 200

    new_trade = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "buy",
            "date": "2026-07-03",
            "quantity": 1,
            "price": 10,
            "currency": "EUR",
        },
    )
    assert new_trade.status_code == 409

    trade_cost = client.post(
        f"/api/v1/trades/{trade['id']}/costs",
        json={"cost_type": "commission", "amount": 1},
    )
    assert trade_cost.status_code == 409

    income = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "event_type": "dividend",
            "payment_date": "2026-07-03",
            "total_amount": 10,
            "currency": "EUR",
        },
    )
    assert income.status_code == 409

    portfolio_cost = client.post(
        "/api/v1/portfolio-costs",
        json={
            "date": "2026-07-04",
            "cost_type": "custody_fee",
            "account_id": investment["id"],
            "amount": 5,
        },
    )
    assert portfolio_cost.status_code == 409


def test_reference_change_is_prospective_for_linked_cash_movements(client):
    old_cash = _create_cash_account(client, "Old cash")
    new_cash = _create_cash_account(client, "New cash")
    investment = _create_investment_account(client, "Investment account", old_cash["id"])
    security = _create_security(client)
    historical_trade = _create_trade(
        client,
        security_id=security["id"],
        account_id=investment["id"],
        date="2026-06-01",
    )

    change_reference = client.put(
        f"/api/v1/accounts/{investment['id']}",
        json={"reference_account_id": new_cash["id"]},
    )
    assert change_reference.status_code == 200

    # Resynchronizing an existing cash flow updates its amount,
    # but does not move it to the new reference account.
    add_cost = client.post(
        f"/api/v1/trades/{historical_trade['id']}/costs",
        json={"cost_type": "commission", "amount": 5},
    )
    assert add_cost.status_code == 201

    old_movements = client.get(
        "/api/v1/transactions", params={"account_id": old_cash["id"]}
    ).json()["items"]
    historical_movement = next(
        movement for movement in old_movements if movement["trade_id"] == historical_trade["id"]
    )
    assert float(historical_movement["amount_eur"]) == -105

    new_movements = client.get(
        "/api/v1/transactions", params={"account_id": new_cash["id"]}
    ).json()["items"]
    assert all(movement["trade_id"] != historical_trade["id"] for movement in new_movements)

    new_trade = _create_trade(
        client,
        security_id=security["id"],
        account_id=investment["id"],
        date="2026-06-02",
        price=20,
    )
    new_movements = client.get(
        "/api/v1/transactions", params={"account_id": new_cash["id"]}
    ).json()["items"]
    assert any(movement["trade_id"] == new_trade["id"] for movement in new_movements)


def test_delete_account_aggregates_every_financial_child_blocker(client):
    cash = _create_cash_account(client, "Cash")
    investment = _create_investment_account(client, "Investment account", cash["id"])
    security = _create_security(client)
    _create_trade(
        client,
        security_id=security["id"],
        account_id=investment["id"],
        date="2026-05-01",
    )
    assert (
        client.post(
            "/api/v1/income-events",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "event_type": "dividend",
                "payment_date": "2026-05-02",
                "total_amount": 10,
                "currency": "EUR",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/portfolio-costs",
            json={
                "date": "2026-05-03",
                "cost_type": "custody_fee",
                "account_id": investment["id"],
                "amount": 5,
            },
        ).status_code
        == 201
    )

    response = client.delete(f"/api/v1/accounts/{investment['id']}")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["transactions_count"] == 0
    assert detail["trades_count"] == 1
    assert detail["income_events_count"] == 1
    assert detail["portfolio_costs_count"] == 1
    assert len(detail["blockers"]) == 3


def test_delete_account_aggregates_transaction_dependent_and_opening_balance(client):
    cash = _create_cash_account(client, "Cash", opening_balance=100)
    _create_investment_account(client, "Investment account", cash["id"])
    category = client.post(
        "/api/v1/categories",
        json={"name": "Deletion-blocking income", "type": "income"},
    ).json()
    assert (
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": cash["id"],
                "category_id": category["id"],
                "date": "2026-04-01",
                "amount": 1,
            },
        ).status_code
        == 201
    )

    response = client.delete(f"/api/v1/accounts/{cash['id']}")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["transactions_count"] == 1
    assert detail["dependent_accounts_count"] == 1
    assert float(detail["opening_balance"]) == 100
    assert len(detail["blockers"]) == 3


def test_nonzero_opening_balance_alone_blocks_hard_delete(client):
    cash = _create_cash_account(client, "Opening balance", opening_balance=50)

    response = client.delete(f"/api/v1/accounts/{cash['id']}")
    assert response.status_code == 409
    assert response.json()["detail"]["blockers"] == ["opening balance 50.000000 EUR"]
    assert any(account["id"] == cash["id"] for account in client.get("/api/v1/accounts").json())


def test_inactive_accounts_are_read_only_for_deletions(client):
    today = dt.date.today().isoformat()
    expense = client.post(
        "/api/v1/categories",
        json={"name": "Lifecycle reset", "type": "expense"},
    ).json()
    cash_to_close = _create_cash_account(client, "Closed cash", opening_balance=100)
    zeroing = client.post(
        "/api/v1/transactions",
        json={
            "account_id": cash_to_close["id"],
            "category_id": expense["id"],
            "date": today,
            "amount": -100,
        },
    ).json()
    assert client.post(f"/api/v1/accounts/{cash_to_close['id']}/deactivate").status_code == 200

    blocked_transaction = client.delete(f"/api/v1/transactions/{zeroing['id']}")
    assert blocked_transaction.status_code == 409
    balance = client.get(f"/api/v1/accounts/{cash_to_close['id']}/balance").json()["balance"]
    assert float(balance) == 0

    cash = _create_cash_account(client, "Closed-source cash")
    investment = _create_investment_account(client, "Closed investment account", cash["id"])
    security = _create_security(client, "READONLY.MI")
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "buy",
            "date": today,
            "quantity": 1,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    sell = client.post(
        "/api/v1/trades",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "type": "sell",
            "date": today,
            "quantity": 1,
            "price": 10,
            "currency": "EUR",
        },
    ).json()
    income = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "event_type": "dividend",
            "payment_date": today,
            "total_amount": 1,
            "currency": "EUR",
        },
    ).json()
    recurring = client.post(
        "/api/v1/portfolio-costs",
        json={
            "account_id": investment["id"],
            "date": today,
            "cost_type": "custody_fee",
            "amount": 1,
            "currency": "EUR",
        },
    ).json()
    assert client.post(f"/api/v1/accounts/{investment['id']}/deactivate").status_code == 200

    assert client.delete(f"/api/v1/trades/{sell['id']}").status_code == 409
    assert client.delete(f"/api/v1/income-events/{income['id']}").status_code == 409
    assert client.delete(f"/api/v1/portfolio-costs/{recurring['id']}").status_code == 409
    assert {trade["id"] for trade in client.get("/api/v1/trades").json()} == {
        buy["id"],
        sell["id"],
    }


def test_frozen_cash_account_survives_zero_cashflow_and_reference_change(client):
    today = dt.date.today().isoformat()
    old_cash = _create_cash_account(client, "Original cash")
    new_cash = _create_cash_account(client, "New cash")
    investment = _create_investment_account(client, "Original investment account", old_cash["id"])
    security = _create_security(client, "FROZEN.MI")

    sale = None
    for type_ in ("buy", "sell"):
        response = client.post(
            "/api/v1/trades",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "type": type_,
                "date": today,
                "quantity": 1,
                "price": 100,
                "currency": "EUR",
            },
        )
        assert response.status_code == 201, response.text
        if type_ == "sell":
            sale = response.json()
    assert sale is not None

    assert (
        client.put(
            f"/api/v1/accounts/{investment['id']}",
            json={"reference_account_id": new_cash["id"]},
        ).status_code
        == 200
    )
    exact_cost = client.post(
        f"/api/v1/trades/{sale['id']}/costs",
        json={"cost_type": "commission", "amount": 100, "currency": "EUR"},
    )
    assert exact_cost.status_code == 201, exact_cost.text
    old_movements = client.get(
        "/api/v1/transactions", params={"account_id": old_cash["id"]}
    ).json()["items"]
    assert all(movement["trade_id"] != sale["id"] for movement in old_movements)

    delete_cost = client.delete(f"/api/v1/trades/{sale['id']}/costs/{exact_cost.json()['id']}")
    assert delete_cost.status_code == 204
    old_movements = client.get(
        "/api/v1/transactions", params={"account_id": old_cash["id"]}
    ).json()["items"]
    restored = next(movement for movement in old_movements if movement["trade_id"] == sale["id"])
    assert float(restored["amount_eur"]) == 100
    new_movements = client.get(
        "/api/v1/transactions", params={"account_id": new_cash["id"]}
    ).json()["items"]
    assert all(movement["trade_id"] != sale["id"] for movement in new_movements)


def test_frozen_inactive_cash_account_blocks_trade_cost_and_rolls_back(client):
    today = dt.date.today().isoformat()
    old_cash = _create_cash_account(client, "Historical cash")
    new_cash = _create_cash_account(client, "Current cash")
    investment = _create_investment_account(client, "Rollover investment account", old_cash["id"])
    security = _create_security(client, "ROLLBACK.MI")

    sale = None
    for type_ in ("buy", "sell"):
        response = client.post(
            "/api/v1/trades",
            json={
                "security_id": security["id"],
                "account_id": investment["id"],
                "type": type_,
                "date": today,
                "quantity": 1,
                "price": 100,
                "currency": "EUR",
            },
        )
        assert response.status_code == 201, response.text
        if type_ == "sell":
            sale = response.json()
    assert sale is not None

    assert (
        client.put(
            f"/api/v1/accounts/{investment['id']}",
            json={"reference_account_id": new_cash["id"]},
        ).status_code
        == 200
    )
    assert client.post(f"/api/v1/accounts/{old_cash['id']}/deactivate").status_code == 200

    blocked = client.post(
        f"/api/v1/trades/{sale['id']}/costs",
        json={"cost_type": "commission", "amount": 1, "currency": "EUR"},
    )
    assert blocked.status_code == 409
    assert client.get(f"/api/v1/trades/{sale['id']}/costs").json() == []
    old_movements = client.get(
        "/api/v1/transactions", params={"account_id": old_cash["id"]}
    ).json()["items"]
    sale_movement = next(
        movement for movement in old_movements if movement["trade_id"] == sale["id"]
    )
    assert float(sale_movement["amount_eur"]) == 100
