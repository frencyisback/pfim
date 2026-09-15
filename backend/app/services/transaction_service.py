"""Service: TransactionService."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.transaction import Transaction
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryNameIndex, CategoryRepository
from app.repositories.transaction_repo import TransactionRepository
from app.schemas.transaction import (
    ImportPreviewResult,
    ImportPreviewRow,
    ImportResult,
    TransactionCreate,
    TransactionSummary,
    TransactionSummaryItem,
    TransferCreate,
)
from app.services.account_service import require_active_account
from app.services.transaction_rules import TransactionRules
from app.utils.csv_parser import CsvProfile, ParsedRow, parse_csv_content
from app.utils.currency import EUR, convert_to_eur, normalize_currency
from app.utils.date_ranges import validate_date_range
from app.utils.deduplication import compute_row_hash
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_18_6

TRANSFER_CATEGORY_NAME = "Account Transfer"


def _tags_to_json(tags: list[str]) -> str:
    return json.dumps(tags or [])


def _tags_from_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _normalize_amount(value: Decimal, *, label: str = "The amount") -> Decimal:
    """Persistable amount representation with a structured application error."""
    try:
        return normalize_numeric_18_6(Decimal(value), label=label)
    except ValueError as exc:
        raise ValidationErrorPFIM(
            str(exc), detail={"field": "amount", "value": str(value)}
        ) from exc


class TransactionService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TransactionRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.rules = TransactionRules(db)

    def _to_orm_kwargs(self, data: TransactionCreate) -> dict:
        """Convert the payload to ORM attributes with entry-time currency conversion. Calculate
        amount_eur and fx_rate here so neither is left empty.
        """
        payload = data.model_dump(exclude_unset=True)
        tags = payload.pop("tags", None)
        declared_rate = payload.pop("fx_rate", None)
        kwargs = dict(payload)
        if tags is not None:
            kwargs["tags"] = _tags_to_json(tags)

        currency = normalize_currency(kwargs.get("currency") or EUR)
        kwargs["currency"] = currency
        kwargs["amount"] = _normalize_amount(Decimal(kwargs["amount"]))
        kwargs["fx_rate"], kwargs["amount_eur"] = convert_to_eur(
            kwargs["amount"], currency, declared_rate
        )
        return kwargs

    def list_transactions(
        self,
        *,
        account_id: int | None = None,
        category_id: int | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "date",
        sort_dir: str = "desc",
    ) -> tuple[list[Transaction], int]:
        validate_date_range(date_from, date_to)
        return self.repo.list(
            account_id=account_id,
            category_id=category_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    def get_transaction(self, transaction_id: int) -> Transaction:
        tx = self.repo.get(transaction_id)
        if tx is None:
            raise NotFoundError(
                f"Transaction {transaction_id} not found",
                detail={"transaction_id": transaction_id},
            )
        return tx

    def _validate_account(
        self,
        account_id: int,
        *,
        effective_on: dt.date | None = None,
    ) -> Account:
        account = self.account_repo.get(account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Account {account_id} not found", detail={"account_id": account_id}
            )
        require_active_account(
            account,
            action="record movements",
            effective_on=effective_on,
        )
        if account.type == "investment":
            raise ValidationErrorPFIM(
                "Investment accounts do not hold their own cash: use them "
                "to record security purchases and sales on the Securities page, "
                "not for manual transactions or transfers.",
                detail={"account_id": account_id, "type": account.type},
            )
        return account

    def create_transaction(self, data: TransactionCreate) -> Transaction:
        self._validate_account(data.account_id, effective_on=data.date)
        self.rules.validate_category(data.category_id, data.amount)
        kwargs = self._to_orm_kwargs(data)
        tx = Transaction(**kwargs)
        return self.repo.add(tx)

    def _raise_if_generated_elsewhere(self, tx: Transaction) -> None:
        """Movements generated by trades, income, or recurring costs must be managed through
        their source entity to keep balances consistent. Transfers are managed here because
        they have no separate source: delete_transaction removes both linked sides.
        """
        if tx.portfolio_cost_id is not None:
            raise ConflictError(
                "This transaction is generated by a recurring portfolio cost. "
                "Edit or delete the cost on the Securities page.",
                detail={"transaction_id": tx.id, "portfolio_cost_id": tx.portfolio_cost_id},
            )
        if tx.trade_id is not None:
            raise ConflictError(
                "This transaction is generated by a security trade. "
                "Edit or delete the trade on the Securities page.",
                detail={"transaction_id": tx.id, "trade_id": tx.trade_id},
            )
        if tx.income_event_id is not None:
            raise ConflictError(
                "This transaction is generated by a coupon or dividend. "
                "Edit or delete the payment on the Income page.",
                detail={"transaction_id": tx.id, "income_event_id": tx.income_event_id},
            )

    def delete_transaction(self, transaction_id: int) -> None:
        tx = self.get_transaction(transaction_id)
        self._raise_if_generated_elsewhere(tx)
        # Archived accounts are read-only. This guard prevents deleting the zeroing transaction
        # after deactivation and recreating a balance on a closed account.
        #
        self._validate_account(tx.account_id, effective_on=tx.date)
        if tx.transfer_group_id is not None:
            # A transfer is one movement viewed from two accounts. Deleting only one side would leave
            # an unmatched entry or exit and break cancellation in the aggregate income statement.
            #
            #
            sibling = self.repo.get_transfer_sibling(
                tx.transfer_group_id, exclude_id=transaction_id
            )
            if sibling is not None:
                self._validate_account(sibling.account_id, effective_on=sibling.date)
                self.repo.delete(sibling.id)
        self.repo.delete(transaction_id)

    def create_transfer(self, data: TransferCreate) -> tuple[Transaction, Transaction]:
        """Transfer between the user's accounts: create two transactions linked by
        transfer_group_id, negative at the source and positive at the destination. They cancel
        in aggregates and do not count as external income or expense.
        """
        if data.from_account_id == data.to_account_id:
            raise ValidationErrorPFIM(
                "The source and destination accounts cannot be the same",
                detail={"account_id": data.from_account_id},
            )
        from_account = self._validate_account(data.from_account_id, effective_on=data.date)
        to_account = self._validate_account(data.to_account_id, effective_on=data.date)

        category_id = self.category_repo.get_or_create(TRANSFER_CATEGORY_NAME, "transfer").id
        amount = _normalize_amount(data.amount, label="The transfer amount")
        self.rules.validate_category(
            category_id,
            -amount,
            allow_transfer=True,
            expected_type="transfer",
        )
        group_id = str(uuid.uuid4())
        currency = normalize_currency(data.currency)
        # Use one exchange rate for both sides of the same transfer. Different rates would create
        # a fictitious EUR difference between the outgoing and incoming amounts.
        #
        fx_rate, amount_eur_to = convert_to_eur(amount, currency, data.fx_rate)
        amount_eur_from = -amount_eur_to

        tx_from = Transaction(
            account_id=data.from_account_id,
            category_id=category_id,
            date=data.date,
            amount=-amount,
            currency=currency,
            amount_eur=amount_eur_from,
            fx_rate=fx_rate,
            description=data.description or f"Transfer to {to_account.name}",
            notes=data.notes,
            tags=_tags_to_json([]),
            transfer_group_id=group_id,
        )
        tx_to = Transaction(
            account_id=data.to_account_id,
            category_id=category_id,
            date=data.date,
            amount=amount,
            currency=currency,
            amount_eur=amount_eur_to,
            fx_rate=fx_rate,
            description=data.description or f"Transfer from {from_account.name}",
            notes=data.notes,
            tags=_tags_to_json([]),
            transfer_group_id=group_id,
        )
        self.db.add(tx_from)
        self.db.add(tx_to)
        self.db.flush()
        self.db.refresh(tx_from)
        self.db.refresh(tx_to)
        return tx_from, tx_to

    def to_read_dict(self, tx: Transaction) -> dict:
        return {
            "id": tx.id,
            "account_id": tx.account_id,
            "category_id": tx.category_id,
            "date": tx.date,
            "amount": tx.amount,
            "currency": tx.currency,
            "amount_eur": tx.amount_eur,
            "fx_rate": tx.fx_rate,
            "description": tx.description,
            "notes": tx.notes,
            "tags": _tags_from_json(tx.tags),
            "transfer_group_id": tx.transfer_group_id,
            "trade_id": tx.trade_id,
            "income_event_id": tx.income_event_id,
            "portfolio_cost_id": tx.portfolio_cost_id,
            "created_at": tx.created_at,
            "updated_at": tx.updated_at,
        }

    def get_summary(
        self, *, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> TransactionSummary:
        validate_date_range(date_from, date_to)
        items = self.repo.iter_filtered(date_from=date_from, date_to=date_to)

        # Always sum amount_eur: amount is in the declared currency and would mix currencies. A
        # single pass also bounds memory use to one batch.
        #
        total_income = Decimal(0)
        total_expense = Decimal(0)
        by_category: dict[str, Decimal] = {}
        for t in items:
            amount = Decimal(t.amount_eur)
            if amount > 0:
                total_income += amount
            elif amount < 0:
                total_expense += amount
            key = str(t.category_id) if t.category_id is not None else "uncategorized"
            by_category[key] = by_category.get(key, Decimal(0)) + amount

        summary_items = [
            TransactionSummaryItem(
                key=k,
                total_income=max(v, Decimal(0)),
                total_expense=min(v, Decimal(0)),
                net=v,
            )
            for k, v in by_category.items()
        ]

        return TransactionSummary(
            period_from=date_from,
            period_to=date_to,
            total_income=total_income,
            total_expense=total_expense,
            net=total_income + total_expense,
            by_category=summary_items,
        )

    @staticmethod
    def _validate_import_profile(profile: CsvProfile) -> None:
        """Legacy profiles without a category remain readable but cannot map new imports. Never
        infer or automatically create categories for imported transactions.
        """
        if not profile.category_column or not profile.category_column.strip():
            raise ValidationErrorPFIM(
                "A category column mapping is required to import transactions"
            )

    def _resolve_category_id(self, row: ParsedRow, category_index: CategoryNameIndex) -> int | None:
        """Resolve and validate the category using the manual POST rules. Keep errors per row so
        preview and import reject the same movements without creating categories.
        """
        if not row.category_raw:
            if not any("category" in error.lower() for error in row.errors):
                row.errors.append("Category required")
            return None
        try:
            category = self.category_repo.get_by_name_ci(row.category_raw, index=category_index)
        except ConflictError as exc:
            row.errors.append(exc.message)
            return None
        if category is None:
            row.errors.append(f"Category '{row.category_raw}' not found")
            return None
        if row.amount is None:
            return category.id
        try:
            self.rules.validate_category(category.id, row.amount)
        except ValidationErrorPFIM as exc:
            row.errors.append(exc.message)
            return None
        return category.id

    @staticmethod
    def _row_hash(row: ParsedRow, account_id: int) -> str:
        """Imported-row identity includes its account: matching rows on different accounts are
        distinct movements. See app.utils.deduplication.
        """
        return compute_row_hash(account_id, row.date.isoformat(), row.amount, row.description)

    def _is_already_seen(self, row_hash: str, seen: set[str]) -> bool:
        """Check both persisted rows and duplicates already seen in the current file. With
        autoflush disabled, queued rows are not queryable yet; checking only the database
        risks a uniqueness failure for the whole import. The caller updates seen only when the
        row is accepted.
        """
        return row_hash in seen or self.repo.get_by_hash(row_hash) is not None

    def preview_import(
        self,
        content: str,
        profile: CsvProfile,
        account_id: int,
        fx_rate: Decimal | None = None,
        page: int = 1,
        page_size: int = 200,
    ) -> ImportPreviewResult:
        """Preview import without writes. Require the destination account because duplicate
        identity depends on it, and use the same account in import_transactions.
        """
        account = self._validate_account(account_id)
        self._validate_import_profile(profile)
        # Validate the declared profile-currency exchange rate immediately, so conversion errors
        # appear in preview before import starts.
        #
        convert_to_eur(Decimal("0"), profile.default_currency, fx_rate)
        parsed_rows = parse_csv_content(content, profile)
        preview_rows: list[ImportPreviewRow] = []
        duplicate_count = 0
        error_count = 0
        seen_hashes: set[str] = set()
        category_index = self.category_repo.build_name_index()

        for row in parsed_rows:
            if row.date is not None:
                try:
                    require_active_account(
                        account,
                        action="import the movement",
                        effective_on=row.date,
                    )
                except ValidationErrorPFIM as exc:
                    row.errors.append(exc.message)
            if row.amount is not None:
                try:
                    row.amount = _normalize_amount(row.amount)
                    convert_to_eur(row.amount, profile.default_currency, fx_rate)
                except ValidationErrorPFIM as exc:
                    row.errors.append(exc.message)
            self._resolve_category_id(row, category_index)
            is_duplicate = False
            if not row.errors and row.date is not None and row.amount is not None:
                row_hash = self._row_hash(row, account_id)
                is_duplicate = self._is_already_seen(row_hash, seen_hashes)
                seen_hashes.add(row_hash)
            if is_duplicate:
                duplicate_count += 1
            if row.errors:
                error_count += 1
            preview_rows.append(
                ImportPreviewRow(
                    row_number=row.row_number,
                    date=row.date,
                    description=row.description,
                    amount=row.amount,
                    category=row.category_raw,
                    is_duplicate=is_duplicate,
                    errors=row.errors,
                )
            )

        total_rows = len(parsed_rows)
        start = (page - 1) * page_size
        return ImportPreviewResult(
            rows=preview_rows[start : start + page_size],
            total_rows=len(parsed_rows),
            duplicate_rows=duplicate_count,
            error_rows=error_count,
            page=page,
            page_size=page_size,
            total_pages=(total_rows + page_size - 1) // page_size,
        )

    def import_transactions(
        self,
        content: str,
        profile: CsvProfile,
        account_id: int,
        import_source: str,
        fx_rate: Decimal | None = None,
    ) -> ImportResult:
        """Use one exchange rate for the whole file, matching the profile's default_currency.
        Reject a non-EUR import with no exchange rate before writing any row.
        """
        account = self._validate_account(account_id)
        self._validate_import_profile(profile)
        currency = normalize_currency(profile.default_currency)
        rate = convert_to_eur(Decimal("0"), currency, fx_rate)[0]
        parsed_rows = parse_csv_content(content, profile)

        imported = 0
        skipped_duplicates = 0
        errors = 0
        seen_hashes: set[str] = set()
        category_index = self.category_repo.build_name_index()

        for row in parsed_rows:
            amount_eur: Decimal | None = None
            if row.date is not None:
                try:
                    require_active_account(
                        account,
                        action="import the movement",
                        effective_on=row.date,
                    )
                except ValidationErrorPFIM as exc:
                    row.errors.append(exc.message)
            if row.amount is not None:
                try:
                    row.amount = _normalize_amount(row.amount)
                    _, amount_eur = convert_to_eur(row.amount, currency, rate)
                except ValidationErrorPFIM as exc:
                    row.errors.append(exc.message)
            category_id = self._resolve_category_id(row, category_index)
            if row.errors or row.date is None or row.amount is None:
                errors += 1
                continue
            if category_id is None:
                # Impossible state: the resolver must return an ID or add a row error. Fail the entire
                # request to expose regressions and guarantee rollback, rather than silently dropping a
                # row shown as valid in preview.
                #
                #
                raise RuntimeError(
                    "Import invariant violated: valid row has no resolved category_id"
                )
            if amount_eur is None:
                raise RuntimeError("Import invariant violated: valid row has no EUR equivalent")

            row_hash = self._row_hash(row, account_id)
            if self._is_already_seen(row_hash, seen_hashes):
                skipped_duplicates += 1
                continue
            seen_hashes.add(row_hash)

            tx = Transaction(
                account_id=account_id,
                category_id=category_id,
                date=row.date,
                amount=row.amount,
                currency=currency,
                amount_eur=amount_eur,
                fx_rate=rate,
                description=row.description,
                import_source=import_source,
                import_hash=row_hash,
                tags=_tags_to_json([]),
            )
            self.db.add(tx)
            imported += 1

        return ImportResult(imported=imported, skipped_duplicates=skipped_duplicates, errors=errors)
