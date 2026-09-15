"""Regression tests for SQLite natural collation used by Cash Flow."""

from app.database import _natural_sort_key


def test_natural_sort_orders_numeric_chunks_without_integer_conversion() -> None:
    values = ["Instalment 10", "Instalment 2", "Instalment 1"]

    assert sorted(values, key=_natural_sort_key) == [
        "Instalment 1",
        "Instalment 2",
        "Instalment 10",
    ]


def test_natural_sort_accepts_unbounded_numeric_text_chunks() -> None:
    huge = "9" * 5_000

    assert _natural_sort_key(f"Instalment {huge}") > _natural_sort_key("Instalment 10")
