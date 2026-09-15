"""Configurable transaction CSV parsing. A profile defines delimiter, skipped rows, date format,
column mappings, currency, and decimal separator.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, overload

from app.config import settings
from app.utils.errors import PayloadTooLargeError, ValidationErrorPFIM


@dataclass
class CsvProfile:
    """Interpret a transaction CSV. The router already decodes content and removes the Excel
    UTF-8 BOM, so no encoding field is needed. Amounts are signed, with negative values
    representing outflows.
    """

    delimiter: str = ","
    skip_rows: int = 0
    date_format: str = "%Y-%m-%d"
    date_column: str = "date"
    description_column: str = "description"
    amount_column: str = "amount"
    # Optional only to represent saved legacy profiles. The service rejects new mappings
    # without this field.
    category_column: str | None = None
    default_currency: str = "EUR"
    decimal_separator: str = "."


@dataclass
class ParsedRow:
    row_number: int
    date: dt.date | None
    description: str | None
    amount: Decimal | None
    category_raw: str | None = None
    errors: list[str] = field(default_factory=list)


@overload
def csv_cell(row: Mapping, column: str, *, required: Literal[True] = True) -> str: ...


@overload
def csv_cell(row: Mapping, column: str, *, required: Literal[False]) -> str | None: ...


def csv_cell(row: Mapping, column: str, *, required: bool = True) -> str | None:
    """Validate cells before parsing without inventing missing values. DictReader uses None for
    truncated rows. Optional cells may be absent; valid strings remain unchanged.
    """
    value = row.get(column)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"Column '{column}' is missing or empty")
        return None
    if not isinstance(value, str):
        raise ValueError(f"Column '{column}' is not text")
    return value


def _parse_amount(raw: str, decimal_separator: str) -> Decimal:
    cleaned = raw.strip().replace(" ", "")
    if decimal_separator == ",":
        # Italian number format: dot for thousands, comma for decimals.
        cleaned = cleaned.replace(".", "").replace(",", ".")
    amount = Decimal(cleaned)
    if not amount.is_finite():
        raise InvalidOperation
    return amount


def validate_csv_delimiter(delimiter: str) -> None:
    """The csv module requires exactly one character that is not a newline."""

    if len(delimiter) != 1 or delimiter in {"\r", "\n"}:
        raise ValidationErrorPFIM(
            "The CSV delimiter must be a single character and cannot be a newline",
            detail={"delimiter": delimiter},
        )


def _unwrap_fully_quoted_rows(lines: list[str], delimiter: str) -> list[str]:
    """Some exports quote each whole row instead of individual fields, for example a quoted
    Date;Description;Amount;Category header. Standard CSV parsing would treat it as one
    unmapped column. When every nonempty line starts and ends with a quote and contains the
    delimiter, strip the outer pair before normal parsing. A correctly quoted single field
    does not trigger this unless all rows, including the header, have that form.
    """
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return lines

    def is_fully_wrapped(line: str) -> bool:
        return (
            len(line) >= 2
            and line.startswith('"')
            and line.endswith('"')
            and delimiter in line[1:-1]
        )

    if all(is_fully_wrapped(line) for line in non_empty):
        return [line[1:-1] if is_fully_wrapped(line) else line for line in lines]
    return lines


def parse_csv_content(
    content: str, profile: CsvProfile, *, max_rows: int | None = None
) -> list[ParsedRow]:
    """Parse CSV content using the supplied profile. Return malformed rows with populated errors
    for preview instead of raising per-row exceptions.
    """
    validate_csv_delimiter(profile.delimiter)
    row_limit = settings.csv_import_max_rows if max_rows is None else max_rows
    if row_limit <= 0:
        raise RuntimeError("csv_import_max_rows must be greater than zero")

    if profile.decimal_separator not in {".", ","}:
        raise ValidationErrorPFIM(
            "The decimal separator must be '.' or ','",
            detail={"decimal_separator": profile.decimal_separator},
        )

    lines = content.splitlines()[profile.skip_rows :]
    lines = _unwrap_fully_quoted_rows(lines, profile.delimiter)
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=profile.delimiter, strict=True)

    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise ValidationErrorPFIM("Malformed CSV header", detail={"reason": str(exc)}) from exc
    if not fieldnames:
        raise ValidationErrorPFIM("The CSV file has no header")
    normalized_headers = [name.strip() if name is not None else "" for name in fieldnames]
    if len(normalized_headers) != len(set(normalized_headers)):
        raise ValidationErrorPFIM(
            "The CSV header contains duplicate columns",
            detail={"columns": normalized_headers},
        )
    required_columns = {
        profile.date_column,
        profile.description_column,
        profile.amount_column,
    }
    if profile.category_column:
        required_columns.add(profile.category_column)
    missing = sorted(required_columns.difference(normalized_headers))
    if missing:
        raise ValidationErrorPFIM(
            "Columns mapped by the profile are missing from the CSV header",
            detail={"missing_columns": missing},
        )

    rows: list[ParsedRow] = []
    try:
        for i, raw_row in enumerate(reader, start=1):
            if i > row_limit:
                raise PayloadTooLargeError(
                    "The CSV exceeds the maximum allowed row count",
                    detail={"max_rows": row_limit},
                )

            raw_row = {
                key.strip() if isinstance(key, str) else key: value
                for key, value in raw_row.items()
            }
            errors: list[str] = []
            if None in raw_row:
                errors.append("The row contains more values than the declared columns")
            parsed_date: dt.date | None = None
            parsed_amount: Decimal | None = None
            try:
                description = csv_cell(raw_row, profile.description_column, required=False)
            except ValueError as exc:
                description = None
                errors.append(str(exc))

            try:
                date_raw = csv_cell(raw_row, profile.date_column)
            except ValueError:
                date_raw = None
                errors.append(f"Date column '{profile.date_column}' is missing or empty")
            if date_raw is not None:
                try:
                    parsed_date = dt.datetime.strptime(date_raw.strip(), profile.date_format).date()
                except ValueError:
                    errors.append(f"Date '{date_raw}' does not match format {profile.date_format}")

            try:
                amount_raw = csv_cell(raw_row, profile.amount_column)
            except ValueError:
                amount_raw = None
                errors.append(f"Amount column '{profile.amount_column}' is missing or empty")
            if amount_raw is not None:
                try:
                    parsed_amount = _parse_amount(amount_raw, profile.decimal_separator)
                except InvalidOperation:
                    errors.append(f"Amount '{amount_raw}' is invalid")

            category_raw: str | None = None
            if profile.category_column:
                try:
                    category_raw = csv_cell(raw_row, profile.category_column).strip()
                except ValueError:
                    errors.append(
                        f"Category column '{profile.category_column}' is missing or empty"
                    )

            rows.append(
                ParsedRow(
                    row_number=i,
                    date=parsed_date,
                    description=description,
                    amount=parsed_amount,
                    category_raw=category_raw,
                    errors=errors,
                )
            )
    except csv.Error as exc:
        raise ValidationErrorPFIM(
            "Malformed CSV file",
            detail={"line_number": reader.line_num, "reason": str(exc)},
        ) from exc
    if not rows:
        raise ValidationErrorPFIM("The CSV file has no data rows")
    return rows
