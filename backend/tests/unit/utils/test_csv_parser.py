"""Unit tests: CSV parsing, including fallback for fully quoted rows
(Excel export with the local semicolon list separator)."""

from datetime import date
from decimal import Decimal

import pytest

from app.utils.csv_parser import CsvProfile, csv_cell, parse_csv_content


@pytest.mark.parametrize("value", [None, "", "   ", 123, ["extra"]])
def test_required_cell_rejects_missing_blank_or_non_textual_values(value):
    with pytest.raises(ValueError):
        csv_cell({"amount": value}, "amount")


def test_truncated_rows_keep_optional_description_and_report_required_cells():
    rows = parse_csv_content(
        "date,amount,category,description\n2026-01-01,-10,Expense\n2026-01-02,-10\n2026-01-03\n",
        CsvProfile(category_column="category"),
    )
    assert rows[0].description is None
    assert rows[0].errors == []
    assert len(rows[1].errors) == 1
    assert "category" in rows[1].errors[0]
    assert len(rows[2].errors) == 2


def test_parses_row_fully_wrapped_in_quotes():
    """Reproduce an export where each row, including the header, is a single quoted string containing semicolons as actual separators instead of individually quoted CSV fields."""
    content = (
        '"Date;Description;Amount;Category"\r\n'
        '"01/01/2025;Example cafe purchase;7;Food and entertainment"\r\n'
    )
    profile = CsvProfile(
        delimiter=";",
        date_format="%d/%m/%Y",
        date_column="Date",
        description_column="Description",
        amount_column="Amount",
        category_column="Category",
        decimal_separator=",",
    )
    rows = parse_csv_content(content, profile)
    assert len(rows) == 1
    row = rows[0]
    assert row.errors == []
    assert row.date == date(2025, 1, 1)
    assert row.description == "Example cafe purchase"
    assert row.amount == Decimal("7")
    assert row.category_raw == "Food and entertainment"


def test_normal_csv_without_wrapping_quotes_is_unaffected():
    content = "date,description,amount\n2026-01-01,Test,10.50\n"
    profile = CsvProfile()
    rows = parse_csv_content(content, profile)
    assert len(rows) == 1
    assert rows[0].errors == []
    assert rows[0].amount == Decimal("10.50")


def test_legitimately_quoted_single_field_is_not_unwrapped():
    """A valid CSV can have a quoted field containing its delimiter, such as a description with a comma, without quoting the entire row. This header does not match the fallback pattern, so fallback must not run."""
    content = 'date,description,amount\n2026-01-01,"Expense, extra",10.50\n'
    profile = CsvProfile()
    rows = parse_csv_content(content, profile)
    assert len(rows) == 1
    assert rows[0].errors == []
    assert rows[0].description == "Expense, extra"
    assert rows[0].amount == Decimal("10.50")
