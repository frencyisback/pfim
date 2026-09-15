"""Integration tests: tax-events and tax-settings (specification §11)."""

from decimal import Decimal

import pytest


def test_manual_tax_event_creation(client):
    resp = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Annual securities account stamp duty",
            "gross_amount": 34.20,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["event_type"] == "other"
    assert resp.json()["origin"] == "manual"


def test_manual_tax_event_numeric_fields_are_canonical_before_storage(client):
    created = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "withholding",
            "description": "Extended-precision amounts",
            "gross_amount": "100.1234565",
            "tax_rate": "26.12345",
            "tax_amount": "26.1234567",
            "net_amount": "74.0000005",
        },
    )

    assert created.status_code == 201
    body = created.json()
    # NUMERIC(18,6) and NUMERIC(8,4) use HALF_EVEN; the returned value
    # already matches SQLite's reread value without implicit rounding.
    assert Decimal(body["gross_amount"]) == Decimal("100.123456")
    assert Decimal(body["tax_rate"]) == Decimal("26.1234")
    assert Decimal(body["tax_amount"]) == Decimal("26.123457")
    assert Decimal(body["net_amount"]) == Decimal("74.000000")

    listed = client.get("/api/v1/tax-events").json()[0]
    assert Decimal(listed["gross_amount"]) == Decimal("100.123456")
    assert Decimal(listed["tax_rate"]) == Decimal("26.1234")
    assert Decimal(listed["tax_amount"]) == Decimal("26.123457")
    assert Decimal(listed["net_amount"]) == Decimal("74.000000")


@pytest.mark.parametrize("field", ["gross_amount", "tax_amount", "net_amount"])
def test_manual_tax_event_rejects_nonzero_amount_below_persisted_precision(client, field):
    response = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Unrepresentable amount",
            field: "0.0000004",
        },
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert response.json()["detail"]["field"] == field
    assert client.get("/api/v1/tax-events").json() == []


def test_manual_tax_event_update_normalizes_numeric_fields_and_is_atomic_on_error(client):
    event = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Numeric correction",
            "gross_amount": "10",
            "tax_amount": "2",
            "net_amount": "8",
        },
    ).json()

    updated = client.put(
        f"/api/v1/tax-events/{event['id']}",
        json={
            "gross_amount": "10.9876545",
            "tax_rate": "20.55555",
            "tax_amount": "2.1234565",
            "net_amount": "8.8641985",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert Decimal(body["gross_amount"]) == Decimal("10.987654")
    assert Decimal(body["tax_rate"]) == Decimal("20.5556")
    assert Decimal(body["tax_amount"]) == Decimal("2.123456")
    assert Decimal(body["net_amount"]) == Decimal("8.864198")

    rejected = client.put(
        f"/api/v1/tax-events/{event['id']}",
        json={"tax_amount": "0.0000004"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"]["field"] == "tax_amount"
    persisted = client.get("/api/v1/tax-events").json()[0]
    assert Decimal(persisted["tax_amount"]) == Decimal("2.123456")


@pytest.mark.parametrize(
    ("event_type", "gross_amount", "expected_sign"),
    [
        ("capital_gain", "-1", "non_negative"),
        ("capital_loss", "1", "non_positive"),
    ],
)
def test_manual_capital_event_rejects_a_gross_amount_with_opposite_sign(
    client, event_type, gross_amount, expected_sign
):
    response = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": event_type,
            "description": "Inconsistent sign",
            "gross_amount": gross_amount,
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["detail"]["field"] == "gross_amount"
    assert body["detail"]["event_type"] == event_type
    assert body["detail"]["expected_sign"] == expected_sign


def test_manual_capital_event_update_validates_the_effective_type_and_amount(client):
    gain = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "capital_gain",
            "description": "Manual capital gain",
            "gross_amount": "100",
        },
    ).json()

    wrong_amount = client.put(f"/api/v1/tax-events/{gain['id']}", json={"gross_amount": "-1"})
    assert wrong_amount.status_code == 400
    assert wrong_amount.json()["detail"]["event_type"] == "capital_gain"

    wrong_type = client.put(f"/api/v1/tax-events/{gain['id']}", json={"event_type": "capital_loss"})
    assert wrong_type.status_code == 400
    assert wrong_type.json()["detail"]["event_type"] == "capital_loss"

    persisted = client.get("/api/v1/tax-events").json()[0]
    assert persisted["event_type"] == "capital_gain"
    assert Decimal(persisted["gross_amount"]) == Decimal("100")

    # Zero is neutral and representable for both types.
    zero_loss = client.put(
        f"/api/v1/tax-events/{gain['id']}",
        json={"event_type": "capital_loss", "gross_amount": "0"},
    )
    assert zero_loss.status_code == 200
    assert zero_loss.json()["event_type"] == "capital_loss"


def test_list_and_delete_tax_event(client):
    event = client.post(
        "/api/v1/tax-events",
        json={"event_date": "2026-06-01", "event_type": "other", "description": "Test"},
    ).json()
    resp = client.get("/api/v1/tax-events")
    assert len(resp.json()) == 1
    del_resp = client.delete(f"/api/v1/tax-events/{event['id']}")
    assert del_resp.status_code == 204
    assert client.get("/api/v1/tax-events").json() == []


def test_api_cannot_create_an_automatic_event(client):
    resp = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "User-entered",
            "origin": "automatic_trade",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["origin"] == "manual"


def test_tax_event_rejects_two_sources_and_missing_references(client):
    both = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Ambiguous",
            "related_trade_id": 1,
            "related_income_id": 1,
        },
    )
    assert both.status_code == 422

    missing_trade = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Missing trade",
            "related_trade_id": 999,
        },
    )
    assert missing_trade.status_code == 400
    assert missing_trade.json()["detail"]["related_trade_id"] == 999

    missing_income = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Missing income event",
            "related_income_id": 999,
        },
    )
    assert missing_income.status_code == 400
    assert missing_income.json()["detail"]["related_income_id"] == 999


def test_manual_tax_event_update_validates_effective_links_and_allows_unlink(client):
    event = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-06-01",
            "event_type": "other",
            "description": "Event to correct",
        },
    ).json()

    missing = client.put(
        f"/api/v1/tax-events/{event['id']}",
        json={"related_trade_id": 999},
    )
    assert missing.status_code == 400
    assert missing.json()["detail"]["related_trade_id"] == 999

    corrected = client.put(
        f"/api/v1/tax-events/{event['id']}",
        json={
            "event_date": "2026-06-02",
            "event_type": "withholding",
            "description": "Corrected event",
            "gross_amount": 100,
            "tax_amount": 26,
            "net_amount": 74,
            "notes": "manual adjustment",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["event_date"] == "2026-06-02"
    assert corrected.json()["event_type"] == "withholding"
    assert corrected.json()["origin"] == "manual"
    assert float(corrected.json()["tax_amount"]) == 26

    explicit_null = client.put(
        f"/api/v1/tax-events/{event['id']}",
        json={"description": None},
    )
    assert explicit_null.status_code == 422


def test_tax_settings_default_and_update(client):
    # In tests without Alembic seeds, the list may be empty: the hardcoded
    # default fallback is tested separately at service level.
    # Here, verify that listing responds and updating works
    # regardless (upsert).
    assert client.get("/api/v1/tax-settings").status_code == 200
    update_resp = client.put("/api/v1/tax-settings/capital_gains_tax_rate", json={"value": 20.0})
    assert update_resp.status_code == 200
    assert float(update_resp.json()["value"]) == 20.0

    resp2 = client.get("/api/v1/tax-settings")
    keys = [s["key"] for s in resp2.json()]
    assert "capital_gains_tax_rate" in keys


def test_tax_setting_is_normalized_to_four_decimals_before_storage(client):
    response = client.put(
        "/api/v1/tax-settings/capital_gains_tax_rate",
        json={"value": "26.12345"},
    )

    assert response.status_code == 200
    assert Decimal(response.json()["value"]) == Decimal("26.1234")
    listed = client.get("/api/v1/tax-settings").json()
    assert Decimal(listed[0]["value"]) == Decimal("26.1234")


@pytest.mark.parametrize("value", ["-0.0001", "100.0001", "1000"])
def test_tax_setting_rejects_rates_outside_zero_to_one_hundred(client, value):
    response = client.put(
        "/api/v1/tax-settings/capital_gains_tax_rate",
        json={"value": value},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["detail"]["field"] == "value"
    assert body["detail"]["key"] == "capital_gains_tax_rate"
    assert client.get("/api/v1/tax-settings").json() == []


@pytest.mark.parametrize("value", ["0", "100"])
def test_tax_setting_accepts_interval_boundaries(client, value):
    response = client.put(
        "/api/v1/tax-settings/capital_gains_tax_rate",
        json={"value": value},
    )

    assert response.status_code == 200
    assert Decimal(response.json()["value"]) == Decimal(value)


def test_auto_generated_tax_event_uses_updated_rate(client):
    """After the user changes a tax rate, the next sale must use the new rate."""
    client.put("/api/v1/tax-settings/capital_gains_tax_rate", json={"value": 10.0})

    sec = client.post(
        "/api/v1/securities",
        json={"ticker": "ENI.MI", "name": "Eni", "type": "stock", "currency": "EUR"},
    ).json()
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    acc = client.post(
        "/api/v1/accounts",
        json={
            "name": "C",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": acc["id"],
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": acc["id"],
            "type": "sell",
            "date": "2026-02-01",
            "quantity": 10,
            "price": 20,
            "currency": "EUR",
        },
    )
    events = client.get("/api/v1/tax-events").json()
    gain_event = next(e for e in events if e["event_type"] == "capital_gain")
    assert float(gain_event["tax_amount"]) == 10.0  # 100 gross * 10%
    assert gain_event["origin"] == "automatic_trade"

    update = client.put(f"/api/v1/tax-events/{gain_event['id']}", json={"notes": "direct edit"})
    assert update.status_code == 409
    delete = client.delete(f"/api/v1/tax-events/{gain_event['id']}")
    assert delete.status_code == 409
    assert client.get("/api/v1/tax-events").json()[0]["id"] == gain_event["id"]


def test_deleting_trade_removes_auto_generated_tax_event(client):
    sec = client.post(
        "/api/v1/securities",
        json={"ticker": "ENI.MI", "name": "Eni", "type": "stock", "currency": "EUR"},
    ).json()
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    acc = client.post(
        "/api/v1/accounts",
        json={
            "name": "C",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": acc["id"],
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    sell = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": acc["id"],
            "type": "sell",
            "date": "2026-02-01",
            "quantity": 10,
            "price": 20,
            "currency": "EUR",
        },
    ).json()
    assert len(client.get("/api/v1/tax-events").json()) == 1

    client.delete(f"/api/v1/trades/{sell['id']}")
    assert client.get("/api/v1/tax-events").json() == []


def test_deleting_trade_preserves_manual_link_and_returns_conflict(client):
    sec = client.post(
        "/api/v1/securities",
        json={"ticker": "ISP.MI", "name": "Intesa", "type": "stock", "currency": "EUR"},
    ).json()
    checking = client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    account = client.post(
        "/api/v1/accounts",
        json={
            "name": "Investment account",
            "type": "investment",
            "reference_account_id": checking["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": account["id"],
            "type": "buy",
            "date": "2026-01-01",
            "quantity": 10,
            "price": 10,
            "currency": "EUR",
        },
    )
    sell = client.post(
        "/api/v1/trades",
        json={
            "security_id": sec["id"],
            "account_id": account["id"],
            "type": "sell",
            "date": "2026-02-01",
            "quantity": 5,
            "price": 20,
            "currency": "EUR",
        },
    ).json()
    manual = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-02-01",
            "event_type": "other",
            "description": "Example tax note",
            "related_trade_id": sell["id"],
        },
    )
    assert manual.status_code == 201
    assert manual.json()["origin"] == "manual"

    deleted = client.delete(f"/api/v1/trades/{sell['id']}")
    assert deleted.status_code == 409
    assert sorted(e["origin"] for e in client.get("/api/v1/tax-events").json()) == [
        "automatic_trade",
        "manual",
    ]
    assert client.get(f"/api/v1/trades/{sell['id']}").status_code == 200


def test_deleting_income_event_with_tax_link_is_409_until_explicitly_unlinked(client):
    security = client.post(
        "/api/v1/securities",
        json={"ticker": "DIV.MI", "name": "Dividend", "type": "stock", "currency": "EUR"},
    ).json()
    cash = client.post(
        "/api/v1/accounts",
        json={
            "name": "Dividend cash",
            "type": "checking",
            "opened_on": "2000-01-01",
        },
    ).json()
    investment = client.post(
        "/api/v1/accounts",
        json={
            "name": "Dividend investment account",
            "type": "investment",
            "reference_account_id": cash["id"],
            "opened_on": "2000-01-01",
        },
    ).json()
    income = client.post(
        "/api/v1/income-events",
        json={
            "security_id": security["id"],
            "account_id": investment["id"],
            "event_type": "dividend",
            "payment_date": "2026-05-01",
            "total_amount": 100,
            "currency": "EUR",
        },
    ).json()
    tax = client.post(
        "/api/v1/tax-events",
        json={
            "event_date": "2026-05-01",
            "event_type": "withholding",
            "description": "Dividend tax note",
            "related_income_id": income["id"],
        },
    ).json()

    blocked = client.delete(f"/api/v1/income-events/{income['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["tax_event_ids"] == [tax["id"]]
    assert blocked.json()["detail"]["tax_event_origins"] == ["manual"]
    assert len(client.get("/api/v1/income-events").json()) == 1
    assert client.get("/api/v1/transactions").json()["total"] == 1

    unlinked = client.put(
        f"/api/v1/tax-events/{tax['id']}",
        json={"related_income_id": None},
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["related_income_id"] is None

    deleted = client.delete(f"/api/v1/income-events/{income['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/income-events").json() == []
    assert client.get("/api/v1/transactions").json()["total"] == 0
    remaining_tax = client.get("/api/v1/tax-events").json()
    assert len(remaining_tax) == 1
    assert remaining_tax[0]["id"] == tax["id"]
