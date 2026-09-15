"""R-08/R-11 regression tests: numeric imports and fail-closed CSV uploads."""

from __future__ import annotations

import io
from decimal import Decimal

from app.config import settings


def _security(client, ticker: str = "IMPORT", currency: str = "EUR") -> int:
    response = client.post(
        "/api/v1/securities",
        json={
            "ticker": ticker,
            "name": f"Security {ticker}",
            "type": "stock",
            "currency": currency,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload(client, path: str, content: str | bytes):
    encoded = content.encode() if isinstance(content, str) else content
    return client.post(
        path,
        files={"file": ("input.csv", io.BytesIO(encoded), "text/csv")},
    )


def _rates_by_date(client, date: str) -> dict[tuple[str, str], tuple[Decimal, str]]:
    return {
        (row["from_currency"], row["to_currency"]): (
            Decimal(row["rate"]),
            row["source"],
        )
        for row in client.get("/api/v1/fx-rates").json()
        if row["date"] == date
    }


def test_price_preview_and_import_reject_the_same_nonpositive_and_nonfinite_rows(client):
    security_id = _security(client)
    csv = (
        "date;ticker;close\n"
        "2026-01-01;IMPORT;0\n"
        "2026-01-02;IMPORT;-1\n"
        "2026-01-03;IMPORT;NaN\n"
        "2026-01-04;IMPORT;Infinity\n"
        "2026-01-05;IMPORT;-Infinity\n"
        "2026-01-06;IMPORT;text\n"
        "2026-01-07;IMPORT;10\n"
    )

    preview = _upload(client, "/api/v1/prices/import/preview", csv)
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["total_rows"] == 7
    assert preview_body["error_rows"] == 6
    assert preview_body["new_rows"] == 1
    assert [bool(row["errors"]) for row in preview_body["rows"]] == [
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    ]

    imported = _upload(client, "/api/v1/prices/import", csv)
    assert imported.status_code == 200
    assert imported.json() == {
        "imported": 1,
        "updated": 0,
        "skipped_unrecognized_ticker": 0,
        "errors": 6,
    }
    history = client.get(f"/api/v1/prices/{security_id}").json()
    assert [(row["date"], Decimal(row["price_close"])) for row in history] == [
        ("2026-01-07", Decimal("10"))
    ]


def test_price_preview_and_import_agree_on_an_invalid_textual_fx_rate(client):
    security_id = _security(client, "USDSEC", "USD")
    csv = "date;ticker;close;fx_rate\n2026-01-01;USDSEC;10;not-a-number\n"

    preview = _upload(client, "/api/v1/prices/import/preview", csv)
    assert preview.status_code == 200
    assert preview.json()["error_rows"] == 1
    assert preview.json()["rows"][0]["errors"]

    imported = _upload(client, "/api/v1/prices/import", csv)
    assert imported.status_code == 200
    assert imported.json()["errors"] == 1
    assert imported.json()["imported"] == 0
    assert client.get(f"/api/v1/prices/{security_id}").json() == []


def test_price_preview_and_import_give_parse_errors_precedence_over_unknown_tickers(client):
    csv = "date;ticker;close;fx_rate\n2026-01-01;UNKNOWN;10;not-a-number\n"

    preview = _upload(client, "/api/v1/prices/import/preview", csv)
    assert preview.status_code == 200
    assert preview.json()["error_rows"] == 1
    assert preview.json()["skipped_unrecognized_ticker"] == 0
    assert preview.json()["rows"][0]["errors"] == ["Invalid exchange rate"]

    imported = _upload(client, "/api/v1/prices/import", csv)
    assert imported.status_code == 200
    assert imported.json() == {
        "imported": 0,
        "updated": 0,
        "skipped_unrecognized_ticker": 0,
        "errors": 1,
    }


def test_manual_price_rejects_nonfinite_values_before_the_database(client):
    security_id = _security(client)
    for value in ("NaN", "Infinity", "-Infinity"):
        response = client.post(
            "/api/v1/prices",
            json={
                "security_id": security_id,
                "date": "2026-01-01",
                "price_close": value,
            },
        )
        assert response.status_code == 422
    assert client.get(f"/api/v1/prices/{security_id}").json() == []


def test_manual_price_uses_normalized_price_and_fx_for_the_eur_value(client):
    security_id = _security(client, "PRECISE", "USD")
    response = client.post(
        "/api/v1/prices",
        json={
            "security_id": security_id,
            "date": "2026-01-01",
            "price_close": "100.0000005",
            "fx_rate": "0.123456789",
        },
    )

    assert response.status_code == 201, response.text
    stored = client.get(f"/api/v1/prices/{security_id}").json()[0]
    assert Decimal(stored["price_close"]) == Decimal("100.000000")
    assert Decimal(stored["fx_rate"]) == Decimal("0.12345679")
    assert Decimal(stored["price_close_eur"]) == Decimal("12.345679")


def test_fx_import_rejects_invalid_rates_and_updates_only_generated_reciprocals(client):
    invalid = (
        "date;from;to;rate\n"
        "2026-01-01;USD;EUR;0\n"
        "2026-01-02;USD;EUR;-1\n"
        "2026-01-03;USD;EUR;NaN\n"
        "2026-01-04;USD;EUR;Infinity\n"
        "2026-01-05;USD;EUR;text\n"
    )
    invalid_response = _upload(client, "/api/v1/fx-rates/import", invalid)
    assert invalid_response.status_code == 200
    assert invalid_response.json()["imported"] == 0
    assert invalid_response.json()["errors"] == 5
    assert client.get("/api/v1/fx-rates").json() == []

    first = _upload(
        client,
        "/api/v1/fx-rates/import",
        "date;from;to;rate\n2026-02-01;USD;EUR;0.8\n",
    ).json()
    assert first["reciprocal_created"] == 1
    assert first["reciprocal_updated"] == 0
    assert _rates_by_date(client, "2026-02-01") == {
        ("USD", "EUR"): (Decimal("0.8"), "csv_import"),
        ("EUR", "USD"): (Decimal("1.25"), "csv_import_reciprocal"),
    }

    updated = _upload(
        client,
        "/api/v1/fx-rates/import",
        "date;from;to;rate\n2026-02-01;USD;EUR;0.5\n",
    ).json()
    assert updated["reciprocal_created"] == 0
    assert updated["reciprocal_updated"] == 1
    assert _rates_by_date(client, "2026-02-01") == {
        ("USD", "EUR"): (Decimal("0.5"), "csv_import"),
        ("EUR", "USD"): (Decimal("2"), "csv_import_reciprocal"),
    }


def test_fx_import_normalizes_direct_and_reciprocal_before_storage(client):
    body = _upload(
        client,
        "/api/v1/fx-rates/import",
        "date;from;to;rate\n2026-02-10;USD;EUR;0.123456789\n",
    ).json()

    assert body["imported"] == 1
    assert body["reciprocal_created"] == 1
    assert body["errors"] == 0
    assert _rates_by_date(client, "2026-02-10") == {
        ("USD", "EUR"): (Decimal("0.12345679"), "csv_import"),
        ("EUR", "USD"): (Decimal("8.10000001"), "csv_import_reciprocal"),
    }


def test_explicit_fx_pairs_are_order_independent_and_never_overwrite_each_other(client):
    header = "date;from;to;rate\n"
    first_order = header + "2026-03-01;USD;EUR;0.8\n2026-03-01;EUR;USD;1.25\n"
    reverse_order = header + "2026-03-02;EUR;USD;1.25\n2026-03-02;USD;EUR;0.8\n"
    for csv in (first_order, reverse_order):
        body = _upload(client, "/api/v1/fx-rates/import", csv).json()
        assert body["imported"] == 2
        assert body["errors"] == 0
        assert body["reciprocal_calculated"] == 0

    expected = {
        ("USD", "EUR"): (Decimal("0.8"), "csv_import"),
        ("EUR", "USD"): (Decimal("1.25"), "csv_import"),
    }
    assert _rates_by_date(client, "2026-03-01") == expected
    assert _rates_by_date(client, "2026-03-02") == expected

    inconsistent = _upload(
        client,
        "/api/v1/fx-rates/import",
        header + "2026-03-03;USD;EUR;0.8\n2026-03-03;EUR;USD;1.3\n",
    ).json()
    assert inconsistent["imported"] == 0
    assert inconsistent["errors"] == 2
    assert _rates_by_date(client, "2026-03-03") == {}

    # Both directions on January 3 are explicit. An inconsistent isolated
    # update is rejected without overwriting either direction.
    conflict = _upload(
        client,
        "/api/v1/fx-rates/import",
        header + "2026-03-01;USD;EUR;0.5\n",
    ).json()
    assert conflict["imported"] == 0
    assert conflict["errors"] == 1
    assert _rates_by_date(client, "2026-03-01") == expected


def test_upload_byte_encoding_and_row_limits_are_structured_and_write_nothing(client, monkeypatch):
    security_id = _security(client)
    monkeypatch.setattr(settings, "csv_upload_max_bytes", 32)
    too_large = _upload(
        client,
        "/api/v1/prices/import",
        "date;ticker;close\n2026-01-01;IMPORT;10\n",
    )
    assert too_large.status_code == 413
    assert too_large.json()["error_code"] == "PAYLOAD_TOO_LARGE"
    assert client.get(f"/api/v1/prices/{security_id}").json() == []

    monkeypatch.setattr(settings, "csv_upload_max_bytes", 1024)
    invalid_utf8 = _upload(client, "/api/v1/prices/import", b"\xff\xfe\x00")
    assert invalid_utf8.status_code == 400
    assert invalid_utf8.json()["error_code"] == "VALIDATION_ERROR"

    malformed = _upload(
        client,
        "/api/v1/prices/import",
        b'date;ticker;close\n"2026-01-01;IMPORT;10\n',
    )
    assert malformed.status_code == 400
    assert malformed.json()["error_code"] == "VALIDATION_ERROR"
    assert client.get(f"/api/v1/prices/{security_id}").json() == []

    monkeypatch.setattr(settings, "csv_import_max_rows", 1)
    two_rows = "date;ticker;close\n" "2026-01-01;IMPORT;10\n" "2026-01-02;IMPORT;11\n"
    row_limit = _upload(client, "/api/v1/prices/import", two_rows)
    assert row_limit.status_code == 413
    assert row_limit.json()["detail"]["max_rows"] == 1
    assert client.get(f"/api/v1/prices/{security_id}").json() == []


def test_paginated_preview_counts_errors_across_pages_and_rejects_bad_delimiters(client):
    account = client.post(
        "/api/v1/accounts",
        json={"name": "Account import", "type": "checking", "opened_on": "2000-01-01"},
    ).json()
    client.post("/api/v1/categories", json={"name": "Expense", "type": "expense"})
    csv = (
        "date,description,amount,category\n"
        "2026-01-01,One,-1,Expense\n"
        "2026-01-02,Due,-2,Unknown\n"
        "2026-01-03,Three,-3,Expense\n"
    )
    response = client.post(
        "/api/v1/transactions/import/preview?page=1&page_size=1",
        files={"file": ("cashflow.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={"account_id": account["id"], "category_column": "category"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 1
    assert body["total_pages"] == 3
    assert body["error_rows"] == 1
    assert body["rows"][0]["errors"] == []

    bad_delimiter = client.post(
        "/api/v1/transactions/import/preview",
        files={"file": ("cashflow.csv", io.BytesIO(csv.encode()), "text/csv")},
        data={
            "account_id": account["id"],
            "category_column": "category",
            "delimiter": "\n",
        },
    )
    assert bad_delimiter.status_code in {400, 422}
    if bad_delimiter.status_code == 400:
        assert bad_delimiter.json()["error_code"] == "VALIDATION_ERROR"
