"""Imported-row identity (app/utils/deduplication.py).

Two system assumptions:

- Equal movements on different accounts have different hashes, preventing
  import_hash uniqueness from silently dropping one.
- Equivalent amount representations have the same hash, allowing repeat
  imports and migration b7e4d1c9a3f2 to recompute historical hashes from
  database values that always carry six decimals.
"""

from decimal import Decimal

from app.utils.deduplication import canonical_amount, compute_row_hash

CSV_ROW = dict(date="2026-01-10", amount=Decimal("-45.30"), description="Expense")


def test_the_same_row_on_two_accounts_has_two_hashes():
    assert compute_row_hash(1, **CSV_ROW) != compute_row_hash(2, **CSV_ROW)


def test_the_same_row_on_the_same_account_has_the_same_hash():
    assert compute_row_hash(1, **CSV_ROW) == compute_row_hash(1, **CSV_ROW)


def test_the_amount_is_compared_at_the_precision_of_the_database():
    """CSV -45.3 and database -45.300000 are the same amount."""
    from_csv = compute_row_hash(1, "2026-01-10", Decimal("-45.3"), "Expense")
    from_database = compute_row_hash(1, "2026-01-10", Decimal("-45.300000"), "Expense")

    assert from_csv == from_database


def test_amounts_that_differ_below_the_stored_precision_collapse():
    """Numeric(18, 6) columns do not distinguish beyond six decimals. Hashes must follow that precision so database rereads can reproduce them."""
    assert canonical_amount(Decimal("1.2345678")) == canonical_amount(Decimal("1.23456780"))
    assert canonical_amount(Decimal("1.2345678")) == "1.234568"


def test_a_missing_description_is_not_a_special_case():
    assert compute_row_hash(1, "2026-01-10", 10, None) == compute_row_hash(1, "2026-01-10", 10, "")


def test_different_dates_or_amounts_still_separate_rows():
    base = compute_row_hash(1, **CSV_ROW)

    assert compute_row_hash(1, "2026-01-11", CSV_ROW["amount"], CSV_ROW["description"]) != base
    assert compute_row_hash(1, CSV_ROW["date"], Decimal("-45.31"), CSV_ROW["description"]) != base
    assert compute_row_hash(1, CSV_ROW["date"], CSV_ROW["amount"], "Other") != base


def test_the_amount_is_accepted_in_any_numeric_form():
    """The caller passes what it has: a Decimal from the CSV parser or database, or a number."""
    expected_value = compute_row_hash(1, "2026-01-10", Decimal("10.000000"), "X")

    assert compute_row_hash(1, "2026-01-10", 10, "X") == expected_value
    assert compute_row_hash(1, "2026-01-10", "10", "X") == expected_value
