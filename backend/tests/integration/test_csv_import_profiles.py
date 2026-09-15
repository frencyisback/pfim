"""CSV import profiles (specification §8.1).

These column-mapping templates are saved in Settings so users do not need
to redefine their bank statement layout for every import.

This was the only API resource with no tests: an unimported type name in
the service could not be detected because no test traversed that file.
"""

from app.models.csv_import_profile import CsvImportProfile
from tests.integration.conftest import TestingSessionLocal


def _profile(**overrides) -> dict:
    payload = {
        "name": "Example Bank",
        "delimiter": ";",
        "skip_rows": 1,
        "date_format": "%d/%m/%Y",
        "date_column": "Date",
        "description_column": "Description",
        "amount_column": "Amount",
        "category_column": "Category",
        "decimal_separator": ",",
        "default_currency": "EUR",
    }
    payload.update(overrides)
    return payload


def test_create_and_list(client):
    resp = client.post("/api/v1/csv-import-profiles", json=_profile())

    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "Example Bank"
    assert created["delimiter"] == ";"
    assert created["decimal_separator"] == ","
    assert created["skip_rows"] == 1

    listed = client.get("/api/v1/csv-import-profiles").json()
    assert [p["id"] for p in listed] == [created["id"]]


def test_defaults_apply_when_only_name_and_required_category_mapping_are_given(client):
    resp = client.post(
        "/api/v1/csv-import-profiles",
        json={"name": "Minimal", "category_column": "category"},
    )

    assert resp.status_code == 201
    created = resp.json()
    assert created["delimiter"] == ","
    assert created["date_format"] == "%Y-%m-%d"
    assert created["decimal_separator"] == "."
    assert created["default_currency"] == "EUR"
    assert created["category_column"] == "category"


def test_new_profile_requires_a_category_mapping(client):
    response = client.post("/api/v1/csv-import-profiles", json={"name": "Without category"})

    assert response.status_code == 422


def test_new_profile_rejects_blank_mapping_and_trims_a_valid_one(client):
    blank = client.post(
        "/api/v1/csv-import-profiles",
        json={"name": "Empty", "category_column": "   "},
    )
    trimmed = client.post(
        "/api/v1/csv-import-profiles",
        json={"name": "Trim", "category_column": "  Category  "},
    )

    assert blank.status_code == 422
    assert trimmed.status_code == 201
    assert trimmed.json()["category_column"] == "Category"


def test_legacy_profile_with_null_category_mapping_remains_readable(client):
    db = TestingSessionLocal()
    try:
        legacy = CsvImportProfile(name="Legacy", category_column=None)
        db.add(legacy)
        db.commit()
        db.refresh(legacy)
        legacy_id = legacy.id
    finally:
        db.close()

    response = client.get("/api/v1/csv-import-profiles")

    assert response.status_code == 200
    item = next(profile for profile in response.json() if profile["id"] == legacy_id)
    assert item["category_column"] is None


def test_duplicate_name_is_rejected(client):
    """The name identifies the profile in the menu: two profiles with the same name would make the choice ambiguous."""
    client.post("/api/v1/csv-import-profiles", json=_profile())
    resp = client.post("/api/v1/csv-import-profiles", json=_profile())

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "CONFLICT"


def test_duplicate_name_check_ignores_case(client):
    client.post("/api/v1/csv-import-profiles", json=_profile(name="Example Bank"))
    resp = client.post("/api/v1/csv-import-profiles", json=_profile(name="example bank"))

    assert resp.status_code == 409


def test_delete(client):
    created = client.post("/api/v1/csv-import-profiles", json=_profile()).json()

    assert client.delete(f"/api/v1/csv-import-profiles/{created['id']}").status_code == 204
    assert client.get("/api/v1/csv-import-profiles").json() == []


def test_delete_of_a_missing_profile_returns_404(client):
    assert client.delete("/api/v1/csv-import-profiles/9999").status_code == 404


def test_the_service_annotations_resolve(client):
    """The payload type was annotated but never imported. Runtime did not fail because annotations were not evaluated, but tools that read them (documentation, type checks, introspection) found an undefined name. This test actually evaluates them."""
    import typing

    from app.services.csv_import_profile_service import CsvImportProfileService

    hints = typing.get_type_hints(CsvImportProfileService.create_profile)
    assert hints["data"].__name__ == "CsvImportProfileCreate"
