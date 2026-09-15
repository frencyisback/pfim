"""Cash movements accompanying investment operations. Trades, income payments, and recurring
portfolio costs all move cash on the investment account's reference account. This shared
procedure resolves the reference account and category, then creates or updates a movement in
EUR. Arguments supply the source link column, amount, description, and category.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.transaction_repo import TransactionRepository
from app.services.account_service import require_active_account
from app.services.transaction_rules import TransactionRules
from app.utils.currency import EUR
from app.utils.errors import ConflictError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_18_6

# The only transactions columns linking a movement to its source entity. Listed explicitly
# because the field arrives as a string: invalid names must fail immediately rather than
# create an untraceable, unlinked transaction.
#
LINK_FIELDS = ("trade_id", "income_event_id", "portfolio_cost_id")


class LinkedCashMovement:
    """Create, update, or delete cash movements linked to a source entity. Amounts are always in
    EUR, with conversion already frozen on the source record so balances never need to convert
    mixed currencies again.
    """

    def __init__(self, db: Session):
        self.db = db
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.transaction_repo = TransactionRepository(db)
        self.rules = TransactionRules(db)

    def _investment_account(self, investment_account_id: int, *, date: dt.date):
        account = self.account_repo.get(investment_account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Investment account {investment_account_id} not found",
                detail={"account_id": investment_account_id},
            )
        require_active_account(
            account,
            action="generate a linked cash movement",
            effective_on=date,
        )
        if account.type != "investment" or account.reference_account_id is None:
            raise ValidationErrorPFIM(
                "The linked movement requires an investment account with a reference account",
                detail={
                    "account_id": investment_account_id,
                    "type": account.type,
                    "reference_account_id": account.reference_account_id,
                },
            )
        return account

    def _require_cash_account(self, account_id: int, *, date: dt.date, action: str) -> int:
        account = self.account_repo.get(account_id)
        if account is None or account.type == "investment":
            raise ValidationErrorPFIM(
                "The frozen cash account for the movement is invalid",
                detail={
                    "cash_account_id": account_id,
                },
            )
        require_active_account(account, action=action, effective_on=date)
        return account.id

    def resolve_cash_account_id(self, investment_account_id: int, *, date: dt.date) -> int:
        """Freeze the reference account valid on the source's economic date."""
        investment = self._investment_account(investment_account_id, date=date)
        return self._require_cash_account(
            investment.reference_account_id,
            date=date,
            action="receive a linked cash movement",
        )

    def sync(
        self,
        *,
        link_field: str,
        link_id: int,
        investment_account_id: int,
        cash_account_id: int | None,
        date: dt.date,
        amount_eur: Decimal,
        description: str,
        category_name: str,
        category_type: str,
    ) -> int:
        """Create the linked movement if absent, otherwise update it. Recreate its system
        category through CategoryRepository.get_or_create if the user deleted it; generated
        movements must remain categorized.
        """
        if link_field not in LINK_FIELDS:
            raise ValueError(f"Unknown link column: {link_field}")

        try:
            amount_eur = normalize_numeric_18_6(
                Decimal(amount_eur), label="The cash movement in EUR"
            )
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc),
                detail={"field": "amount_eur", "value": str(amount_eur)},
            ) from exc

        existing = self.transaction_repo.get_by_link(link_field, link_id)
        # The investment account must be writable even for zero amounts. Use the cash account
        # fixed on the source. For legacy rows, recover it only from an existing linked
        # transaction, never the current reference.
        #
        self._investment_account(investment_account_id, date=date)
        resolved_cash_account_id = cash_account_id
        if resolved_cash_account_id is None and existing is not None:
            resolved_cash_account_id = existing.account_id
        if resolved_cash_account_id is None:
            raise ConflictError(
                "The historical cash account cannot be reconstructed with certainty: "
                "this legacy operation requires an explicit correction before it can be edited",
                detail={
                    "link_field": link_field,
                    "link_id": link_id,
                    "investment_account_id": investment_account_id,
                },
            )
        self._require_cash_account(
            resolved_cash_account_id,
            date=date,
            action="edit a linked cash movement",
        )
        if existing is not None and existing.account_id != resolved_cash_account_id:
            raise ConflictError(
                "The linked movement does not match the source's frozen cash account",
                detail={
                    "link_field": link_field,
                    "link_id": link_id,
                    "cash_account_id": resolved_cash_account_id,
                    "movement_account_id": existing.account_id,
                },
            )
        if amount_eur == 0:
            # Fully withheld income or another zero-net event is valid but creates no cash movement.
            # If resynchronization makes it zero, also remove any previous transaction.
            #
            #
            if existing is not None:
                self.transaction_repo.delete(existing.id)
            return resolved_cash_account_id

        category_id = self.category_repo.get_or_create(category_name, category_type).id
        self.rules.validate_category(
            category_id,
            amount_eur,
            expected_type=category_type,
        )

        if existing is not None:
            # Changing a reference account affects future movements, without moving historical ones.
            # Recalculation updates amount/date/category while preserving the account where cash
            # originally moved.
            #
            existing.amount = amount_eur
            existing.amount_eur = amount_eur
            existing.date = date
            existing.description = description
            existing.category_id = category_id
            self.transaction_repo.update(existing)
            return resolved_cash_account_id

        transaction = Transaction(
            account_id=resolved_cash_account_id,
            category_id=category_id,
            date=date,
            amount=amount_eur,
            currency=EUR,
            amount_eur=amount_eur,
            fx_rate=Decimal("1"),
            description=description,
            tags=json.dumps([]),
        )
        setattr(transaction, link_field, link_id)
        self.db.add(transaction)
        self.db.flush()
        return resolved_cash_account_id

    def delete(
        self,
        *,
        link_field: str,
        link_id: int,
        investment_account_id: int,
        cash_account_id: int | None,
        date: dt.date,
    ) -> None:
        """Delete the linked movement, if present, when its source entity is removed."""
        existing = self.transaction_repo.get_by_link(link_field, link_id)
        if existing is not None:
            self._investment_account(investment_account_id, date=date)
            resolved_cash_account_id = cash_account_id or existing.account_id
            self._require_cash_account(
                resolved_cash_account_id,
                date=date,
                action="delete a linked cash movement",
            )
            if existing.account_id != resolved_cash_account_id:
                raise ConflictError(
                    "The linked movement does not match the source's frozen cash account",
                    detail={
                        "link_field": link_field,
                        "link_id": link_id,
                        "cash_account_id": resolved_cash_account_id,
                        "movement_account_id": existing.account_id,
                    },
                )
            self.transaction_repo.delete(existing.id)
