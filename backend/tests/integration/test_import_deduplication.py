"""CSV import deduplication: what counts as an already-seen row.

Two properties missing from the original implementation require a session
configured as in production (see the autoflush note in conftest.py):

1. Within one file, identical rows were not recognized because queries
   searched only the database, where the first row had not arrived yet.
   Both were queued, import_hash uniqueness failed at commit after the
   success response, and HTTP 200 reported {"imported": 2} with zero saved rows.
2. Across accounts, the hash omitted the account, silently dropping the
   same movement imported into a second account. Equal salary or rent
   amounts on separate accounts are ordinary, valid cases.
"""

import io


def _account(client, name: str) -> int:
    return client.post(
        "/api/v1/accounts",
        json={"name": name, "type": "checking", "opened_on": "2000-01-01"},
    ).json()["id"]


def _category(client, name: str, type_: str) -> None:
    response = client.post("/api/v1/categories", json={"name": name, "type": type_})
    assert response.status_code == 201


def _import(client, content: str, account_id: int, **form):
    return client.post(
        "/api/v1/transactions/import",
        files={"file": ("statement.csv", io.BytesIO(content.encode("utf-8")), "text/csv")},
        data={"account_id": account_id, **form},
    )


def _preview(client, content: str, account_id: int, **form):
    return client.post(
        "/api/v1/transactions/import/preview",
        files={"file": ("statement.csv", io.BytesIO(content.encode("utf-8")), "text/csv")},
        data={"account_id": account_id, **form},
    )


TWO_IDENTICAL_ROWS = (
    "date,description,amount,category\n"
    "2026-01-10,Café,-1.50,Expenses\n"
    "2026-01-10,Café,-1.50,Expenses\n"
)


def test_two_identical_rows_in_the_same_file_do_not_lose_the_whole_import(client):
    """The case that lost everything: count the second row as a duplicate instead of queuing it beside the first."""
    account_id = _account(client, "Checking")
    _category(client, "Expenses", "expense")

    result = _import(client, TWO_IDENTICAL_ROWS, account_id, category_column="category").json()

    assert result == {"imported": 1, "skipped_duplicates": 1, "errors": 0}
    # Above all, the response's claimed result must actually exist in the
    # database. Previously, the import announced two rows and saved neither.
    assert client.get("/api/v1/transactions").json()["total"] == 1


def test_the_preview_flags_a_duplicate_row_inside_the_file(client):
    """Preview must agree with import: it is the step on which the user decides whether to confirm."""
    account_id = _account(client, "Checking")
    _category(client, "Expenses", "expense")

    body = _preview(client, TWO_IDENTICAL_ROWS, account_id, category_column="category").json()

    assert body["duplicate_rows"] == 1
    assert [r["is_duplicate"] for r in body["rows"]] == [False, True]


def test_the_same_movement_on_another_account_is_imported_not_skipped(client):
    """Same date, amount, and description, but a different account: a different movement. Previously it silently disappeared, leaving the second account at zero."""
    first_value = _account(client, "Account A")
    second_value = _account(client, "Account B")
    _category(client, "Salary", "income")
    csv = "date,description,amount,category\n2026-02-10,Salary,1500.00,Salary\n"

    assert _import(client, csv, first_value, category_column="category").json()["imported"] == 1
    assert _import(client, csv, second_value, category_column="category").json() == {
        "imported": 1,
        "skipped_duplicates": 0,
        "errors": 0,
    }

    account_balance = client.get(f"/api/v1/accounts/{second_value}/balance").json()
    assert float(account_balance["balance"]) == 1500.00


def test_the_same_file_imported_twice_on_the_same_account_is_still_skipped(client):
    """Required protection: importing the same statement twice into the same account must not double its balance."""
    account_id = _account(client, "Checking")
    _category(client, "Salary", "income")
    csv = "date,description,amount,category\n2026-02-10,Salary,1500.00,Salary\n"

    _import(client, csv, account_id, category_column="category")
    result = _import(client, csv, account_id, category_column="category").json()

    assert result == {"imported": 0, "skipped_duplicates": 1, "errors": 0}
    assert client.get("/api/v1/transactions").json()["total"] == 1


def test_the_preview_judges_duplicates_against_the_chosen_account(client):
    """Preview needs the destination account: a row may be a duplicate in one account and new in another. Without the account, the wizard's Status column would ignore the intended destination."""
    first_value = _account(client, "Account A")
    second_value = _account(client, "Account B")
    _category(client, "Salary", "income")
    csv = "date,description,amount,category\n2026-02-10,Salary,1500.00,Salary\n"
    _import(client, csv, first_value, category_column="category")

    assert (
        _preview(client, csv, first_value, category_column="category").json()["duplicate_rows"] == 1
    )
    assert (
        _preview(client, csv, second_value, category_column="category").json()["duplicate_rows"]
        == 0
    )


def test_an_amount_written_with_fewer_decimals_is_the_same_amount(client):
    """CSV -1.5 and database -1.500000 are the same amount: normalize the hash so a second import recognizes the rows."""
    account_id = _account(client, "Checking")
    _category(client, "Expenses", "expense")

    _import(
        client,
        "date,description,amount,category\n2026-01-10,Café,-1.5,Expenses\n",
        account_id,
        category_column="category",
    )
    result = _import(
        client,
        "date,description,amount,category\n2026-01-10,Café,-1.500,Expenses\n",
        account_id,
        category_column="category",
    ).json()

    assert result["skipped_duplicates"] == 1
    assert client.get("/api/v1/transactions").json()["total"] == 1
