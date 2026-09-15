"""Integration tests: category CRUD and hierarchy constraints (specification §5.1)."""

from app.models.category import Category
from tests.integration.conftest import TestingSessionLocal


def test_create_category(client):
    resp = client.post("/api/v1/categories", json={"name": "Travel", "type": "expense"})
    assert resp.status_code == 201
    assert resp.json()["is_system"] is False


def test_duplicate_category_name_returns_409(client):
    client.post("/api/v1/categories", json={"name": "Travel", "type": "expense"})
    resp = client.post("/api/v1/categories", json={"name": "Travel", "type": "expense"})
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


def test_hierarchy_max_two_levels(client):
    parent = client.post("/api/v1/categories", json={"name": "Home", "type": "expense"}).json()
    child = client.post(
        "/api/v1/categories",
        json={"name": "Household bills", "type": "expense", "parent_id": parent["id"]},
    )
    assert child.status_code == 201

    grandchild = client.post(
        "/api/v1/categories",
        json={"name": "Electricity bill", "type": "expense", "parent_id": child.json()["id"]},
    )
    assert grandchild.status_code == 400
    assert grandchild.json()["error_code"] == "VALIDATION_ERROR"


def test_cannot_delete_category_with_children(client):
    parent = client.post("/api/v1/categories", json={"name": "Parent", "type": "expense"}).json()
    client.post(
        "/api/v1/categories", json={"name": "Child", "type": "expense", "parent_id": parent["id"]}
    )
    resp = client.delete(f"/api/v1/categories/{parent['id']}")
    assert resp.status_code == 409


def test_cannot_delete_category_used_by_transactions(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    category = client.post(
        "/api/v1/categories", json={"name": "Test expense", "type": "expense"}
    ).json()
    client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "category_id": category["id"],
            "date": "2026-07-01",
            "amount": -10,
            "currency": "EUR",
        },
    )
    resp = client.delete(f"/api/v1/categories/{category['id']}")
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


def test_subcategory_type_must_match_parent(client):
    parent = client.post(
        "/api/v1/categories", json={"name": "Other income", "type": "income"}
    ).json()
    resp = client.post(
        "/api/v1/categories",
        json={"name": "Household expense", "type": "expense", "parent_id": parent["id"]},
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_subcategory_same_type_as_parent_is_allowed(client):
    parent = client.post("/api/v1/categories", json={"name": "Home", "type": "expense"}).json()
    resp = client.post(
        "/api/v1/categories",
        json={"name": "Rent", "type": "expense", "parent_id": parent["id"]},
    )
    assert resp.status_code == 201


def test_system_category_is_now_deletable(client):
    """System categories can be deleted when unused; the default set is not permanent."""
    db = TestingSessionLocal()
    try:
        system_category = Category(name="Test system", type="expense", is_system=True)
        db.add(system_category)
        db.commit()
        db.refresh(system_category)
        category_id = system_category.id
    finally:
        db.close()

    resp = client.delete(f"/api/v1/categories/{category_id}")
    assert resp.status_code == 204

    resp = client.get("/api/v1/categories")
    assert all(c["id"] != category_id for c in resp.json())
