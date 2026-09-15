"""Invariants shared by every path that persists Transaction."""

import io

import pytest


def _account(client, name: str = "Account") -> int:
    return client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]


def _category(client, name: str, type_: str, parent_id: int | None = None) -> dict:
    payload = {"name": name, "type": type_}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    response = client.post("/api/v1/categories", json=payload)
    assert response.status_code == 201
    return response.json()


def _manual_transaction(client, account_id: int, category_id: int, amount: float):
    return client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-08-01",
            "amount": amount,
            "currency": "EUR",
        },
    )


def test_manual_transaction_requires_an_existing_category(client):
    account_id = _account(client)

    missing = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "date": "2026-08-01",
            "amount": 10,
            "currency": "EUR",
        },
    )
    unknown = _manual_transaction(client, account_id, 999_999, 10)

    assert missing.status_code == 422
    assert unknown.status_code == 400
    assert unknown.json()["error_code"] == "VALIDATION_ERROR"


def test_a_root_leaf_and_a_child_leaf_are_assignable_but_the_parent_is_not(client):
    account_id = _account(client)
    root_leaf = _category(client, "Test salary", "income")
    parent = _category(client, "Test home", "expense")
    child = _category(client, "Test rent", "expense", parent["id"])

    assert _manual_transaction(client, account_id, root_leaf["id"], 100).status_code == 201
    assert _manual_transaction(client, account_id, child["id"], -50).status_code == 201

    rejected = _manual_transaction(client, account_id, parent["id"], -10)
    assert rejected.status_code == 400
    assert "leaf" in rejected.json()["message"].lower()


@pytest.mark.parametrize(
    ("category_type", "amount"),
    [("income", -1), ("expense", 1)],
)
def test_manual_transaction_sign_must_match_category_type(client, category_type, amount):
    account_id = _account(client)
    category = _category(client, f"Category {category_type}", category_type)

    response = _manual_transaction(client, account_id, category["id"], amount)

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_manual_transaction_rejects_zero_and_transfer_categories(client):
    account_id = _account(client)
    income = _category(client, "Test income", "income")
    transfer = _category(client, "Test transfer", "transfer")

    zero = _manual_transaction(client, account_id, income["id"], 0)
    manual_transfer = _manual_transaction(client, account_id, transfer["id"], 10)

    assert zero.status_code == 422
    assert manual_transfer.status_code == 400
    assert "dedicated account transfer workflow" in manual_transfer.json()["message"].lower()


def test_dedicated_transfer_is_the_only_flow_allowed_to_use_transfer_category(client):
    from_account = _account(client, "Origin")
    to_account = _account(client, "Destination")

    response = client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": from_account,
            "to_account_id": to_account,
            "date": "2026-08-01",
            "amount": 25,
            "currency": "EUR",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert float(body["from_transaction"]["amount"]) == -25
    assert float(body["to_transaction"]["amount"]) == 25
    assert body["from_transaction"]["category_id"] == body["to_transaction"]["category_id"]


def test_creating_first_child_under_a_used_category_is_atomic_conflict(client):
    account_id = _account(client)
    parent = _category(client, "Used income", "income")
    assert _manual_transaction(client, account_id, parent["id"], 100).status_code == 201

    response = client.post(
        "/api/v1/categories",
        json={"name": "Uncreated child", "type": "income", "parent_id": parent["id"]},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "CONFLICT"
    assert all(
        category["name"] != "Uncreated child"
        for category in client.get("/api/v1/categories").json()
    )
    # The conflict does not transform the parent: it remains an assignable root leaf.
    assert _manual_transaction(client, account_id, parent["id"], 20).status_code == 201


def _upload_transactions(client, path: str, account_id: int, content: str, **extra):
    form = {"account_id": str(account_id), "category_column": "category", **extra}
    return client.post(
        path,
        files={"file": ("transactions.csv", io.BytesIO(content.encode()), "text/csv")},
        data=form,
    )


def test_csv_preview_and_import_apply_the_same_category_validator(client):
    account_id = _account(client)
    expense = _category(client, "CSV expenses", "expense")
    _category(client, "CSV income", "income")
    _category(client, "Transfer CSV", "transfer")
    parent = _category(client, "Parent CSV", "expense")
    _category(client, "Child CSV", "expense", parent["id"])
    content = (
        "date,description,amount,category\n"
        "2026-08-01,Valid,-10,CSV expenses\n"
        "2026-08-02,Income sign,-2,CSV income\n"
        "2026-08-03,Expense sign,3,CSV expenses\n"
        "2026-08-04,Zero,0,CSV income\n"
        "2026-08-05,Transfer,5,Transfer CSV\n"
        "2026-08-06,Parent,-4,Parent CSV\n"
        "2026-08-07,Empty,-1,\n"
        "2026-08-08,Unknown,-1,Does Not Exist\n"
    )

    preview = _upload_transactions(
        client, "/api/v1/transactions/import/preview", account_id, content
    )
    imported = _upload_transactions(client, "/api/v1/transactions/import", account_id, content)

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total_rows"] == 8
    assert preview_body["error_rows"] == 7
    assert preview_body["rows"][0]["errors"] == []
    assert any("greater than zero" in error for error in preview_body["rows"][1]["errors"])
    assert any("less than zero" in error for error in preview_body["rows"][2]["errors"])
    assert any("zero" in error for error in preview_body["rows"][3]["errors"])
    assert any(
        "dedicated account transfer workflow" in error
        for error in preview_body["rows"][4]["errors"]
    )
    assert any("leaf" in error for error in preview_body["rows"][5]["errors"])
    assert any("category" in error.lower() for error in preview_body["rows"][6]["errors"])
    assert any("not found" in error for error in preview_body["rows"][7]["errors"])

    assert imported.status_code == 200
    assert imported.json() == {"imported": 1, "skipped_duplicates": 0, "errors": 7}
    transactions = client.get("/api/v1/transactions").json()
    assert transactions["total"] == 1
    assert transactions["items"][0]["category_id"] == expense["id"]


def test_csv_mapping_itself_requires_a_category_column(client):
    account_id = _account(client)
    content = "date,description,amount\n2026-08-01,Without mapping,-10\n"

    for path in ("/api/v1/transactions/import/preview", "/api/v1/transactions/import"):
        response = client.post(
            path,
            files={"file": ("legacy.csv", io.BytesIO(content.encode()), "text/csv")},
            data={"account_id": str(account_id)},
        )
        assert response.status_code == 422


def test_csv_rejects_a_mapped_category_header_that_is_absent(client):
    account_id = _account(client)
    content = "date,description,amount\n2026-08-01,Missing header,-10\n"

    preview = _upload_transactions(
        client, "/api/v1/transactions/import/preview", account_id, content
    )

    assert preview.status_code == 400
    body = preview.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "Columns mapped" in body["message"]
    assert body["detail"]["missing_columns"] == ["category"]


def _investment_context(client) -> tuple[int, int, int]:
    cash_id = _account(client, "Cash")
    investment_id = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investments",
            "type": "investment",
            "reference_account_id": cash_id,
            "opened_on": "2000-01-01",
        },
    ).json()["id"]
    security_id = client.post(
        "/api/v1/securities",
        json={"ticker": "INV", "name": "Security", "type": "stock", "currency": "EUR"},
    ).json()["id"]
    return investment_id, cash_id, security_id


def _buy_and_sell(client) -> tuple[int, int]:
    investment_id, cash_id, security_id = _investment_context(client)
    buy = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": investment_id,
            "type": "buy",
            "date": "2026-08-01",
            "quantity": 1,
            "price": 10,
            "currency": "EUR",
        },
    )
    assert buy.status_code == 201
    sell = client.post(
        "/api/v1/trades",
        json={
            "security_id": security_id,
            "account_id": investment_id,
            "type": "sell",
            "date": "2026-08-02",
            "quantity": 1,
            "price": 100,
            "currency": "EUR",
        },
    )
    assert sell.status_code == 201
    return sell.json()["id"], cash_id


def test_a_zero_net_trade_keeps_the_trade_without_a_zero_transaction(client):
    sell_id, cash_id = _buy_and_sell(client)

    cost = client.post(
        f"/api/v1/trades/{sell_id}/costs",
        json={"cost_type": "commission", "amount": 100, "currency": "EUR"},
    )

    assert cost.status_code == 201
    transactions = client.get("/api/v1/transactions", params={"account_id": cash_id}).json()
    assert not any(item["trade_id"] == sell_id for item in transactions["items"])


def test_a_cost_that_would_make_a_sale_negative_is_rejected_atomically(client):
    sell_id, cash_id = _buy_and_sell(client)

    initial_cost = client.post(
        f"/api/v1/trades/{sell_id}/costs",
        json={"cost_type": "commission", "amount": 25, "currency": "EUR"},
    )
    assert initial_cost.status_code == 201

    before_costs = client.get(f"/api/v1/trades/{sell_id}/costs").json()
    before_transactions = client.get("/api/v1/transactions", params={"account_id": cash_id}).json()
    before_sale = next(item for item in before_transactions["items"] if item["trade_id"] == sell_id)
    assert float(before_sale["amount"]) == 75

    cost = client.post(
        f"/api/v1/trades/{sell_id}/costs",
        json={
            "cost_type": "tax",
            "amount": 152,
            "currency": "USD",
            "fx_rate": 0.5,
        },
    )

    assert cost.status_code == 409
    assert cost.json()["error_code"] == "CONFLICT"
    assert "would exceed" in cost.json()["message"]
    assert cost.json()["detail"] == {
        "trade_id": sell_id,
        "gross_proceeds_eur": "100.000000",
        "previous_costs_eur": "25.000000",
        "requested_cost_eur": "76.000000",
        "candidate_costs_eur": "101.000000",
    }

    # No partial writes: the rejected cost is absent and the previous
    # cash movement retains its amount and category.
    assert client.get(f"/api/v1/trades/{sell_id}/costs").json() == before_costs
    after_transactions = client.get("/api/v1/transactions", params={"account_id": cash_id}).json()
    after_sale = next(item for item in after_transactions["items"] if item["trade_id"] == sell_id)
    assert after_sale == before_sale


def test_a_legacy_negative_net_sale_fails_closed_during_resync(client):
    """A state written by an earlier version must not be disguised as an expense."""
    from decimal import Decimal

    from app.models.trade import Trade
    from app.models.trade_cost import TradeCost
    from app.repositories.transaction_repo import TransactionRepository
    from app.services.trade_service import TradeService
    from app.utils.errors import ConflictError
    from tests.integration.conftest import TestingSessionLocal

    sell_id, _ = _buy_and_sell(client)

    # Simulate a legacy row only in the in-memory database; the current API
    # no longer allows creating it.
    with TestingSessionLocal() as db:
        db.add(
            TradeCost(
                trade_id=sell_id,
                cost_type="commission",
                amount=Decimal("110"),
                currency="EUR",
                fx_rate=Decimal("1"),
                amount_eur=Decimal("110"),
            )
        )
        db.commit()

    with TestingSessionLocal() as db:
        trade = db.get(Trade, sell_id)
        assert trade is not None
        linked_before = TransactionRepository(db).get_by_link("trade_id", sell_id)
        assert linked_before is not None
        before = (linked_before.amount, linked_before.category_id)

        with pytest.raises(ConflictError, match="exceed its gross proceeds"):
            TradeService(db)._sync_linked_transaction(trade)
        db.rollback()

    with TestingSessionLocal() as db:
        linked_after = TransactionRepository(db).get_by_link("trade_id", sell_id)
        assert linked_after is not None
        assert (linked_after.amount, linked_after.category_id) == before


def test_zero_net_income_event_does_not_persist_a_zero_transaction(client):
    investment_id, cash_id, security_id = _investment_context(client)

    response = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security_id,
            "account_id": investment_id,
            "event_type": "dividend",
            "payment_date": "2026-08-10",
            "total_amount": 50,
            "tax_withheld": 50,
            "currency": "EUR",
        },
    )

    assert response.status_code == 201
    assert float(response.json()["net_amount_eur"]) == 0
    transactions = client.get("/api/v1/transactions", params={"account_id": cash_id}).json()
    assert transactions["total"] == 0
