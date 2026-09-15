"""A11/A12: truncated cells, partial imports, and sequential previews without writes."""

import io
from decimal import Decimal

import pytest

from app.repositories.fx_rate_repo import FxRateRepository
from app.repositories.price_repo import PriceRepository


def _upload(client, path, content):
    return client.post(
        path, files={"file": ("input.csv", io.BytesIO(content.encode()), "text/csv")}
    )


def _security(client, currency="EUR"):
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": "CELL",
            "isin": "IT0000000001",
            "name": "Cells",
            "type": "stock",
            "currency": currency,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    "invalid",
    [
        "2026-01-01",
        "2026-01-01;CELL",
        ";CELL;10",
        "2026-01-01;;10",
        "2026-01-01;CELL;",
        "2026-01-01;UNKNOWN",
    ],
)
def test_truncated_price_rows_are_errors_and_other_rows_are_committed(client, invalid):
    security_id = _security(client)
    content = f"date;ticker;close;fx_rate\n{invalid}\n2026-01-02;CELL;12\n"
    preview = _upload(client, "/api/v1/prices/import/preview", content)
    assert preview.status_code == 200, preview.text
    assert preview.json()["error_rows"] == 1
    assert preview.json()["skipped_unrecognized_ticker"] == 0
    assert preview.json()["rows"][0]["errors"]
    assert client.get(f"/api/v1/prices/{security_id}").json() == []
    result = _upload(client, "/api/v1/prices/import", content)
    assert result.status_code == 200, result.text
    assert result.json() == {
        "imported": 1,
        "updated": 0,
        "errors": 1,
        "skipped_unrecognized_ticker": 0,
    }
    assert len(client.get(f"/api/v1/prices/{security_id}").json()) == 1


def test_missing_optional_fx_is_valid_only_for_eur(client):
    security_id = _security(client, "USD")
    content = "date;ticker;close;fx_rate\n2026-01-01;CELL;12\n2026-01-02;CELL;12;0.9\n"
    preview = _upload(client, "/api/v1/prices/import/preview", content).json()
    result = _upload(client, "/api/v1/prices/import", content).json()
    assert preview["error_rows"] == result["errors"] == 1
    assert preview["new_rows"] == result["imported"] == 1
    history = client.get(f"/api/v1/prices/{security_id}").json()
    assert Decimal(history[0]["price_close_eur"]) == Decimal("10.8")


@pytest.mark.parametrize(
    "path", ["/api/v1/prices/import/preview", "/api/v1/prices/import", "/api/v1/fx-rates/import"]
)
@pytest.mark.parametrize("header", ['"date;ticker;close\n', "", "date;other\n2026-01-01;10\n"])
def test_malformed_or_missing_headers_are_structured_errors(client, path, header):
    response = _upload(client, path, header)
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "invalid,columns",
    [
        ("2026-01-01", {"from", "to", "rate"}),
        ("2026-01-01;USD", {"to", "rate"}),
        ("2026-01-01;USD;EUR", {"rate"}),
        (";USD;EUR;1", {"date"}),
        ("2026-01-01;;EUR;1", {"from"}),
        ("2026-01-01;USD;EUR;", {"rate"}),
    ],
)
def test_fx_reports_missing_columns_without_discarding_valid_rows(client, invalid, columns):
    response = _upload(
        client, "/api/v1/fx-rates/import", f"date;from;to;rate\n{invalid}\n2026-01-02;USD;EUR;0.8\n"
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["errors"] == 1
    assert result["imported"] == 1
    assert result["reciprocal_calculated"] == 1
    assert {error["column"] for error in result["row_errors"]} == columns
    assert {error["row_number"] for error in result["row_errors"]} == {1}
    assert all(error["message"] for error in result["row_errors"])
    assert len(client.get("/api/v1/fx-rates").json()) == 2


def test_fx_duplicate_policy_stays_reject_all_and_explains_rows(client):
    result = _upload(
        client,
        "/api/v1/fx-rates/import",
        "date;from;to;rate\n2026-01-01;USD;EUR;0.8\n2026-01-01;USD;EUR;0.8\n",
    ).json()
    assert result["imported"] == 0
    assert result["errors"] == 2
    assert {error["row_number"] for error in result["row_errors"]} == {1, 2}
    assert all("Duplicate direction" in error["message"] for error in result["row_errors"])


@pytest.mark.parametrize("existing", [False, True])
def test_price_preview_simulates_aliases_and_duplicates_across_pages(client, existing):
    security_id = _security(client)
    if existing:
        assert (
            client.post(
                "/api/v1/prices",
                json={"security_id": security_id, "date": "2026-01-01", "price_close": "5"},
            ).status_code
            == 201
        )
    content = "date;ticker;close\n2026-01-01;CELL;10\n2026-01-01;IT0000000001;11\n2026-01-01;CELL;11\n2026-01-01;CELL;bad\n2026-01-01;UNKNOWN;99\n"
    pages = [
        _upload(client, f"/api/v1/prices/import/preview?page={page}&page_size=1", content).json()
        for page in range(1, 6)
    ]
    for page in pages:
        assert page["new_rows"] == (0 if existing else 1)
        assert page["update_rows"] == (3 if existing else 2)
        assert page["error_rows"] == 1
        assert page["skipped_unrecognized_ticker"] == 1
    rows = [page["rows"][0] for page in pages]
    assert [row["is_update"] for row in rows[:3]] == [existing, True, True]
    for row in rows[:3]:
        assert row["final_row_number"] == 3
        assert Decimal(row["final_close"]) == Decimal("11")
    assert rows[0]["superseded_by_row"] == rows[1]["superseded_by_row"] == 3
    assert rows[2]["superseded_by_row"] is None
    assert rows[3]["final_row_number"] is None
    assert len(client.get(f"/api/v1/prices/{security_id}").json()) == int(existing)
    result = _upload(client, "/api/v1/prices/import", content).json()
    assert result["imported"] == pages[0]["new_rows"]
    assert result["updated"] == pages[0]["update_rows"]
    saved = client.get(f"/api/v1/prices/{security_id}").json()
    assert len(saved) == 1
    assert Decimal(saved[0]["price_close"]) == Decimal("11")
    assert saved[0]["source"] == "csv_import"


def test_unexpected_import_failure_rolls_back_earlier_valid_rows(client, monkeypatch):
    security_id = _security(client)
    original = PriceRepository.upsert
    calls = 0

    def fail_second(self, price):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated error after a valid row")
        return original(self, price)

    monkeypatch.setattr(PriceRepository, "upsert", fail_second)
    with pytest.raises(RuntimeError, match="simulated"):
        _upload(
            client,
            "/api/v1/prices/import",
            "date;ticker;close\n2026-01-01;CELL;10\n2026-01-02;CELL;11\n",
        )
    assert client.get(f"/api/v1/prices/{security_id}").json() == []


def test_unexpected_fx_failure_rolls_back_earlier_valid_rows(client, monkeypatch):
    original = FxRateRepository.upsert
    calls = 0

    def fail_second(self, rate):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated error after a valid exchange rate")
        return original(self, rate)

    monkeypatch.setattr(FxRateRepository, "upsert", fail_second)
    with pytest.raises(RuntimeError, match="simulated"):
        _upload(
            client,
            "/api/v1/fx-rates/import",
            "date;from;to;rate\n2026-01-01;USD;EUR;0.8\n2026-01-02;USD;EUR;0.9\n",
        )
    assert client.get("/api/v1/fx-rates").json() == []


def test_invalid_first_price_does_not_make_the_next_valid_occurrence_an_update(client):
    _security(client, "USD")
    content = "date;ticker;close;fx_rate\n2026-01-01;CELL;10\n2026-01-01;CELL;12;0.9\n"
    preview = _upload(client, "/api/v1/prices/import/preview", content).json()
    assert preview["rows"][0]["errors"]
    assert not preview["rows"][1]["is_update"]
    assert preview["rows"][1]["final_row_number"] is None
    result = _upload(client, "/api/v1/prices/import", content).json()
    assert result["imported"] == preview["new_rows"] == 1
    assert result["updated"] == preview["update_rows"] == 0
