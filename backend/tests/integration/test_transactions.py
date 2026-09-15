"""Integration tests: transaction CRUD, summary, and CSV import (specification §6.1, §8.1)."""

import io
from decimal import Decimal


def _make_account(client) -> int:
    return client.post(
        "/api/v1/accounts",
        json={"name": "Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]


def _make_category(client, name: str, type_: str) -> int:
    return client.post("/api/v1/categories", json={"name": name, "type": type_}).json()["id"]


def test_create_transaction_normalizes_eur(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Income", "income")
    resp = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 100,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert float(data["amount_eur"]) == 100.0
    assert float(data["fx_rate"]) == 1.0


def test_transaction_normalizes_native_amount_and_fx_before_conversion(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Precise income", "income")
    response = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": "1.0000005",
            "currency": "USD",
            "fx_rate": "0.123456789",
        },
    )

    assert response.status_code == 201, response.text
    stored = client.get("/api/v1/transactions").json()["items"][0]
    assert Decimal(stored["amount"]) == Decimal("1.000000")
    assert Decimal(stored["fx_rate"]) == Decimal("0.12345679")
    assert Decimal(stored["amount_eur"]) == Decimal("0.123457")


def test_create_transaction_invalid_account_returns_400(client):
    category_id = _make_category(client, "Income", "income")
    resp = client.post(
        "/api/v1/transactions",
        json={
            "account_id": 9999,
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 100,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_pagination(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Income", "income")
    for i in range(5):
        client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": "2026-07-01",
                "amount": i + 1,
                "currency": "EUR",
            },
        )
    resp = client.get("/api/v1/transactions", params={"page": 1, "page_size": 2})
    body = resp.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2


def test_summary_income_expense(client):
    account_id = _make_account(client)
    income_category_id = _make_category(client, "Income", "income")
    expense_category_id = _make_category(client, "Expense", "expense")
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": income_category_id,
            "date": "2026-07-01",
            "amount": 300,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": expense_category_id,
            "date": "2026-07-02",
            "amount": -100,
            "currency": "EUR",
        },
    )
    resp = client.get("/api/v1/transactions/summary")
    body = resp.json()
    assert float(body["total_income"]) == 300.0
    assert float(body["total_expense"]) == -100.0
    assert float(body["net"]) == 200.0


def test_import_csv_with_deduplication(client):
    account_id = _make_account(client)
    _make_category(client, "CSV income", "income")
    csv_content = "date,description,amount,category\n2026-07-01,Test row,50.00,CSV income\n"

    file_1 = io.BytesIO(csv_content.encode("utf-8"))
    resp1 = client.post(
        "/api/v1/transactions/import",
        files={"file": ("test.csv", file_1, "text/csv")},
        data={"account_id": str(account_id), "category_column": "category"},
    )
    assert resp1.status_code == 200
    assert resp1.json() == {"imported": 1, "skipped_duplicates": 0, "errors": 0}

    file_2 = io.BytesIO(csv_content.encode("utf-8"))
    resp2 = client.post(
        "/api/v1/transactions/import",
        files={"file": ("test.csv", file_2, "text/csv")},
        data={"account_id": str(account_id), "category_column": "category"},
    )
    assert resp2.status_code == 200
    assert resp2.json() == {"imported": 0, "skipped_duplicates": 1, "errors": 0}


def test_delete_transaction(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Income", "income")
    tx = client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 10,
            "currency": "EUR",
        },
    ).json()
    resp = client.delete(f"/api/v1/transactions/{tx['id']}")
    assert resp.status_code == 204
    resp2 = client.get(f"/api/v1/transactions/{tx['id']}")
    assert resp2.status_code == 404


def test_create_transfer_creates_two_linked_transactions(client):
    account_a = _make_account(client)
    account_b = client.post(
        "/api/v1/accounts",
        json={"name": "Account B", "type": "savings", "opened_on": "2000-01-01"},
    ).json()["id"]

    resp = client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": account_a,
            "to_account_id": account_b,
            "date": "2026-07-01",
            "amount": "200.0000005",
            "currency": "EUR",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    from_tx = body["from_transaction"]
    to_tx = body["to_transaction"]

    assert Decimal(from_tx["amount"]) == Decimal("-200.000000")
    assert from_tx["account_id"] == account_a
    assert Decimal(to_tx["amount"]) == Decimal("200.000000")
    assert to_tx["account_id"] == account_b
    assert from_tx["transfer_group_id"] is not None
    assert from_tx["transfer_group_id"] == to_tx["transfer_group_id"]
    # The Account Transfer category is created on demand if absent
    assert from_tx["category_id"] is not None
    assert from_tx["category_id"] == to_tx["category_id"]
    category = client.get("/api/v1/categories").json()
    transfer_cat = next(c for c in category if c["id"] == from_tx["category_id"])
    assert transfer_cat["name"] == "Account Transfer"
    assert transfer_cat["type"] == "transfer"


def test_create_transfer_same_account_returns_400(client):
    account_a = _make_account(client)
    resp = client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": account_a,
            "to_account_id": account_a,
            "date": "2026-07-01",
            "amount": 50,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_deleting_one_transfer_leg_deletes_the_sibling(client):
    account_a = _make_account(client)
    account_b = client.post(
        "/api/v1/accounts",
        json={"name": "Account B", "type": "savings", "opened_on": "2000-01-01"},
    ).json()["id"]
    body = client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": account_a,
            "to_account_id": account_b,
            "date": "2026-07-01",
            "amount": 75,
            "currency": "EUR",
        },
    ).json()

    resp = client.delete(f"/api/v1/transactions/{body['from_transaction']['id']}")
    assert resp.status_code == 204

    resp_sibling = client.get(f"/api/v1/transactions/{body['to_transaction']['id']}")
    assert resp_sibling.status_code == 404


def test_list_transactions_sorting(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Income", "income")
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 50,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-03",
            "amount": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "date": "2026-07-02",
            "amount": 30,
            "currency": "EUR",
        },
    )

    asc = client.get("/api/v1/transactions", params={"sort_by": "date", "sort_dir": "asc"}).json()
    assert [t["date"] for t in asc["items"]] == ["2026-07-01", "2026-07-02", "2026-07-03"]

    desc = client.get("/api/v1/transactions", params={"sort_by": "date", "sort_dir": "desc"}).json()
    assert [t["date"] for t in desc["items"]] == ["2026-07-03", "2026-07-02", "2026-07-01"]

    by_amount = client.get(
        "/api/v1/transactions", params={"sort_by": "amount", "sort_dir": "asc"}
    ).json()
    assert [float(t["amount"]) for t in by_amount["items"]] == [10.0, 30.0, 50.0]


def test_transaction_text_columns_sort_by_the_labels_shown_in_cashflow(client):
    account_z = client.post(
        "/api/v1/accounts",
        json={"name": "Zeta", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    account_a = client.post(
        "/api/v1/accounts",
        json={"name": "Alpha", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]
    category_z = _make_category(client, "Sugar", "income")
    category_a = _make_category(client, "Rent received", "income")

    for account_id, category_id, description in (
        (account_z, category_z, "Zebra"),
        (account_a, category_a, "Tree"),
    ):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": "2026-07-01",
                "amount": 10,
                "currency": "EUR",
                "description": description,
            },
        )
        assert response.status_code == 201

    by_account = client.get(
        "/api/v1/transactions", params={"sort_by": "account_id", "sort_dir": "asc"}
    ).json()["items"]
    by_category = client.get(
        "/api/v1/transactions", params={"sort_by": "category_id", "sort_dir": "asc"}
    ).json()["items"]
    by_description = client.get(
        "/api/v1/transactions", params={"sort_by": "description", "sort_dir": "asc"}
    ).json()["items"]

    assert [item["account_id"] for item in by_account] == [account_a, account_z]
    assert [item["category_id"] for item in by_category] == [category_a, category_z]
    assert [item["description"] for item in by_description] == ["Tree", "Zebra"]


def test_transaction_description_sort_is_case_insensitive_and_keeps_missing_last(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Sorting income", "income")

    for description in ("zebra", "Tree", None, ""):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": "2026-07-01",
                "amount": 10,
                "currency": "EUR",
                "description": description,
            },
        )
        assert response.status_code == 201

    ascending = client.get(
        "/api/v1/transactions", params={"sort_by": "description", "sort_dir": "asc"}
    ).json()["items"]
    descending = client.get(
        "/api/v1/transactions", params={"sort_by": "description", "sort_dir": "desc"}
    ).json()["items"]

    assert [item["description"] for item in ascending[:2]] == ["Tree", "zebra"]
    assert [item["description"] for item in descending[:2]] == ["zebra", "Tree"]
    assert {item["description"] for item in ascending[2:]} == {None, ""}
    assert {item["description"] for item in descending[2:]} == {None, ""}


def test_transaction_description_sort_is_natural_across_server_pages(client):
    account_id = _make_account(client)
    category_id = _make_category(client, "Instalments", "expense")
    for description in ("Instalment 10", "Instalment 2", "Instalment 1"):
        response = client.post(
            "/api/v1/transactions",
            json={
                "account_id": account_id,
                "category_id": category_id,
                "date": "2026-08-01",
                "amount": "-1",
                "currency": "EUR",
                "description": description,
            },
        )
        assert response.status_code == 201

    first_page = client.get(
        "/api/v1/transactions",
        params={"sort_by": "description", "sort_dir": "asc", "page_size": 2},
    ).json()
    second_page = client.get(
        "/api/v1/transactions",
        params={
            "sort_by": "description",
            "sort_dir": "asc",
            "page": 2,
            "page_size": 2,
        },
    ).json()

    descriptions = [item["description"] for item in first_page["items"]]
    descriptions += [item["description"] for item in second_page["items"]]
    assert descriptions == ["Instalment 1", "Instalment 2", "Instalment 10"]
