"""Account service: account CRUD and current balance calculation."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.income_event import IncomeEvent
from app.models.portfolio_cost import PortfolioCost
from app.models.trade import Trade
from app.models.transaction import Transaction
from app.repositories.account_repo import AccountRepository
from app.schemas.account import (
    AccountBalance,
    AccountBalanceHistoryPoint,
    AccountCreate,
    AccountUpdate,
)
from app.utils.currency import EUR, normalize_currency
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_18_6


def _normalize_opening_balance(value: Decimal) -> Decimal:
    """Return opening balance in a form that can actually be persisted."""
    try:
        return normalize_numeric_18_6(Decimal(value), label="The opening balance")
    except ValueError as exc:
        raise ValidationErrorPFIM(
            str(exc),
            detail={"field": "opening_balance", "value": str(value)},
        ) from exc


def require_active_account(
    account: Account,
    *,
    action: str,
    effective_on: dt.date | None = None,
) -> Account:
    """Shared domain guard for account writes. Accept an already loaded model independently of
    HTTP schemas, so transactions, trades, income, costs, and linked cash movements use the
    same validation.
    """
    if not account.is_active:
        raise ConflictError(
            f"Account '{account.name}' is inactive: reactivate it before attempting to {action}",
            detail={"account_id": account.id, "is_active": False, "action": action},
        )
    if effective_on is not None and not account_is_present_on(account, effective_on):
        raise ValidationErrorPFIM(
            f"Account '{account.name}' is unavailable on "
            f"{effective_on.isoformat()}: cannot {action}",
            detail={
                "account_id": account.id,
                "effective_on": effective_on.isoformat(),
                "opened_on": account.opened_on.isoformat() if account.opened_on else None,
                "closed_on": account.closed_on.isoformat() if account.closed_on else None,
                "action": action,
            },
        )
    return account


def validate_investment_opening_balance(account_type: str, opening_balance) -> None:
    """An investment account holds positions and no cash of its own."""
    if account_type == "investment" and Decimal(opening_balance) != Decimal(0):
        raise ValidationErrorPFIM(
            "An investment account must have a zero opening balance: "
            "cash belongs to the reference account",
            detail={
                "type": account_type,
                "opening_balance": str(Decimal(opening_balance)),
            },
        )


def account_is_present_on(account: Account, date: dt.date) -> bool:
    """Return whether the account existed on the requested date. Boundaries are inclusive. Legacy
    NULL dates are open bounds meaning unknown date, not absent account.
    """
    return (account.opened_on is None or account.opened_on <= date) and (
        account.closed_on is None or account.closed_on >= date
    )


class AccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = AccountRepository(db)

    def list_accounts(self, *, only_active: bool = False) -> list[Account]:
        return self.repo.list(only_active=only_active)

    def get_account(self, account_id: int) -> Account:
        account = self.repo.get(account_id)
        if account is None:
            raise NotFoundError(
                f"Account {account_id} not found",
                detail={"account_id": account_id},
            )
        return account

    def _validate_currency(self, currency: str | None) -> None:
        """Accounts support EUR only in v1.0. Movements are converted to EUR at entry, so other
        account currencies would mix native opening balances with EUR movements.
        """
        if currency is not None and normalize_currency(currency) != EUR:
            raise ValidationErrorPFIM(
                "Accounts are managed in EUR only. Record a foreign-currency movement "
                "on a EUR account by declaring the currency and exchange rate on the movement "
                "itself.",
                detail={"currency": normalize_currency(currency)},
            )

    def _validate_reference_account(
        self,
        account_id: int | None,
        type_: str,
        reference_account_id: int | None,
        *,
        require_active_reference: bool = True,
        effective_on: dt.date | None = None,
    ) -> None:
        """Investment accounts require a checking, savings, or cash reference account for trade
        and income cash movements. Other account types cannot have a reference account.
        """
        if type_ != "investment":
            if reference_account_id is not None:
                raise ValidationErrorPFIM(
                    "Only investment accounts can have a reference account",
                    detail={"type": type_},
                )
            return
        if reference_account_id is None:
            raise ValidationErrorPFIM(
                "Investment accounts require a reference account "
                "for cash movements from purchases, sales, and income payments",
                detail={"type": type_},
            )
        if reference_account_id == account_id:
            raise ValidationErrorPFIM(
                "An account cannot be its own reference account",
                detail={"account_id": account_id},
            )
        reference = self.repo.get(reference_account_id)
        if reference is None:
            raise ValidationErrorPFIM(
                f"Reference account {reference_account_id} not found",
                detail={"reference_account_id": reference_account_id},
            )
        if reference.type == "investment":
            raise ValidationErrorPFIM(
                "The reference account cannot itself be an investment account",
                detail={"reference_account_id": reference_account_id},
            )
        if effective_on is not None and not account_is_present_on(reference, effective_on):
            raise ValidationErrorPFIM(
                "The reference account is unavailable on the investment account's opening date",
                detail={
                    "reference_account_id": reference_account_id,
                    "opened_on": effective_on.isoformat(),
                    "reference_opened_on": (
                        reference.opened_on.isoformat() if reference.opened_on else None
                    ),
                    "reference_closed_on": (
                        reference.closed_on.isoformat() if reference.closed_on else None
                    ),
                },
            )
        if require_active_reference:
            require_active_account(reference, action="use it as a reference account")

    def _active_dependent_count(self, account_id: int) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(Account)
                .where(
                    Account.reference_account_id == account_id,
                    Account.is_active.is_(True),
                )
            )
            or 0
        )

    def _account_usage_counts(self, account_id: int) -> dict[str, int]:
        """Count all relationships that make the account part of financial history. Share this
        check between updates and permanent deletion.
        """
        return {
            "transactions_count": int(
                self.db.scalar(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.account_id == account_id)
                )
                or 0
            ),
            "trades_count": int(
                self.db.scalar(
                    select(func.count())
                    .select_from(Trade)
                    .where(or_(Trade.account_id == account_id, Trade.cash_account_id == account_id))
                )
                or 0
            ),
            "income_events_count": int(
                self.db.scalar(
                    select(func.count())
                    .select_from(IncomeEvent)
                    .where(
                        or_(
                            IncomeEvent.account_id == account_id,
                            IncomeEvent.cash_account_id == account_id,
                        )
                    )
                )
                or 0
            ),
            "portfolio_costs_count": int(
                self.db.scalar(
                    select(func.count())
                    .select_from(PortfolioCost)
                    .where(
                        or_(
                            PortfolioCost.account_id == account_id,
                            PortfolioCost.cash_account_id == account_id,
                        )
                    )
                )
                or 0
            ),
            "dependent_accounts_count": int(
                self.db.scalar(
                    select(func.count())
                    .select_from(Account)
                    .where(Account.reference_account_id == account_id)
                )
                or 0
            ),
        }

    def _ensure_financial_identity_is_mutable(
        self,
        account: Account,
        update_data: dict,
    ) -> None:
        """Type and opening balance define accounting identity. Changing them after the first
        movement or reference would reinterpret existing history. Name, notes, status, and
        reference follow their own guards; reference changes deliberately apply prospectively.
        """
        changed_fields: list[str] = []
        if "type" in update_data and update_data["type"] != account.type:
            changed_fields.append("type")
        if "opening_balance" in update_data and Decimal(update_data["opening_balance"]) != Decimal(
            account.opening_balance
        ):
            changed_fields.append("opening_balance")
        if not changed_fields:
            return

        usage = self._account_usage_counts(account.id)
        if any(usage.values()):
            raise ConflictError(
                "Type and opening balance cannot be changed after the account "
                "has entered the financial history",
                detail={
                    "account_id": account.id,
                    "changed_fields": changed_fields,
                    **usage,
                },
            )

    def _ensure_can_deactivate(
        self,
        account: Account,
        *,
        projected_opening_balance=None,
    ) -> None:
        """Allow archiving only when no operational state remains. Closed history is retained in
        reports and balances. Nonzero cash, dependent active investment accounts, open
        positions, and future trades block archiving.
        """
        today = dt.date.today()
        opening_balance = Decimal(
            account.opening_balance
            if projected_opening_balance is None
            else projected_opening_balance
        )
        transactions_total = self.db.scalar(
            select(func.sum(Transaction.amount_eur)).where(
                Transaction.account_id == account.id,
                Transaction.date <= today,
            )
        )
        current_balance = opening_balance + Decimal(transactions_total or 0)
        dependent_count = self._active_dependent_count(account.id)

        positions: dict[int, Decimal] = {}
        historical_trades = self.db.scalars(
            select(Trade).where(
                Trade.account_id == account.id,
                Trade.date <= today,
            )
        )
        for trade in historical_trades:
            signed_quantity = Decimal(trade.quantity)
            if trade.type == "sell":
                signed_quantity = -signed_quantity
            positions[trade.security_id] = (
                positions.get(trade.security_id, Decimal(0)) + signed_quantity
            )
        open_positions_count = sum(quantity != 0 for quantity in positions.values())
        future_trades_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(Trade)
                .where(
                    or_(Trade.account_id == account.id, Trade.cash_account_id == account.id),
                    Trade.date > today,
                )
            )
            or 0
        )
        future_transactions_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(Transaction)
                .where(
                    Transaction.account_id == account.id,
                    Transaction.date > today,
                )
            )
            or 0
        )
        future_income_events_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(IncomeEvent)
                .where(
                    or_(
                        IncomeEvent.account_id == account.id,
                        IncomeEvent.cash_account_id == account.id,
                    ),
                    IncomeEvent.payment_date > today,
                )
            )
            or 0
        )
        future_portfolio_costs_count = int(
            self.db.scalar(
                select(func.count())
                .select_from(PortfolioCost)
                .where(
                    or_(
                        PortfolioCost.account_id == account.id,
                        PortfolioCost.cash_account_id == account.id,
                    ),
                    PortfolioCost.date > today,
                )
            )
            or 0
        )

        blockers: list[str] = []
        if current_balance != 0:
            blockers.append(f"current balance {current_balance} EUR")
        if dependent_count:
            blockers.append(f"{dependent_count} dependent active investment accounts")
        if open_positions_count:
            blockers.append(f"{open_positions_count} open positions")
        if future_trades_count:
            blockers.append(f"{future_trades_count} future security trades")
        if future_transactions_count:
            blockers.append(f"{future_transactions_count} future transactions")
        if future_income_events_count:
            blockers.append(f"{future_income_events_count} future coupons/dividends")
        if future_portfolio_costs_count:
            blockers.append(f"{future_portfolio_costs_count} future recurring costs")

        if blockers:
            raise ConflictError(
                "Cannot deactivate the account: " + ", ".join(blockers),
                detail={
                    "account_id": account.id,
                    "current_balance": str(current_balance),
                    "active_dependent_accounts_count": dependent_count,
                    "open_positions_count": open_positions_count,
                    "future_trades_count": future_trades_count,
                    "future_transactions_count": future_transactions_count,
                    "future_income_events_count": future_income_events_count,
                    "future_portfolio_costs_count": future_portfolio_costs_count,
                    "blockers": blockers,
                },
            )

    def create_account(self, data: AccountCreate) -> Account:
        self._validate_currency(data.currency)
        opening_balance = _normalize_opening_balance(data.opening_balance)
        validate_investment_opening_balance(data.type, opening_balance)
        opened_on = data.opened_on or dt.date.today()
        if opened_on > dt.date.today():
            # Keep the guard in the service to protect internal callers that construct schemas without
            # HTTP validation.
            raise ValidationErrorPFIM(
                "The account opening date cannot be in the future",
                detail={"opened_on": opened_on.isoformat()},
            )
        self._validate_reference_account(
            None,
            data.type,
            data.reference_account_id,
            effective_on=opened_on,
        )
        values = data.model_dump()
        values["opening_balance"] = opening_balance
        values["opened_on"] = opened_on
        account = Account(**values)
        return self.repo.add(account)

    def update_account(self, account_id: int, data: AccountUpdate) -> Account:
        account = self.get_account(account_id)
        update_data = data.model_dump(exclude_unset=True)
        if "opening_balance" in update_data:
            update_data["opening_balance"] = _normalize_opening_balance(
                update_data["opening_balance"]
            )
        self._validate_currency(update_data.get("currency"))
        effective_type = update_data.get("type", account.type)
        effective_opening_balance = update_data.get("opening_balance", account.opening_balance)
        effective_active = update_data.get("is_active", account.is_active)
        effective_reference = update_data.get("reference_account_id", account.reference_account_id)
        if (
            update_data.get("is_active") is True
            and not account.is_active
            and account.closed_on is not None
            and account.closed_on < dt.date.today()
        ):
            # A single opened_on/closed_on pair can undo today's deactivation but cannot represent two
            # separate intervals. Removing a historical closure would include the account in snapshots
            # where it was absent.
            #
            raise ConflictError(
                "An account closed on an earlier date cannot be reactivated: "
                "create a new account for the new operating interval",
                detail={
                    "account_id": account.id,
                    "closed_on": account.closed_on.isoformat(),
                    "reactivation_policy": "same_day_undo_only",
                },
            )
        if effective_type != "investment":
            # A nonnull reference supplied for checking/savings/cash is incompatible and must be
            # rejected. Implicit clearing is allowed only when an empty investment account actually
            # changes type; its reference then has no meaning and must not remain attached.
            #
            #
            if (
                "reference_account_id" in update_data
                and update_data["reference_account_id"] is not None
            ):
                raise ValidationErrorPFIM(
                    "Only investment accounts can have a reference account",
                    detail={"type": effective_type},
                )
            if account.type == "investment" and effective_type != "investment":
                effective_reference = None
                update_data["reference_account_id"] = None
        validate_investment_opening_balance(effective_type, effective_opening_balance)
        self._ensure_financial_identity_is_mutable(account, update_data)
        self._validate_reference_account(
            account_id,
            effective_type,
            effective_reference,
            # An archived investment account may retain a historical reference to an account later
            # deactivated. The reference must be active when the investment account is operational or
            # its reference changes.
            require_active_reference=(effective_active or "reference_account_id" in update_data),
        )
        if update_data.get("is_active") is False:
            self._ensure_can_deactivate(
                account,
                projected_opening_balance=effective_opening_balance,
            )
        if "is_active" in update_data and update_data["is_active"] != account.is_active:
            # Reactivation here only undoes a same-day closure; the guard above protects historical
            # closures.
            update_data["closed_on"] = None if update_data["is_active"] else dt.date.today()
        for field, value in update_data.items():
            setattr(account, field, value)
        return self.repo.update(account)

    def deactivate_account(self, account_id: int) -> Account:
        """Soft delete: deactivate the account instead of deleting it."""
        account = self.get_account(account_id)
        if not account.is_active:
            # Do not invent a date for an already inactive legacy account.
            return account
        self._ensure_can_deactivate(account)
        account.is_active = False
        account.closed_on = dt.date.today()
        return self.repo.update(account)

    def delete_account(self, account_id: int) -> None:
        """Delete only an account that is truly empty. Calculate every blocker before returning
        so users can see all required changes together. Never cascade-delete financial
        children.
        """
        account = self.get_account(account_id)
        usage = self._account_usage_counts(account_id)
        opening_balance = Decimal(account.opening_balance)

        blocker_labels = []
        for key, label in (
            ("transactions_count", "transactions"),
            ("trades_count", "security trades"),
            ("income_events_count", "coupons/dividends"),
            ("portfolio_costs_count", "recurring costs"),
            ("dependent_accounts_count", "dependent investment accounts"),
        ):
            count = usage[key]
            if count:
                blocker_labels.append(f"{count} {label}")
        if opening_balance != 0:
            blocker_labels.append(f"opening balance {opening_balance} EUR")

        if blocker_labels:
            raise ConflictError(
                "Cannot delete the account: " + ", ".join(blocker_labels),
                detail={
                    "account_id": account_id,
                    **usage,
                    "opening_balance": str(opening_balance),
                    "blockers": blocker_labels,
                },
            )
        self.repo.delete(account_id)

    def get_balance(self, account_id: int, as_of_date: dt.date | None = None) -> AccountBalance:
        account = self.get_account(account_id)
        as_of_date = as_of_date or dt.date.today()

        if not account_is_present_on(account, as_of_date):
            return AccountBalance(
                account_id=account_id,
                balance=Decimal("0"),
                currency=EUR,
                as_of_date=as_of_date.isoformat(),
            )

        stmt = select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.date <= as_of_date,
        )
        # Sum amount_eur: foreign-currency transactions were converted at entry. Summing native
        # amounts would mix currencies in a EUR balance.
        #
        transactions_sum = sum(
            (Decimal(t.amount_eur) for t in self.db.scalars(stmt)), start=Decimal("0")
        )
        balance = Decimal(account.opening_balance) + transactions_sum
        return AccountBalance(
            account_id=account_id,
            balance=balance,
            currency=EUR,
            as_of_date=as_of_date.isoformat(),
        )

    def get_balance_history(self, account_id: int) -> list[AccountBalanceHistoryPoint]:
        """Balance history: one point per date containing a movement, starting from the opening
        balance. When known, the opening date starts the series; legacy records without one
        retain their previous behavior. End at the closing date inclusive and never expose
        points outside the account lifecycle.
        """
        account = self.get_account(account_id)

        today = dt.date.today()
        end_date = min(today, account.closed_on) if account.closed_on else today
        if account.opened_on is not None and account.opened_on > end_date:
            return []
        stmt = (
            select(Transaction)
            .where(
                Transaction.account_id == account_id,
                Transaction.date <= end_date,
            )
            .order_by(Transaction.date)
        )
        transactions = list(self.db.scalars(stmt))

        if account.opened_on is None:
            if not transactions:
                return [
                    AccountBalanceHistoryPoint(
                        date=end_date,
                        balance=Decimal(account.opening_balance),
                    )
                ]

            by_date: dict[dt.date, Decimal] = {}
            for transaction in transactions:
                by_date[transaction.date] = by_date.get(transaction.date, Decimal("0")) + Decimal(
                    transaction.amount_eur
                )

            running_balance = Decimal(account.opening_balance)
            points: list[AccountBalanceHistoryPoint] = []
            for date in sorted(by_date):
                running_balance += by_date[date]
                points.append(AccountBalanceHistoryPoint(date=date, balance=running_balance))
            return points

        # For an account with a known opening date, consolidate earlier transactions imported
        # before lifecycle support into the first point at opening. Never show them before that
        # date; leave the current balance unchanged.
        #
        by_date: dict[dt.date, Decimal] = {}
        carried_balance = Decimal(account.opening_balance)
        for transaction in transactions:
            if transaction.date < account.opened_on:
                carried_balance += Decimal(transaction.amount_eur)
            else:
                by_date[transaction.date] = by_date.get(transaction.date, Decimal("0")) + Decimal(
                    transaction.amount_eur
                )

        running_balance = carried_balance + by_date.pop(account.opened_on, Decimal("0"))
        points = [AccountBalanceHistoryPoint(date=account.opened_on, balance=running_balance)]
        for date in sorted(by_date):
            running_balance += by_date[date]
            points.append(AccountBalanceHistoryPoint(date=date, balance=running_balance))

        return points
