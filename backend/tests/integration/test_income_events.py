"""Integration tests: coupons/dividends (specification §6.5)."""

from decimal import Decimal


def _make_security(client) -> int:
    return client.post(
        "/api/v1/securities",
        json={"ticker": "ENI.MI", "name": "Eni SpA", "type": "stock", "currency": "EUR"},
    ).json()["id"]


def _make_account(client) -> int:
    return _make_account_with_reference(client)[0]


def _make_account_with_reference(client) -> tuple[int, int]:
    """Return (investment_account_id, reference_account_id): the coupon's linked transaction belongs to the second account (specification §5.2)."""
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking Account", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    invest = client.post(
        "/api/v1/accounts",
        json={
            "name": "Securities Account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    return invest["id"], checking["id"]


def test_create_income_event_normalizes_eur(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    resp = client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
            "tax_withheld": 13,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert float(data["total_eur"]) == 50.0
    assert float(data["net_amount_eur"]) == 37.0


def test_income_event_normalizes_native_components_before_netting(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    response = client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "quantity_held": "10.0000005",
            "amount_per_unit": "1.0000005",
            "total_amount": "10.0000005",
            "currency": "EUR",
            "tax_withheld": "1.0000005",
        },
    )

    assert response.status_code == 201, response.text
    event = response.json()
    assert Decimal(event["quantity_held"]) == Decimal("10.000000")
    assert Decimal(event["amount_per_unit"]) == Decimal("1.000000")
    assert Decimal(event["total_amount"]) == Decimal("10.000000")
    assert Decimal(event["tax_withheld"]) == Decimal("1.000000")
    assert Decimal(event["net_amount_eur"]) == Decimal("9.000000")


def test_income_event_invalid_security_returns_400(client):
    acc_id = _make_account(client)
    resp = client.post(
        "/api/v1/income-events",
        json={
            "security_id": 9999,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 400


def test_income_events_summary(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
            "tax_withheld": 0,
        },
    )
    resp = client.get("/api/v1/income-events/summary")
    body = resp.json()
    assert float(body["total_net_eur"]) == 50.0
    assert len(body["by_security"]) == 1
    assert body["by_security"][0]["ticker"] == "ENI.MI"


def test_delete_income_event(client):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    event = client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
        },
    ).json()
    resp = client.delete(f"/api/v1/income-events/{event['id']}")
    assert resp.status_code == 204


def test_income_event_creates_linked_net_transaction(client):
    """Recording a coupon/dividend automatically creates a linked net cash transaction, after withholding, on the receiving account so its balance reflects the income (see CHANGELOG)."""
    sec_id = _make_security(client)
    acc_id, ref_id = _make_account_with_reference(client)
    event = client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
            "tax_withheld": 13,
        },
    ).json()

    transactions = client.get("/api/v1/transactions", params={"account_id": ref_id}).json()
    assert transactions["total"] == 1
    tx = transactions["items"][0]
    assert tx["income_event_id"] == event["id"]
    assert float(tx["amount"]) == 37.0
    assert tx["date"] == "2026-06-15"

    balance = client.get(f"/api/v1/accounts/{ref_id}/balance").json()
    assert float(balance["balance"]) == 37.0


def test_deleting_income_event_removes_linked_transaction(client):
    sec_id = _make_security(client)
    acc_id, ref_id = _make_account_with_reference(client)
    event = client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "coupon",
            "payment_date": "2026-06-15",
            "amount_per_unit": 1,
            "total_amount": 20,
            "currency": "EUR",
        },
    ).json()
    client.delete(f"/api/v1/income-events/{event['id']}")

    transactions = client.get("/api/v1/transactions", params={"account_id": ref_id}).json()
    assert transactions["total"] == 0


def test_linked_transaction_cannot_be_deleted_or_edited_directly(client):
    sec_id = _make_security(client)
    acc_id, ref_id = _make_account_with_reference(client)
    client.post(
        "/api/v1/income-events",
        json={
            "security_id": sec_id,
            "account_id": acc_id,
            "event_type": "dividend",
            "payment_date": "2026-06-15",
            "amount_per_unit": 0.5,
            "total_amount": 50,
            "currency": "EUR",
        },
    )
    tx = client.get("/api/v1/transactions", params={"account_id": ref_id}).json()["items"][0]

    resp_delete = client.delete(f"/api/v1/transactions/{tx['id']}")
    assert resp_delete.status_code == 409
    assert resp_delete.json()["error_code"] == "CONFLICT"


def _post_event(client, **overrides):
    sec_id = _make_security(client)
    acc_id = _make_account(client)
    payload = {
        "security_id": sec_id,
        "account_id": acc_id,
        "event_type": "dividend",
        "payment_date": "2026-06-15",
        "total_amount": 50,
        "currency": "EUR",
    }
    payload.update(overrides)
    return client.post("/api/v1/income-events", json=payload)


def test_withholding_larger_than_the_gross_is_refused(client):
    """Withholding above gross income produces negative net income and an OUTGOING cash movement categorized as Coupons and Dividends: a dividend that removes money.

    This is a typing error, not a real case. Previously it was silently accepted, affecting returns and the income statement.
    """
    resp = _post_event(client, total_amount=10, tax_withheld=50)

    assert resp.status_code == 422
    assert "withholding" in resp.json()["message"].lower()


def test_withholding_equal_to_the_gross_is_accepted(client):
    """Valid boundary case: income fully withheld at source. Net zero, not negative."""
    resp = _post_event(client, total_amount=50, tax_withheld=50)

    assert resp.status_code == 201
    assert float(resp.json()["net_amount_eur"]) == 0.0


def test_a_negative_withholding_is_refused(client):
    """Negative withholding would inflate net income above gross income."""
    resp = _post_event(client, total_amount=50, tax_withheld=-10)

    assert resp.status_code == 422


def test_a_negative_gross_is_refused(client):
    """Income means incoming money: a negative sign is an input error. Correct it by deleting the incorrect event."""
    resp = _post_event(client, total_amount=-50)

    assert resp.status_code == 422
