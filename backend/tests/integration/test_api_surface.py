"""API surface: explicitly document what exists and what does not.

This serves two purposes:

1. Removed duplicate or unused endpoints must stay removed. A test fails
   if a future change accidentally reintroduces them.
2. Exceptions have reasons. Some resources retain updates and others do
   not; the choice and its rationale are documented alongside the tests.
"""

import pytest

# Resources where updates were REMOVED: correct records by deleting and
# recreating them. Fewer ways to do the same thing, and no update path
# to maintain alongside creation.
RESOURCES_WITHOUT_UPDATE = [
    "/api/v1/transactions/1",
    "/api/v1/trades/1",
    "/api/v1/categories/1",
    "/api/v1/income-events/1",
    "/api/v1/portfolio-costs/1",
    "/api/v1/csv-import-profiles/1",
    "/api/v1/forecasts/scenarios/1",
]

# Endpoints removed because they exactly duplicated another endpoint.
REMOVED_DUPLICATES = [
    # returned the same response as GET /income-events
    "/api/v1/income-events/calendar",
    # exact alias of GET /performance/portfolio
    "/api/v1/reports/portfolio-performance",
    # accountant statement: its aggregates duplicated those of
    # costs-analysis, with one inconsistent value as well
    "/api/v1/reports/tax-register",
]


@pytest.mark.parametrize("path", RESOURCES_WITHOUT_UPDATE)
def test_update_is_not_exposed(client, path):
    """405 (not 404): the route exists for GET/DELETE, but does not accept PUT."""
    assert client.put(path, json={}).status_code == 405


@pytest.mark.parametrize("path", REMOVED_DUPLICATES)
def test_removed_duplicates_are_gone(client, path):
    """404 or 405 depending on the route shape: `/…/calendar` matches `/…/{id}`, which still exists for DELETE. In either case, reading is no longer supported, which is what matters."""
    assert client.get(path).status_code in (404, 405)


def test_the_endpoint_that_replaced_the_alias_still_works(client):
    """Removing the alias must not also remove the original."""
    assert client.get("/api/v1/performance/portfolio").status_code == 200


class TestUpdateThatSurvives:
    """Three exceptions, each with a reason worth reviewing."""

    def test_accounts_keep_update(self, client):
        """An investment account's reference account is changed in Settings. Without updates, the account would have to be deleted and recreated, losing its history."""
        account = client.post(
            "/api/v1/accounts", json={"name": "Checking", "type": "checking"}
        ).json()
        resp = client.put(
            f"/api/v1/accounts/{account['id']}", json={"name": "Renamed checking account"}
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed checking account"

    def test_tax_settings_keep_update(self, client):
        """Tax rates are configuration values: changing them IS the only supported operation (§11.3); there is no create-rate operation."""
        resp = client.put("/api/v1/tax-settings/capital_gains_tax_rate", json={"value": "26.50"})
        assert resp.status_code == 200

    def test_tax_events_keep_update(self, client):
        """The specification declares the tax register EDITABLE (§11.1): the user must be able to correct an entry."""
        event = client.post(
            "/api/v1/tax-events",
            json={
                "event_date": "2026-05-01",
                "event_type": "other",
                "description": "Manual entry",
                "gross_amount": 100,
            },
        ).json()
        resp = client.put(
            f"/api/v1/tax-events/{event['id']}", json={"description": "Corrected entry"}
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Corrected entry"

    def test_securities_keep_update(self, client):
        """This is the only way to deactivate a security, already exposed through `GET /securities?only_active=true`. Removing it would leave a filter that can never be triggered."""
        security = client.post(
            "/api/v1/securities",
            json={"ticker": "AAA", "name": "AAA", "type": "stock", "currency": "EUR"},
        ).json()
        resp = client.put(f"/api/v1/securities/{security['id']}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert client.get("/api/v1/securities?only_active=true").json() == []
