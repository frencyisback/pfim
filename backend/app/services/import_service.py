"""Service: ImportService. Import security prices and exchange rates from fixed CSV formats.
Semicolon delimiters allow either comma or point decimal notation without splitting numeric
values into multiple columns. Transaction imports have configurable profiles.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.config import settings
from app.models.fx_rate import FxRate
from app.models.price import Price
from app.repositories.fx_rate_repo import FxRateRepository
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.schemas.fx_rate import FxRateImportError, FxRateImportResult
from app.schemas.price import (
    PriceCreate,
    PriceImportPreviewResult,
    PriceImportPreviewRow,
    PriceImportResult,
    PriceRead,
)
from app.utils.csv_parser import csv_cell
from app.utils.currency import convert_to_eur
from app.utils.errors import PayloadTooLargeError, ValidationErrorPFIM
from app.utils.numeric_limits import (
    PRICE_MAX,
    PRICE_MIN,
    normalize_fx_rate,
    normalize_numeric_18_6,
)

CSV_DELIMITER = ";"
FX_RECIPROCAL_TOLERANCE = Decimal("0.00000001")


def _parse_decimal(raw: str) -> Decimal:
    """Accept both 17.50 and 17,50. A semicolon delimiter makes comma decimals unambiguous, so
    normalize them to a point before conversion.
    """
    value = Decimal(raw.strip().replace(",", "."))
    if not value.is_finite():
        raise InvalidOperation
    return value


def _parse_positive_decimal(raw: str, *, label: str) -> Decimal:
    value = _parse_decimal(raw)
    if value <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return value


def _normalize_price(value: Decimal, *, label: str) -> Decimal:
    normalized = normalize_numeric_18_6(value, label=label)
    if not PRICE_MIN <= normalized <= PRICE_MAX:
        raise ValueError(f"{label} must be between {PRICE_MIN} and {PRICE_MAX}")
    return normalized


def _parse_optional_decimal(raw: str | None) -> Decimal | None:
    """An absent or empty optional column means no declared value. This is normal for EUR
    securities; conversion rules report an error for other currencies.
    """
    if raw is None or not raw.strip():
        return None
    return _parse_decimal(raw)


def _fixed_csv_rows(content: str, *, required_columns: set[str]) -> list[dict]:
    """Parse and validate the common price/FX CSV structure. Read the whole file before writes so
    malformed structure or limits cannot cause partial imports. Allow named extra columns for
    older OHLCV exports; unnamed extra values make a malformed row handled by the caller.
    """

    reader = csv.DictReader(io.StringIO(content), delimiter=CSV_DELIMITER, strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        raise ValidationErrorPFIM("Malformed CSV header", detail={"reason": str(exc)}) from exc
    if not fieldnames:
        raise ValidationErrorPFIM("The CSV file has no header")
    normalized = [name.strip() if name is not None else "" for name in fieldnames]
    if len(normalized) != len(set(normalized)):
        raise ValidationErrorPFIM(
            "The CSV header contains duplicate columns",
            detail={"columns": normalized},
        )
    missing = sorted(required_columns.difference(normalized))
    if missing:
        raise ValidationErrorPFIM(
            "Required columns are missing from the CSV header",
            detail={"missing_columns": missing},
        )

    rows: list[dict] = []
    try:
        for row_number, row in enumerate(reader, start=1):
            if row_number > settings.csv_import_max_rows:
                raise PayloadTooLargeError(
                    "The CSV exceeds the maximum allowed row count",
                    detail={"max_rows": settings.csv_import_max_rows},
                )
            rows.append(
                {key.strip() if isinstance(key, str) else key: value for key, value in row.items()}
            )
    except csv.Error as exc:
        raise ValidationErrorPFIM(
            "Malformed CSV file",
            detail={"line_number": reader.line_num, "reason": str(exc)},
        ) from exc
    if not rows:
        raise ValidationErrorPFIM("The CSV file has no data rows")
    return rows


def _currency_code(raw: str) -> str:
    code = raw.strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise ValueError("Invalid currency code: expected three letters")
    return code


class ImportService:
    def __init__(self, db: Session):
        self.db = db
        self.security_repo = SecurityRepository(db)
        self.fx_rate_repo = FxRateRepository(db)
        self.price_repo = PriceRepository(db)

    def add_price(self, data: PriceCreate) -> PriceRead:
        """Manually upsert one price using the same rules as CSV import. The security defines the
        currency; the user supplies an exchange rate when it is not EUR.
        """
        security = self.security_repo.get(data.security_id)
        if security is None:
            raise ValidationErrorPFIM(
                f"Security {data.security_id} not found", detail={"security_id": data.security_id}
            )
        if not security.is_active:
            raise ValidationErrorPFIM(
                f"Security {security.ticker} is inactive: it cannot receive new prices",
                detail={"security_id": security.id, "is_active": False},
            )
        try:
            price_close = _normalize_price(data.price_close, label="The price")
        except ValueError as exc:
            raise ValidationErrorPFIM(str(exc)) from exc
        fx_rate, price_close_eur = convert_to_eur(price_close, security.currency, data.fx_rate)
        try:
            price_close_eur = _normalize_price(price_close_eur, label="The price in EUR")
        except ValueError as exc:
            raise ValidationErrorPFIM(str(exc)) from exc
        price = Price(
            security_id=data.security_id,
            date=data.date,
            price_close=price_close,
            fx_rate=fx_rate,
            price_close_eur=price_close_eur,
            source="manual",
        )
        return self.price_repo.upsert(price)

    def preview_prices(
        self, content: str, *, page: int = 1, page_size: int = 200
    ) -> PriceImportPreviewResult:
        """Dry-run price import using the same parsing and matching as import_prices, without
        writes, for row-by-row user confirmation.
        """
        source_rows = _fixed_csv_rows(content, required_columns={"date", "ticker", "close"})
        rows: list[PriceImportPreviewRow] = []
        new_count = 0
        update_count = 0
        skipped_unrecognized = 0
        error_count = 0
        # Simulate the entire file independently of the requested page.
        existing_keys = {(p.security_id, p.date) for p in self.price_repo.list_all()}
        valid_occurrences: dict[tuple[int, dt.date], list[PriceImportPreviewRow]] = {}

        for i, row in enumerate(source_rows, start=1):
            errors: list[str] = []
            ticker = ""
            try:
                ticker = csv_cell(row, "ticker").strip()
            except ValueError:
                pass
            date = None
            close = None
            declared_rate = None

            try:
                date = dt.datetime.strptime(csv_cell(row, "date").strip(), "%Y-%m-%d").date()
            except (KeyError, ValueError):
                errors.append("Invalid date: expected YYYY-MM-DD")
            try:
                close = _normalize_price(
                    _parse_positive_decimal(csv_cell(row, "close"), label="The price"),
                    label="The price",
                )
            except (KeyError, InvalidOperation, ValueError):
                errors.append("Invalid closing price")
            if not ticker:
                errors.append("Missing ticker")
            if None in row:
                errors.append("The row contains more values than the declared columns")
            try:
                declared_rate = _parse_optional_decimal(csv_cell(row, "fx_rate", required=False))
            except (InvalidOperation, ValueError):
                errors.append("Invalid exchange rate")

            security = None
            # Actual import validates the entire numeric structure before matching. Preview must use
            # the same precedence: an unknown ticker with a malformed exchange rate is an error, not
            # merely a skipped row.
            #
            if ticker and not errors:
                security = self.security_repo.get_by_ticker(
                    ticker
                ) or self.security_repo.get_by_isin(ticker)
                if security is None:
                    skipped_unrecognized += 1
                elif not security.is_active:
                    errors.append(f"Security {security.ticker} is inactive")

            # Only non-EUR securities require an exchange rate, fixed on the price record. Previewing
            # it shows which rows require it before any writes.
            #
            fx_rate = None
            close_eur = None
            if security is not None and close is not None:
                try:
                    fx_rate, close_eur = convert_to_eur(close, security.currency, declared_rate)
                    close_eur = _normalize_price(close_eur, label="The price in EUR")
                except (InvalidOperation, ValidationErrorPFIM, ValueError) as exc:
                    message = (
                        exc.message
                        if isinstance(exc, ValidationErrorPFIM)
                        else (str(exc) if isinstance(exc, ValueError) else "Invalid exchange rate")
                    )
                    errors.append(message)

            is_update = False
            if security is not None and date is not None and not errors:
                key = (security.id, date)
                is_update = key in existing_keys
                existing_keys.add(key)

            if errors:
                error_count += 1
            elif security is not None:
                if is_update:
                    update_count += 1
                else:
                    new_count += 1

            rows.append(
                PriceImportPreviewRow(
                    row_number=i,
                    date=date,
                    ticker=ticker or None,
                    security_id=security.id if security else None,
                    security_label=security.ticker if security else None,
                    close=close,
                    currency=security.currency if security else None,
                    fx_rate=fx_rate,
                    close_eur=close_eur,
                    is_update=is_update,
                    errors=errors,
                )
            )
            if security is not None and date is not None and not errors:
                valid_occurrences.setdefault((security.id, date), []).append(rows[-1])

        for occurrences in valid_occurrences.values():
            if len(occurrences) < 2:
                continue
            final = occurrences[-1]
            for occurrence in occurrences:
                occurrence.final_row_number = final.row_number
                occurrence.final_close = final.close
                occurrence.final_close_eur = final.close_eur
                occurrence.final_fx_rate = final.fx_rate
                if occurrence is not final:
                    occurrence.superseded_by_row = final.row_number

        total_rows = len(rows)
        start = (page - 1) * page_size
        return PriceImportPreviewResult(
            rows=rows[start : start + page_size],
            total_rows=len(rows),
            new_rows=new_count,
            update_rows=update_count,
            skipped_unrecognized_ticker=skipped_unrecognized,
            error_rows=error_count,
            page=page,
            page_size=page_size,
            total_pages=(total_rows + page_size - 1) // page_size,
        )

    def import_prices(self, content: str) -> PriceImportResult:
        """Expected semicolon-delimited format: date;ticker;close;fx_rate. The optional fx_rate
        is EUR per unit of the security currency on the row date, needed only for non-EUR
        securities. Leave it empty or omit it for EUR. Match by exact ticker first, then by
        ISIN when the ticker column contains a valid ISIN.
        """
        rows = _fixed_csv_rows(content, required_columns={"date", "ticker", "close"})
        imported = 0
        updated = 0
        skipped_unrecognized = 0
        errors = 0

        for row in rows:
            try:
                if None in row:
                    raise ValueError
                ticker = csv_cell(row, "ticker").strip()
                if not ticker:
                    raise ValueError
                date = dt.datetime.strptime(csv_cell(row, "date").strip(), "%Y-%m-%d").date()
                close = _normalize_price(
                    _parse_positive_decimal(csv_cell(row, "close"), label="The price"),
                    label="The price",
                )
                declared_rate = _parse_optional_decimal(csv_cell(row, "fx_rate", required=False))
            except (KeyError, InvalidOperation, ValueError):
                errors += 1
                continue

            security = self.security_repo.get_by_ticker(ticker) or self.security_repo.get_by_isin(
                ticker
            )
            if security is None:
                skipped_unrecognized += 1
                continue
            if not security.is_active:
                errors += 1
                continue

            try:
                fx_rate, close_eur = convert_to_eur(close, security.currency, declared_rate)
                close_eur = _normalize_price(close_eur, label="The price in EUR")
            except (ValidationErrorPFIM, ValueError):
                # A foreign-currency security without an fx_rate column makes this row unusable, but must
                # not block the rest of the file.
                errors += 1
                continue

            existing = self.price_repo.get_by_security_and_date(security.id, date)
            price = Price(
                security_id=security.id,
                date=date,
                price_close=close,
                fx_rate=fx_rate,
                price_close_eur=close_eur,
                source="csv_import",
            )
            self.price_repo.upsert(price)
            if existing:
                updated += 1
            else:
                imported += 1

        return PriceImportResult(
            imported=imported,
            updated=updated,
            skipped_unrecognized_ticker=skipped_unrecognized,
            errors=errors,
        )

    def import_fx_rates(self, content: str) -> FxRateImportResult:
        """Expected semicolon-delimited format: date;from;to;rate. When EUR->USD exists but
        USD->EUR does not, automatically compute the reciprocal.
        """
        rows = _fixed_csv_rows(content, required_columns={"date", "from", "to", "rate"})
        candidates: list[dict] = []
        invalid_rows: set[int] = set()
        row_errors: list[FxRateImportError] = []

        def reject(row_number: int, column: str | None, message: str) -> None:
            invalid_rows.add(row_number)
            row_errors.append(
                FxRateImportError(row_number=row_number, column=column, message=message)
            )

        # Complete first pass: do not write until the entire file's structure, duplicates, and
        # explicit currency pairs have been validated.
        for row_number, row in enumerate(rows, start=1):
            if None in row:
                reject(row_number, None, "The row contains more values than the declared columns")
            values: dict = {}
            for column in ("date", "from", "to", "rate"):
                try:
                    raw = csv_cell(row, column)
                    if column == "date":
                        values[column] = dt.datetime.strptime(raw.strip(), "%Y-%m-%d").date()
                    elif column in {"from", "to"}:
                        values[column] = _currency_code(raw)
                    else:
                        values[column] = normalize_fx_rate(
                            _parse_positive_decimal(raw, label="The rate"), label="The rate"
                        )
                        normalize_fx_rate(Decimal(1) / values[column], label="The reciprocal rate")
                except (InvalidOperation, ValueError) as exc:
                    message = str(exc) if isinstance(exc, ValueError) else "Invalid rate"
                    reject(row_number, column, message)
            if row_number in invalid_rows:
                continue
            date, from_ccy, to_ccy, rate = (
                values["date"],
                values["from"],
                values["to"],
                values["rate"],
            )
            if from_ccy == to_ccy:
                reject(
                    row_number,
                    "to",
                    "The destination currency must differ from the source currency",
                )
                continue
            candidates.append(
                {
                    "row_number": row_number,
                    "date": date,
                    "from": from_ccy,
                    "to": to_ccy,
                    "rate": rate,
                }
            )

        by_direction: dict[tuple, list[dict]] = {}
        for candidate in candidates:
            key = (candidate["date"], candidate["from"], candidate["to"])
            by_direction.setdefault(key, []).append(candidate)

        # Even identical duplicates create ambiguity in counts and origin. Reject every occurrence
        # of that direction.
        for duplicates in by_direction.values():
            if len(duplicates) > 1:
                numbers = ", ".join(str(item["row_number"]) for item in duplicates)
                for item in duplicates:
                    reject(item["row_number"], "rate", f"Duplicate direction on rows {numbers}")

        unique = {
            key: values[0]
            for key, values in by_direction.items()
            if len(values) == 1 and values[0]["row_number"] not in invalid_rows
        }

        checked_pairs: set[tuple] = set()
        for key, candidate in unique.items():
            date, from_ccy, to_ccy = key
            pair_key = (date, *sorted((from_ccy, to_ccy)))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)
            reverse = unique.get((date, to_ccy, from_ccy))
            if reverse is not None and abs(candidate["rate"] * reverse["rate"] - 1) > (
                FX_RECIPROCAL_TOLERANCE
            ):
                for item in (candidate, reverse):
                    reject(item["row_number"], "rate", "Inconsistent explicit reciprocal rates")

        # A new direction cannot conflict with an existing explicit reverse quote. Generated
        # reciprocals are derived and will be aligned after the upsert.
        #
        for key, candidate in unique.items():
            if candidate["row_number"] in invalid_rows:
                continue
            date, from_ccy, to_ccy = key
            if (date, to_ccy, from_ccy) in unique:
                continue
            counterpart = self.fx_rate_repo.get(to_ccy, from_ccy, date)
            if (
                counterpart is not None
                and counterpart.source != "csv_import_reciprocal"
                and abs(candidate["rate"] * Decimal(counterpart.rate) - 1) > FX_RECIPROCAL_TOLERANCE
            ):
                reject(
                    candidate["row_number"],
                    "rate",
                    "Rate is inconsistent with the stored explicit reciprocal",
                )

        valid = [c for c in candidates if c["row_number"] not in invalid_rows]
        valid_keys = {(c["date"], c["from"], c["to"]) for c in valid}

        imported = 0
        reciprocal_calculated = 0
        reciprocal_created = 0
        reciprocal_updated = 0
        for candidate in valid:
            self.fx_rate_repo.upsert(
                FxRate(
                    date=candidate["date"],
                    from_currency=candidate["from"],
                    to_currency=candidate["to"],
                    rate=candidate["rate"],
                    source="csv_import",
                )
            )
            imported += 1

        for candidate in valid:
            date = candidate["date"]
            from_ccy = candidate["from"]
            to_ccy = candidate["to"]
            if (date, to_ccy, from_ccy) in valid_keys:
                continue
            reciprocal = self.fx_rate_repo.get(to_ccy, from_ccy, date)
            reciprocal_rate = normalize_fx_rate(
                Decimal(1) / candidate["rate"],
                label="The reciprocal rate",
            )
            if reciprocal is None:
                self.fx_rate_repo.upsert(
                    FxRate(
                        date=date,
                        from_currency=to_ccy,
                        to_currency=from_ccy,
                        rate=reciprocal_rate,
                        source="csv_import_reciprocal",
                    )
                )
                reciprocal_calculated += 1
                reciprocal_created += 1
            elif reciprocal.source == "csv_import_reciprocal":
                # A generated reciprocal is not an independent quote and must follow direct-rate changes.
                # An explicit row with a different source is authoritative and is never overwritten by the
                # generator.
                #
                reciprocal.rate = reciprocal_rate
                reciprocal.source = "csv_import_reciprocal"
                self.db.flush()
                reciprocal_calculated += 1
                reciprocal_updated += 1

        return FxRateImportResult(
            imported=imported,
            reciprocal_calculated=reciprocal_calculated,
            reciprocal_created=reciprocal_created,
            reciprocal_updated=reciprocal_updated,
            errors=len(invalid_rows),
            row_errors=sorted(row_errors, key=lambda error: error.row_number),
        )
