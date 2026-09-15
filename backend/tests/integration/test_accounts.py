"""Integration tests: account CRUD (specification §6.2)."""

from decimal import Decimal


def test_create_and_get_account(client):
    resp = client.post(
        "/api/v1/accounts",
        json={
            "name": "Test Account",
            "type": "checking",
            "currency": "EUR",
            "opening_balance": 500,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Account"
    assert data["is_active"] is True


def test_opening_balance_is_normalized_before_create_update_and_db_round_trip(client):
    created = client.post(
        "/api/v1/accounts",
        json={
            "name": "Precise balance",
            "type": "checking",
            "opening_balance": "12345.1234565",
        },
    )
    assert created.status_code == 201
    account_id = created.json()["id"]
    assert Decimal(str(created.json()["opening_balance"])) == Decimal("12345.123456")

    # A second request reads the value actually
    # committed by SQLite, rather than just the value assigned to the ORM.
    persisted_after_create = next(
        account for account in client.get("/api/v1/accounts").json() if account["id"] == account_id
    )
    assert Decimal(str(persisted_after_create["opening_balance"])) == Decimal("12345.123456")

    updated = client.put(
        f"/api/v1/accounts/{account_id}",
        json={"opening_balance": "-12345.1234575"},
    )
    assert updated.status_code == 200
    assert Decimal(str(updated.json()["opening_balance"])) == Decimal("-12345.123458")

    persisted_after_update = next(
        account for account in client.get("/api/v1/accounts").json() if account["id"] == account_id
    )
    assert Decimal(str(persisted_after_update["opening_balance"])) == Decimal("-12345.123458")


def test_opening_balance_application_max_round_trips_on_sqlite(client):
    response = client.post(
        "/api/v1/accounts",
        json={
            "name": "Maximum balance",
            "type": "checking",
            "opening_balance": "999999999",
        },
    )
    assert response.status_code == 201
    account_id = response.json()["id"]

    persisted = next(
        account for account in client.get("/api/v1/accounts").json() if account["id"] == account_id
    )
    assert Decimal(str(persisted["opening_balance"])) == Decimal("999999999.000000")


def test_create_rejects_opening_balance_underflow_overflow_and_nonfinite_with_400(client):
    invalid_values = (
        "0.0000004",
        "-0.0000004",
        "1000000000",
        "-1000000000",
        "NaN",
        "Infinity",
        "-Infinity",
    )
    for index, value in enumerate(invalid_values):
        response = client.post(
            "/api/v1/accounts",
            json={
                "name": f"Invalid balance {index}",
                "type": "checking",
                "opening_balance": value,
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert body["detail"] == {
            "field": "opening_balance",
            "value": str(Decimal(value)),
        }

    assert client.get("/api/v1/accounts").json() == []


def test_investment_create_uses_same_400_for_unrepresentable_opening_balance(client):
    reference = client.post(
        "/api/v1/accounts",
        json={"name": "Cash", "type": "checking"},
    ).json()

    for index, value in enumerate(("0.0000004", "1000000000", "NaN")):
        response = client.post(
            "/api/v1/accounts",
            json={
                "name": f"Unrepresentable investment account {index}",
                "type": "investment",
                "reference_account_id": reference["id"],
                "opening_balance": value,
            },
        )
        assert response.status_code == 400
        assert response.json()["error_code"] == "VALIDATION_ERROR"
        assert response.json()["detail"]["field"] == "opening_balance"


def test_update_rejects_invalid_opening_balance_without_changing_persisted_value(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Unchanged balance", "type": "checking", "opening_balance": "10"},
    ).json()

    for value in ("0.0000004", "1000000000", "NaN"):
        response = client.put(
            f"/api/v1/accounts/{account['id']}",
            json={"opening_balance": value},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error_code"] == "VALIDATION_ERROR"
        assert body["detail"] == {
            "field": "opening_balance",
            "value": str(Decimal(value)),
        }

    persisted = next(
        item for item in client.get("/api/v1/accounts").json() if item["id"] == account["id"]
    )
    assert Decimal(str(persisted["opening_balance"])) == Decimal("10.000000")


def test_list_accounts(client):
    client.post("/api/v1/accounts", json={"name": "A1", "type": "checking"})
    client.post("/api/v1/accounts", json={"name": "A2", "type": "savings"})
    resp = client.get("/api/v1/accounts")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_balance_after_transactions(client):
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Balance Account",
            "type": "checking",
            "opening_balance": 1000,
            "opened_on": "2026-07-01",
        },
    ).json()
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "Balance income", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "Balance expenses", "type": "expense"}
    ).json()["id"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": income_category_id,
            "date": "2026-07-01",
            "amount": 200,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": expense_category_id,
            "date": "2026-07-02",
            "amount": -50,
            "currency": "EUR",
        },
    )
    resp = client.get(f"/api/v1/accounts/{account['id']}/balance")
    assert resp.status_code == 200
    assert float(resp.json()["balance"]) == 1150.0


def test_get_balance_nonexistent_account_returns_404_with_error_schema(client):
    resp = client.get("/api/v1/accounts/9999/balance")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error_code"] == "NOT_FOUND"
    assert "detail" in body


def test_deactivate_account_soft_delete(client):
    account = client.post("/api/v1/accounts", json={"name": "To deactivate", "type": "cash"}).json()
    resp = client.post(f"/api/v1/accounts/{account['id']}/deactivate")
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_delete_account_without_movements(client):
    account = client.post("/api/v1/accounts", json={"name": "To delete", "type": "cash"}).json()
    resp = client.delete(f"/api/v1/accounts/{account['id']}")
    assert resp.status_code == 204

    resp = client.get("/api/v1/accounts")
    assert all(a["id"] != account["id"] for a in resp.json())


def test_cannot_delete_account_with_transactions(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Used Account", "type": "checking", "opened_on": "2026-07-01"},
    ).json()
    category_id = client.post(
        "/api/v1/categories", json={"name": "Used account income", "type": "income"}
    ).json()["id"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 10,
            "currency": "EUR",
        },
    )
    resp = client.delete(f"/api/v1/accounts/{account['id']}")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


def test_balance_history_aggregates_same_day_transactions(client):
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "History Account",
            "type": "checking",
            "opening_balance": 1000,
            "opened_on": "2026-01-01",
        },
    ).json()
    income_category_id = client.post(
        "/api/v1/categories", json={"name": "History income", "type": "income"}
    ).json()["id"]
    expense_category_id = client.post(
        "/api/v1/categories", json={"name": "History expenses", "type": "expense"}
    ).json()["id"]
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": income_category_id,
            "date": "2026-01-15",
            "amount": 500,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": expense_category_id,
            "date": "2026-02-10",
            "amount": -200,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": expense_category_id,
            "date": "2026-02-10",
            "amount": -50,
            "currency": "EUR",
        },
    )

    resp = client.get(f"/api/v1/accounts/{account['id']}/history")
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 3  # opening + two distinct dates, not 3 transactions
    assert points[0]["date"] == "2026-01-01"
    assert float(points[0]["balance"]) == 1000.0
    assert points[1]["date"] == "2026-01-15"
    assert float(points[1]["balance"]) == 1500.0
    assert points[2]["date"] == "2026-02-10"
    assert float(points[2]["balance"]) == 1250.0  # 1500 - 200 - 50, aggregated


def test_balance_history_empty_account_returns_opening_balance(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Empty Account", "type": "checking", "opening_balance": 300},
    ).json()
    resp = client.get(f"/api/v1/accounts/{account['id']}/history")
    assert resp.status_code == 200
    points = resp.json()
    assert len(points) == 1
    assert float(points[0]["balance"]) == 300.0


def test_investment_account_requires_reference_account(client):
    """Investment accounts never hold their own cash (specification §5.2): they require a reference account at creation."""
    resp = client.post(
        "/api/v1/accounts", json={"name": "Securities Account", "type": "investment"}
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_investment_account_reference_cannot_be_another_investment_account(client):
    checking = client.post("/api/v1/accounts", json={"name": "Checking", "type": "checking"}).json()
    invest_a = client.post(
        "/api/v1/accounts",
        json={"name": "Securities A", "type": "investment", "reference_account_id": checking["id"]},
    ).json()
    resp = client.post(
        "/api/v1/accounts",
        json={"name": "Securities B", "type": "investment", "reference_account_id": invest_a["id"]},
    )
    assert resp.status_code == 400


def test_non_investment_account_cannot_have_reference_account(client):
    checking = client.post("/api/v1/accounts", json={"name": "Checking", "type": "checking"}).json()
    resp = client.post(
        "/api/v1/accounts",
        json={"name": "Other", "type": "savings", "reference_account_id": checking["id"]},
    )
    assert resp.status_code == 400


def test_cannot_delete_account_referenced_by_investment_account(client):
    checking = client.post("/api/v1/accounts", json={"name": "Checking", "type": "checking"}).json()
    client.post(
        "/api/v1/accounts",
        json={"name": "Securities", "type": "investment", "reference_account_id": checking["id"]},
    )
    resp = client.delete(f"/api/v1/accounts/{checking['id']}")
    assert resp.status_code == 409


def test_investment_account_rejected_for_manual_transaction(client):
    checking = client.post("/api/v1/accounts", json={"name": "Checking", "type": "checking"}).json()
    invest = client.post(
        "/api/v1/accounts",
        json={"name": "Securities", "type": "investment", "reference_account_id": checking["id"]},
    ).json()
    category_id = client.post(
        "/api/v1/categories", json={"name": "Invalid income", "type": "income"}
    ).json()["id"]
    resp = client.post(
        "/api/v1/transactions",
        json={
            "account_id": invest["id"],
            "category_id": category_id,
            "date": "2026-07-01",
            "amount": 100,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 400


def test_investment_account_rejected_as_transfer_endpoint(client):
    checking_a = client.post(
        "/api/v1/accounts", json={"name": "Checking 1", "type": "checking"}
    ).json()
    invest = client.post(
        "/api/v1/accounts",
        json={"name": "Securities", "type": "investment", "reference_account_id": checking_a["id"]},
    ).json()
    resp = client.post(
        "/api/v1/transactions/transfer",
        json={
            "from_account_id": checking_a["id"],
            "to_account_id": invest["id"],
            "date": "2026-07-01",
            "amount": 100,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 400
