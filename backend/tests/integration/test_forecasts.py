"""Integration tests: forecast scenarios (specification §6.9, §10)."""

import json
from decimal import Decimal

import pytest

from app.models.forecast_scenario import ForecastScenario
from app.services.forecast_service import ForecastService
from tests.integration.conftest import TestingSessionLocal


def _scenario_payload(**overrides):
    payload = {
        "name": "Test scenario",
        "base_date": "2026-01-01",
        "horizon_years": 3,
        "parameters": {
            "starting_net_worth": "auto",
            "cash_flow": {
                "monthly_income": 3000,
                "monthly_expenses": 2000,
                "income_growth_rate_annual": 0,
                "expense_growth_rate_annual": 0,
            },
            "portfolio": {
                "expected_annual_return": 0.07,
                "return_optimistic": 0.10,
                "return_pessimistic": 0.04,
            },
            "contributions": [],
        },
    }
    payload.update(overrides)
    return payload


def test_create_and_get_scenario(client):
    resp = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload())
    assert resp.status_code == 201
    scenario = resp.json()
    assert scenario["name"] == "Test scenario"

    get_resp = client.get(f"/api/v1/forecasts/scenarios/{scenario['id']}")
    assert get_resp.status_code == 200


def test_run_scenario_with_auto_starting_net_worth(client):
    client.post(
        "/api/v1/accounts", json={"name": "Account", "type": "checking", "opening_balance": 5000}
    )
    scenario = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload()).json()

    resp = client.post(f"/api/v1/forecasts/run/{scenario['id']}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["scenarios"].keys()) == {"pessimistic", "base", "optimistic"}

    year1_base = body["scenarios"]["base"]["years"][0]
    # No existing portfolio: starting_portfolio_value=0, so
    # year-1 portfolio_value = 0*1.07 + 12000 (automatic savings) = 12000
    assert float(year1_base["portfolio_value"]) == 12000.0
    # Cash stays at 5000 (the entire flow is invested)
    assert float(year1_base["cash_balance"]) == 5000.0


def test_run_scenario_not_found_returns_404(client):
    resp = client.post("/api/v1/forecasts/run/9999")
    assert resp.status_code == 404


def test_compare_scenarios(client):
    s1 = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload(name="S1")).json()
    s2 = client.post(
        "/api/v1/forecasts/scenarios",
        json=_scenario_payload(name="S2", horizon_years=5),
    ).json()

    resp = client.post("/api/v1/forecasts/compare", json={"scenario_ids": [s1["id"], s2["id"]]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 2


def test_compare_requires_at_least_two(client):
    s1 = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload()).json()
    resp = client.post("/api/v1/forecasts/compare", json={"scenario_ids": [s1["id"]]})
    assert resp.status_code == 422  # Pydantic min_length violation


def test_delete_scenario(client):
    scenario = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload()).json()
    resp = client.delete(f"/api/v1/forecasts/scenarios/{scenario['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/v1/forecasts/scenarios/{scenario['id']}").status_code == 404


def test_scenario_with_explicit_starting_net_worth(client):
    """An explicit numeric starting_net_worth is allocated entirely to cash (not auto)."""
    payload = _scenario_payload()
    payload["parameters"]["starting_net_worth"] = 50000
    scenario = client.post("/api/v1/forecasts/scenarios", json=payload).json()
    resp = client.post(f"/api/v1/forecasts/run/{scenario['id']}")
    year1 = resp.json()["scenarios"]["base"]["years"][0]
    # Opening cash 50000 + invested flow 12000: cash stays 50000, portfolio = 0*1.07+12000=12000
    assert float(year1["cash_balance"]) == 50000.0
    assert float(year1["portfolio_value"]) == 12000.0


@pytest.mark.parametrize(
    "starting", ["", " ", "abc", "NaN", "sNaN", "Infinity", "-Infinity", True, False, None, [], {}]
)
def test_invalid_starting_net_worth_is_rejected_without_insert(client, starting):
    payload = _scenario_payload()
    payload["parameters"]["starting_net_worth"] = starting
    response = client.post("/api/v1/forecasts/scenarios", json=payload)
    assert response.status_code == 422
    assert client.get("/api/v1/forecasts/scenarios").json() == []


@pytest.mark.parametrize("starting", [0, "0", -500, "-500.25", "1500.125", 1500.125])
def test_finite_starting_amounts_remain_cash_and_do_not_read_live_values(
    client, monkeypatch, starting
):
    def unexpected_auto_resolution(*args, **kwargs):
        pytest.fail("An explicit amount must not resolve automatic net worth")

    monkeypatch.setattr(
        "app.services.account_service.AccountService.list_accounts", unexpected_auto_resolution
    )
    payload = _scenario_payload()
    payload["parameters"]["starting_net_worth"] = starting
    response = client.post("/api/v1/forecasts/scenarios", json=payload)
    assert response.status_code == 201
    result = client.post(f"/api/v1/forecasts/run/{response.json()['id']}")
    assert result.status_code == 200
    for scenario in result.json()["scenarios"].values():
        assert Decimal(scenario["years"][0]["cash_balance"]) == Decimal(str(starting))
        assert Decimal(scenario["years"][0]["portfolio_value"]) == 12000


def _replace_saved_parameters(scenario_id, parameters):
    """Simulate a historical record only in the fixture's in-memory database."""
    serialized = json.dumps(parameters)
    with TestingSessionLocal() as db:
        scenario = db.get(ForecastScenario, scenario_id)
        scenario.parameters = serialized
        db.commit()
    return serialized


@pytest.mark.parametrize("starting", ["abc", "NaN", "Infinity", True])
def test_invalid_legacy_scenario_stays_readable_and_execution_identifies_field(
    client, monkeypatch, starting
):
    payload = _scenario_payload()
    scenario = client.post("/api/v1/forecasts/scenarios", json=payload).json()
    payload["parameters"]["starting_net_worth"] = starting
    saved = _replace_saved_parameters(scenario["id"], payload["parameters"])

    def unexpected_resolution(*args, **kwargs):
        pytest.fail("Validation must precede net-worth resolution")

    monkeypatch.setattr(ForecastService, "_resolve_starting_values", unexpected_resolution)
    assert client.get("/api/v1/forecasts/scenarios").status_code == 200
    read = client.get(f"/api/v1/forecasts/scenarios/{scenario['id']}")
    assert read.json()["parameters"]["starting_net_worth"] == starting
    result = client.post(f"/api/v1/forecasts/run/{scenario['id']}")
    assert result.status_code == 400
    assert result.json()["error_code"] == "VALIDATION_ERROR"
    assert result.json()["detail"] == {
        "scenario_id": scenario["id"],
        "fields": ["parameters.starting_net_worth"],
    }
    assert str(scenario["id"]) in result.json()["message"]
    with TestingSessionLocal() as db:
        assert db.get(ForecastScenario, scenario["id"]).parameters == saved


def test_compare_validates_all_scenarios_before_running_and_identifies_invalid_one(
    client, monkeypatch
):
    first = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload(name="Valid")).json()
    second = client.post(
        "/api/v1/forecasts/scenarios", json=_scenario_payload(name="Legacy")
    ).json()
    parameters = second["parameters"]
    parameters["starting_net_worth"] = "text"
    _replace_saved_parameters(second["id"], parameters)

    def unexpected_execution(*args, **kwargs):
        pytest.fail("An invalid comparison must not run even the valid scenario")

    monkeypatch.setattr(ForecastService, "_run_validated_scenario", unexpected_execution)
    result = client.post(
        "/api/v1/forecasts/compare", json={"scenario_ids": [first["id"], second["id"]]}
    )
    assert result.status_code == 400
    assert "results" not in result.json()
    assert result.json()["detail"]["scenario_id"] == second["id"]
    assert "Legacy" in result.json()["message"]


def test_legacy_extra_fields_remain_readable_and_ignored_during_execution(client):
    scenario = client.post("/api/v1/forecasts/scenarios", json=_scenario_payload()).json()
    before = client.post(f"/api/v1/forecasts/run/{scenario['id']}").json()
    parameters = scenario["parameters"]
    parameters["portfolio"].update(include_dividends=False, dividend_reinvestment=False)
    parameters["historical_field"] = {"value": "retained"}
    saved = _replace_saved_parameters(scenario["id"], parameters)
    after = client.post(f"/api/v1/forecasts/run/{scenario['id']}")
    assert after.status_code == 200
    assert after.json() == before
    assert (
        client.get(f"/api/v1/forecasts/scenarios/{scenario['id']}").json()["parameters"]
        == parameters
    )
    with TestingSessionLocal() as db:
        assert db.get(ForecastScenario, scenario["id"]).parameters == saved


def test_api_contributions_use_anniversary_periods(client):
    payload = _scenario_payload(base_date="2026-06-01", horizon_years=1)
    payload["parameters"]["starting_net_worth"] = 0
    payload["parameters"]["contributions"] = [
        {"date": "2026-06-01", "amount": 99999, "label": "Already in net worth"},
        {"date": "2026-09-01", "amount": 100, "label": "Within period"},
        {"date": "2027-06-01", "amount": -20, "label": "At endpoint"},
        {"date": "2027-06-02", "amount": 99999, "label": "Outside period"},
    ]
    scenario = client.post("/api/v1/forecasts/scenarios", json=payload).json()
    result = client.post(f"/api/v1/forecasts/run/{scenario['id']}")
    assert result.status_code == 200
    for projection in result.json()["scenarios"].values():
        assert projection["years"][0]["date"] == "2027-06-01"
        assert Decimal(projection["years"][0]["net_worth"]) == 12080
