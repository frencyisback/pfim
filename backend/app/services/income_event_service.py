"""Service: IncomeEventService."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.income_event import IncomeEvent
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.income_event_repo import IncomeEventRepository
from app.repositories.security_repo import SecurityRepository
from app.schemas.income_event import IncomeEventCreate, IncomeEventsSummary, IncomeEventSummaryItem
from app.services.account_service import require_active_account
from app.services.linked_transaction import LinkedCashMovement
from app.services.tax_service import TaxService
from app.utils.currency import convert_to_eur, normalize_currency
from app.utils.date_ranges import validate_date_range
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_18_6

INCOME_EVENT_CATEGORY_NAME = "Coupons and Dividends"
EVENT_TYPE_LABELS = {
    "dividend": "Dividend",
    "coupon": "Coupon",
    "return_of_capital": "Principal repayment",
}


class IncomeEventService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncomeEventRepository(db)
        self.security_repo = SecurityRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.cash_movement = LinkedCashMovement(db)
        self.tax_service = TaxService(db)

    def get_event(self, event_id: int) -> IncomeEvent:
        event = self.repo.get(event_id)
        if event is None:
            raise NotFoundError(f"Event {event_id} not found", detail={"event_id": event_id})
        return event

    def list_events(
        self,
        *,
        security_id: int | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
    ) -> list[IncomeEvent]:
        validate_date_range(date_from, date_to)
        return self.repo.list(security_id=security_id, date_from=date_from, date_to=date_to)

    def _validate_account(self, account_id: int, *, effective_on: dt.date) -> None:
        account = self.account_repo.get(account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Account {account_id} not found", detail={"account_id": account_id}
            )
        require_active_account(
            account,
            action="record coupons or dividends",
            effective_on=effective_on,
        )
        if account.type != "investment":
            raise ValidationErrorPFIM(
                "Coupons and dividends can only be recorded on investment accounts",
                detail={"account_id": account_id, "type": account.type},
            )
        if account.reference_account_id is None:
            raise ValidationErrorPFIM(
                "The investment account has no reference account configured. "
                "Set one in Settings before recording coupons or dividends.",
                detail={"account_id": account_id},
            )

    def create_event(self, data: IncomeEventCreate) -> IncomeEvent:
        security = self.security_repo.get(data.security_id)
        if security is None:
            raise ValidationErrorPFIM(
                f"Security {data.security_id} not found", detail={"security_id": data.security_id}
            )
        if not security.is_active:
            raise ValidationErrorPFIM(
                f"Security {security.ticker} is inactive: it cannot receive new income payments",
                detail={"security_id": data.security_id, "is_active": False},
            )
        self._validate_account(data.account_id, effective_on=data.payment_date)

        payload = data.model_dump()
        currency = normalize_currency(payload.pop("currency"))
        declared_rate = payload.pop("fx_rate")
        for field, label in (
            ("quantity_held", "The quantity held"),
            ("amount_per_unit", "The amount per unit"),
            ("total_amount", "The gross amount"),
            ("tax_withheld", "The withholding tax"),
        ):
            value = payload.get(field)
            if value is None:
                continue
            try:
                payload[field] = normalize_numeric_18_6(value, label=label)
            except ValueError as exc:
                raise ValidationErrorPFIM(
                    str(exc), detail={"field": field, "value": str(value)}
                ) from exc
        total_amount = Decimal(payload["total_amount"])
        tax_withheld = Decimal(payload["tax_withheld"])
        if tax_withheld > total_amount:
            raise ValidationErrorPFIM(
                "Withholding tax cannot exceed the gross amount after normalization "
                "to accounting precision",
                detail={
                    "total_amount": str(total_amount),
                    "tax_withheld": str(tax_withheld),
                },
            )
        # Gross income and withholding share a currency and timestamp. Use one rate for both so
        # their difference equals the net EUR amount.
        #
        fx_rate, total_eur = convert_to_eur(total_amount, currency, declared_rate)
        _, net_amount_eur = convert_to_eur(
            total_amount - tax_withheld,
            currency,
            fx_rate,
        )
        cash_account_id = self.cash_movement.resolve_cash_account_id(
            data.account_id,
            date=data.payment_date,
        )

        event = IncomeEvent(
            **payload,
            cash_account_id=cash_account_id,
            currency=currency,
            fx_rate=fx_rate,
            total_eur=total_eur,
            net_amount_eur=net_amount_eur,
        )
        saved_event = self.repo.add(event)
        self._sync_linked_transaction(saved_event)
        return saved_event

    def delete_event(self, event_id: int) -> None:
        event = self.get_event(event_id)
        self._validate_account(event.account_id, effective_on=event.payment_date)
        security = self.security_repo.get(event.security_id)
        if security is not None and not security.is_active:
            raise ConflictError(
                f"Security {security.ticker} is inactive: its history is read-only",
                detail={"security_id": security.id, "is_active": False, "action": "delete"},
            )
        self.tax_service.ensure_income_source_can_be_deleted(event_id)
        self._delete_linked_transaction(event)
        self.repo.delete(event_id)

    def _sync_linked_transaction(self, event: IncomeEvent) -> None:
        """Create or update the cash movement linked to a coupon or dividend. Use the calculated
        net_amount_eur after withholding: this is the actual cash received. Post it to the
        investment account's reference account.
        """
        security = self.security_repo.get(event.security_id)
        ticker = security.ticker if security else "?"
        label = EVENT_TYPE_LABELS.get(event.event_type, event.event_type)

        event.cash_account_id = self.cash_movement.sync(
            link_field="income_event_id",
            link_id=event.id,
            investment_account_id=event.account_id,
            cash_account_id=event.cash_account_id,
            date=event.payment_date,
            amount_eur=Decimal(event.net_amount_eur),
            description=f"{label} {ticker}",
            category_name=INCOME_EVENT_CATEGORY_NAME,
            category_type="income",
        )

    def _delete_linked_transaction(self, event: IncomeEvent) -> None:
        self.cash_movement.delete(
            link_field="income_event_id",
            link_id=event.id,
            investment_account_id=event.account_id,
            cash_account_id=event.cash_account_id,
            date=event.payment_date,
        )

    def get_summary(
        self, *, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> IncomeEventsSummary:
        validate_date_range(date_from, date_to)
        events = self.repo.list(date_from=date_from, date_to=date_to)
        by_security: dict[int, dict] = {}
        total_net = Decimal("0")

        for e in events:
            net = Decimal(e.net_amount_eur)
            total_net += net
            if e.security_id not in by_security:
                security = self.security_repo.get(e.security_id)
                by_security[e.security_id] = {
                    "ticker": security.ticker if security else "?",
                    "total_net_eur": Decimal("0"),
                    "events_count": 0,
                }
            by_security[e.security_id]["total_net_eur"] += net
            by_security[e.security_id]["events_count"] += 1

        return IncomeEventsSummary(
            period_from=date_from,
            period_to=date_to,
            total_net_eur=total_net,
            by_security=[
                IncomeEventSummaryItem(security_id=sid, **data) for sid, data in by_security.items()
            ],
        )
