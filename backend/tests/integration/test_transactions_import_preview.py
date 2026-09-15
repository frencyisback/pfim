"""Transaction CSV import preview (specification §8.1, step 4).

Before any writes, users see each row's import status, duplicate status,
and parsing errors. Previously this step lacked all test coverage despite
being the defense between an incorrect file and a persisted statement.

Preview must NEVER write; half the tests verify this.

Like import, preview receives the destination account because the same row
can be a duplicate in one account and new in another
(see test_import_deduplication.py).
"""

import io
from decimal import Decimal

import pytest


def _account(client) -> int:
    return client.post(
        "/api/v1/accounts",
        json={"name": "Checking", "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]


def _category(client, name: str, type_: str) -> None:
    response = client.post("/api/v1/categories", json={"name": name, "type": type_})
    assert response.status_code == 201


def _base_categories(client) -> None:
    _category(client, "Groceries", "expense")
    _category(client, "Salary", "income")


def _upload(client, content: str, path="/api/v1/transactions/import/preview", **form):
    return client.post(
        path,
        files={"file": ("statement.csv", io.BytesIO(content.encode("utf-8")), "text/csv")},
        data=form,
    )


BASE_CSV = (
    "date,description,amount,category\n"
    "2026-01-10,Groceries,-45.30,Groceries\n"
    "2026-01-12,Salary,2500,Salary\n"
)


def test_truncated_cells_preserve_partial_import_and_optional_description(client):
    account_id = _account(client)
    _category(client, "Expense", "expense")
    content = (
        "date,amount,category,description\n"
        "2026-01-01,-10,Expense\n"
        "2026-01-02,-10\n"
        "2026-01-03\n"
        ",-10,Expense\n"
    )
    form = {"account_id": account_id, "category_column": "category"}
    preview = _upload(client, content, **form)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["error_rows"] == 3
    assert body["rows"][0]["description"] is None
    assert body["rows"][0]["errors"] == []
    assert [row["row_number"] for row in body["rows"] if row["errors"]] == [2, 3, 4]
    assert client.get("/api/v1/transactions").json()["total"] == 0
    imported = _upload(client, content, path="/api/v1/transactions/import", **form)
    assert imported.status_code == 200, imported.text
    assert imported.json() == {"imported": 1, "errors": 3, "skipped_duplicates": 0}
    saved = client.get("/api/v1/transactions").json()
    assert saved["total"] == 1
    assert saved["items"][0]["description"] is None
    repeated = _upload(client, content, path="/api/v1/transactions/import", **form)
    assert repeated.json() == {"imported": 0, "errors": 3, "skipped_duplicates": 1}


@pytest.mark.parametrize("content", ['"date,description,amount,category\n', "date,amount\n"])
def test_broken_transaction_header_is_a_global_error_in_both_steps(client, content):
    account_id = _account(client)
    for path in ("/api/v1/transactions/import/preview", "/api/v1/transactions/import"):
        response = _upload(
            client, content, path=path, account_id=account_id, category_column="category"
        )
        assert response.status_code == 400, response.text
        assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/transactions").json()["total"] == 0


def test_preview_and_import_reject_rows_before_account_opening(client):
    account_id = client.post(
        "/api/v1/accounts",
        json={"name": "Recent checking account", "type": "checking", "opened_on": "2026-02-01"},
    ).json()["id"]
    _category(client, "Temporal expense", "expense")
    content = (
        "date,description,amount,category\n" "2026-01-31,Before opening,-10,Temporal expense\n"
    )

    preview = _upload(client, content, account_id=account_id, category_column="category")
    assert preview.status_code == 200
    assert preview.json()["error_rows"] == 1
    assert "is unavailable on" in preview.json()["rows"][0]["errors"][0]

    imported = _upload(
        client,
        content,
        path="/api/v1/transactions/import",
        account_id=account_id,
        category_column="category",
    )
    assert imported.status_code == 200
    assert imported.json() == {"imported": 0, "skipped_duplicates": 0, "errors": 1}
    assert client.get("/api/v1/transactions").json()["total"] == 0


def test_preview_reads_every_row_without_writing_anything(client):
    account_id = _account(client)
    _base_categories(client)

    resp = _upload(client, BASE_CSV, account_id=account_id, category_column="category")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["error_rows"] == 0
    assert body["duplicate_rows"] == 0
    assert [r["description"] for r in body["rows"]] == ["Groceries", "Salary"]
    assert [r["row_number"] for r in body["rows"]] == [1, 2]
    # No transaction created: preview is a read operation.
    assert client.get("/api/v1/transactions").json()["total"] == 0


def test_preview_flags_rows_that_are_already_in_the_database(client):
    """Detect duplicates by account+date+amount+description hash: loading the same statement twice into one account must not double the balance."""
    account_id = _account(client)
    _base_categories(client)
    _upload(
        client,
        BASE_CSV,
        path="/api/v1/transactions/import",
        account_id=account_id,
        category_column="category",
    )

    body = _upload(client, BASE_CSV, account_id=account_id, category_column="category").json()

    assert body["duplicate_rows"] == 2
    assert all(row["is_duplicate"] for row in body["rows"])


def test_preview_reports_unreadable_rows_instead_of_failing(client):
    """A malformed row must not fail the entire file: show its error beside it so the user knows what to correct."""
    account_id = _account(client)
    _category(client, "CSV errors", "expense")
    csv = (
        "date,description,amount,category\n"
        "10/01/2026,Incorrect date format,-10,CSV errors\n"
        ",Without date,-5,CSV errors\n"
    )

    body = _upload(client, csv, account_id=account_id, category_column="category").json()

    assert body["total_rows"] == 2
    assert body["error_rows"] == 2
    assert any("format" in e for e in body["rows"][0]["errors"])
    assert any("missing" in e for e in body["rows"][1]["errors"])


def test_preview_resolves_categories_and_reports_the_missing_ones(client):
    """A CSV category that does not exist blocks the row: creating categories from file text would fill the catalog with typos."""
    account_id = _account(client)
    _category(client, "Expense", "expense")
    csv = (
        "date,description,amount,category\n"
        "2026-01-10,Supermarket,-45.30,expense\n"
        "2026-01-11,Unknown item,-10,Invented category\n"
    )

    body = _upload(client, csv, account_id=account_id, category_column="category").json()

    assert body["rows"][0]["errors"] == []  # case-insensitive comparison
    assert any("not found" in e for e in body["rows"][1]["errors"])


def test_preview_honours_the_declared_format(client):
    """Delimiter, skipped rows, date format, and decimal separator come from the profile. Ignoring them would make every row of an Italian statement unreadable."""
    account_id = _account(client)
    _category(client, "Bills", "expense")
    csv = (
        "Statement - row to skip\n"
        "Date;Description;Amount;Category\n"
        "10/01/2026;Electricity bill;-89,90;Bills\n"
    )

    body = _upload(
        client,
        csv,
        account_id=account_id,
        delimiter=";",
        skip_rows=1,
        date_format="%d/%m/%Y",
        date_column="Date",
        description_column="Description",
        amount_column="Amount",
        category_column="Category",
        decimal_separator=",",
    ).json()

    assert body["error_rows"] == 0
    assert body["rows"][0]["date"] == "2026-01-10"
    assert float(body["rows"][0]["amount"]) == -89.90


def test_preview_refuses_a_foreign_currency_file_without_a_rate(client):
    """Report an error during preview instead of discovering halfway through import that the file cannot be converted (docs/multi-currency.md)."""
    account_id = _account(client)
    _base_categories(client)

    resp = _upload(
        client,
        BASE_CSV,
        account_id=account_id,
        category_column="category",
        default_currency="USD",
    )

    assert resp.status_code == 400
    assert "USD" in resp.json()["message"]


def test_preview_accepts_a_foreign_currency_file_with_a_rate(client):
    account_id = _account(client)
    _base_categories(client)

    resp = _upload(
        client,
        BASE_CSV,
        account_id=account_id,
        category_column="category",
        default_currency="USD",
        fx_rate="0.92",
    )

    assert resp.status_code == 200
    assert resp.json()["error_rows"] == 0


def test_import_applies_the_single_rate_declared_for_the_file(client):
    """A bank statement uses one currency: one exchange rate applies to every row and is frozen on each."""
    account_id = _account(client)
    _base_categories(client)

    result = _upload(
        client,
        BASE_CSV,
        path="/api/v1/transactions/import",
        account_id=account_id,
        category_column="category",
        default_currency="USD",
        fx_rate="0.92",
    ).json()

    assert result["imported"] == 2
    rows = client.get("/api/v1/transactions").json()["items"]
    assert {r["currency"] for r in rows} == {"USD"}
    assert all(float(r["fx_rate"]) == 0.92 for r in rows)
    # -45.30 USD x 0.92 = -41.676 EUR
    spesa = next(r for r in rows if r["description"] == "Groceries")
    assert float(spesa["amount_eur"]) == -41.676


def test_preview_and_import_reject_amounts_not_storable_after_conversion(client):
    account_id = _account(client)
    _category(client, "Microexpense", "expense")
    content = (
        "date,description,amount,category\n"
        "2026-01-10,Amount that would disappear,-0.000001,Microexpense\n"
    )
    form = {
        "account_id": account_id,
        "category_column": "category",
        "default_currency": "USD",
        "fx_rate": "0.00000001",
    }

    preview = _upload(client, content, **form)
    assert preview.status_code == 200
    assert preview.json()["error_rows"] == 1
    assert "EUR equivalent" in preview.json()["rows"][0]["errors"][0]

    imported = _upload(
        client,
        content,
        path="/api/v1/transactions/import",
        **form,
    )
    assert imported.status_code == 200
    assert imported.json() == {"imported": 0, "skipped_duplicates": 0, "errors": 1}
    assert client.get("/api/v1/transactions").json()["total"] == 0


def test_preview_and_import_share_the_canonical_six_decimal_amount(client):
    account_id = _account(client)
    _category(client, "Precise expense", "expense")
    content = (
        "date,description,amount,category\n" "2026-01-10,Microscale,-1.0000005,Precise expense\n"
    )

    preview = _upload(client, content, account_id=account_id, category_column="category")
    assert preview.status_code == 200
    assert Decimal(preview.json()["rows"][0]["amount"]) == Decimal("-1.000000")

    imported = _upload(
        client,
        content,
        path="/api/v1/transactions/import",
        account_id=account_id,
        category_column="category",
    )
    assert imported.json() == {"imported": 1, "skipped_duplicates": 0, "errors": 0}
    stored = client.get("/api/v1/transactions").json()["items"][0]
    assert Decimal(stored["amount"]) == Decimal("-1.000000")
    assert Decimal(stored["amount_eur"]) == Decimal("-1.000000")
