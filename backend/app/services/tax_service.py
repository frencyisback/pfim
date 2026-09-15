"""Service: TaxService. A flexible tax register supporting user-entered events alongside
capital-gain/loss events generated automatically from sales by sync_capital_gain_events.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.finance.portfolio import realized_by_sell_eur
from app.models.income_event import IncomeEvent
from app.models.tax_event import TaxEvent
from app.models.trade import Trade
from app.repositories.tax_event_repo import TaxEventRepository
from app.schemas.tax_event import TaxEventCreate, TaxEventUpdate
from app.services.tax_settings_service import TaxSettingsService
from app.utils.date_ranges import validate_date_range
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import (
    normalize_numeric_8_4,
    normalize_numeric_18_6,
    quantize_numeric_18_6,
)

ORIGIN_MANUAL = "manual"
ORIGIN_AUTOMATIC_TRADE = "automatic_trade"
ORIGIN_LEGACY_UNKNOWN = "legacy_unknown"
_CENT = Decimal("0.01")
_MANUAL_AMOUNT_LABELS = {
    "gross_amount": "The tax event's gross amount",
    "tax_amount": "The tax event's tax amount",
    "net_amount": "The tax event's net amount",
}


class TaxService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TaxEventRepository(db)
        self.settings_service = TaxSettingsService(db)

    def get_event(self, event_id: int) -> TaxEvent:
        event = self.repo.get(event_id)
        if event is None:
            raise NotFoundError(f"Tax event {event_id} not found", detail={"event_id": event_id})
        return event

    def list_events(
        self, *, date_from: dt.date | None = None, date_to: dt.date | None = None
    ) -> list[TaxEvent]:
        validate_date_range(date_from, date_to)
        return self.repo.list(date_from=date_from, date_to=date_to)

    def create_event(self, data: TaxEventCreate) -> TaxEvent:
        values = data.model_dump()
        self._normalize_manual_numeric_fields(values)
        self._validate_capital_amount_sign(
            event_type=values["event_type"], gross_amount=values.get("gross_amount")
        )
        self._validate_related_sources(
            related_trade_id=values["related_trade_id"],
            related_income_id=values["related_income_id"],
        )
        # Origin is not part of the input schema. Everything from the public API is user-owned,
        # even when referencing a trade or income event. Only internal synchronization creates
        # automatic_trade.
        event = TaxEvent(**values, origin=ORIGIN_MANUAL, is_compensated=False)
        return self.repo.add(event)

    @staticmethod
    def _normalize_manual_numeric_fields(values: dict) -> None:
        """Normalize editable decimals before calculations and persistence. SQLite does not
        enforce NUMERIC scale, so normalization keeps validated and reread values consistent.
        tax_amount retains the user's policy; automatic tax rounding to cents stays in
        _apply_capital_gain_amounts.
        """
        for field, label in _MANUAL_AMOUNT_LABELS.items():
            if field not in values or values[field] is None:
                continue
            original = values[field]
            try:
                values[field] = normalize_numeric_18_6(original, label=label)
            except ValueError as exc:
                raise ValidationErrorPFIM(
                    str(exc), detail={"field": field, "value": str(original)}
                ) from exc

        if "tax_rate" in values and values["tax_rate"] is not None:
            original = values["tax_rate"]
            try:
                values["tax_rate"] = normalize_numeric_8_4(
                    original, label="The tax event's tax rate"
                )
            except ValueError as exc:
                raise ValidationErrorPFIM(
                    str(exc), detail={"field": "tax_rate", "value": str(original)}
                ) from exc

    @staticmethod
    def _validate_capital_amount_sign(
        *, event_type: str, gross_amount: Decimal | float | None
    ) -> None:
        """Preserve signs used in tax aggregation. Capital losses must be negative, or reports
        would treat them as taxable gains. Other event types remain flexible.
        """
        if gross_amount is None or event_type not in {"capital_gain", "capital_loss"}:
            return
        amount = Decimal(gross_amount)
        invalid = (event_type == "capital_gain" and amount < 0) or (
            event_type == "capital_loss" and amount > 0
        )
        if invalid:
            expected = (
                "greater than or equal to zero"
                if event_type == "capital_gain"
                else ("less than or equal to zero")
            )
            raise ValidationErrorPFIM(
                f"The gross amount of {event_type} must be {expected}",
                detail={
                    "field": "gross_amount",
                    "event_type": event_type,
                    "value": str(amount),
                    "expected_sign": (
                        "non_negative" if event_type == "capital_gain" else "non_positive"
                    ),
                },
            )

    def _validate_related_sources(
        self, *, related_trade_id: int | None, related_income_id: int | None
    ) -> None:
        if related_trade_id is not None and related_income_id is not None:
            # Service protection supplements Pydantic validation and database CHECK constraints:
            # callers may bypass the router.
            raise ValidationErrorPFIM(
                "A tax event may reference either a trade or an income payment, not both",
                detail={
                    "related_trade_id": related_trade_id,
                    "related_income_id": related_income_id,
                },
            )
        if related_trade_id is not None and self.db.get(Trade, related_trade_id) is None:
            raise ValidationErrorPFIM(
                f"Trade {related_trade_id} not found",
                detail={"related_trade_id": related_trade_id},
            )
        if related_income_id is not None and self.db.get(IncomeEvent, related_income_id) is None:
            raise ValidationErrorPFIM(
                f"Income payment {related_income_id} not found",
                detail={"related_income_id": related_income_id},
            )

    def update_event(self, event_id: int, data: TaxEventUpdate) -> TaxEvent:
        event = self.get_event(event_id)
        self._ensure_direct_mutation_allowed(event, action="edit")
        update_data = data.model_dump(exclude_unset=True)
        self._normalize_manual_numeric_fields(update_data)
        self._validate_capital_amount_sign(
            event_type=update_data.get("event_type", event.event_type),
            gross_amount=update_data.get("gross_amount", event.gross_amount),
        )
        self._validate_related_sources(
            related_trade_id=update_data.get("related_trade_id", event.related_trade_id),
            related_income_id=update_data.get("related_income_id", event.related_income_id),
        )
        for field, value in update_data.items():
            setattr(event, field, value)
        return self.repo.update(event)

    def delete_event(self, event_id: int) -> None:
        event = self.get_event(event_id)
        self._ensure_direct_mutation_allowed(event, action="delete")
        self.repo.delete(event_id)

    @staticmethod
    def _ensure_direct_mutation_allowed(event: TaxEvent, *, action: str) -> None:
        if event.origin == ORIGIN_AUTOMATIC_TRADE:
            raise ConflictError(
                f"Cannot {action} an automatic tax event directly: "
                "correct the security trade that generated it",
                detail={
                    "tax_event_id": event.id,
                    "origin": event.origin,
                    "related_trade_id": event.related_trade_id,
                },
            )

    @staticmethod
    def _capital_gain_description(realized_delta: Decimal, ticker: str) -> str:
        kind = "Capital gain" if realized_delta > 0 else "Capital loss"
        return f"{kind} realized on {ticker}"

    def _apply_capital_gain_amounts(
        self, event: TaxEvent, realized_delta: Decimal, tax_rate: Decimal
    ) -> None:
        """Write amounts for a capital-gain/loss event. tax_amount and net_amount describe this
        sale before loss offsets and must never be summed as total tax due. Only
        ReportService.fiscal_position computes period tax after offsetting losses.
        """
        realized_delta = normalize_numeric_18_6(realized_delta, label="The sale's taxable amount")
        tax_rate = normalize_numeric_8_4(tax_rate, label="The capital-gains tax rate")
        is_gain = realized_delta > 0
        tax_amount_at_cent = (
            (realized_delta * tax_rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            if is_gain
            else Decimal("0")
        )
        tax_amount = normalize_numeric_18_6(
            tax_amount_at_cent,
            label="The gross capital-gains tax",
        )
        event.event_type = "capital_gain" if is_gain else "capital_loss"
        event.gross_amount = realized_delta
        event.tax_rate = tax_rate if is_gain else None
        event.tax_amount = tax_amount if is_gain else None
        event.net_amount = normalize_numeric_18_6(
            realized_delta - tax_amount,
            label="The sale's net tax amount",
        )

    def sync_capital_gain_events(self, trades: list, *, ticker: str) -> None:
        """Synchronize one security's tax register with current FIFO after every trade mutation,
        including purchases. Backdated trades and removed sales change later consumed lots and
        taxable amounts. Update existing automatic events to preserve IDs and status; the
        public API cannot edit them. Never adopt manual rows. Remove events for break-even
        sales, including gains rounded to zero at micro-euro precision.
        """
        realized = realized_by_sell_eur(trades)
        sells = [t for t in trades if t.type == "sell"]

        sell_ids = [t.id for t in sells]
        linked_events = self.repo.list_for_trades(sell_ids)
        legacy = [event for event in linked_events if event.origin == ORIGIN_LEGACY_UNKNOWN]
        if legacy:
            # A linked legacy row may be a customized old automatic entry. Creating another could
            # double-count taxes. Stop for an explicit decision instead of heuristically reclassifying
            # or deleting data.
            #
            raise ConflictError(
                "Cannot synchronize the tax register: legacy events are "
                "linked to the affected trades",
                detail={
                    "tax_event_ids": [event.id for event in legacy],
                    "trade_ids": sorted({event.related_trade_id for event in legacy}),
                },
            )

        automatic = {
            event.related_trade_id: event for event in self.repo.list_automatic_for_trades(sell_ids)
        }

        tax_rate = self.settings_service.get_rate("capital_gains_tax_rate")

        for trade in sells:
            raw_realized_delta = realized.get(trade.id, Decimal("0"))
            try:
                realized_delta = quantize_numeric_18_6(
                    raw_realized_delta,
                    label="The sale's taxable amount",
                )
            except ValueError as exc:
                raise ValidationErrorPFIM(
                    str(exc),
                    detail={
                        "field": "gross_amount",
                        "trade_id": trade.id,
                        "value": str(raw_realized_delta),
                    },
                ) from exc
            event = automatic.get(trade.id)

            if realized_delta == 0:
                if event is not None:
                    self.repo.delete(event.id)
                continue

            if event is None:
                event = TaxEvent(
                    event_date=trade.date,
                    related_trade_id=trade.id,
                    origin=ORIGIN_AUTOMATIC_TRADE,
                    description=self._capital_gain_description(realized_delta, ticker),
                    is_compensated=False,
                )
                self._apply_capital_gain_amounts(event, realized_delta, tax_rate)
                self.repo.add(event)
                continue

            event.event_date = trade.date
            event.description = self._capital_gain_description(realized_delta, ticker)
            self._apply_capital_gain_amounts(event, realized_delta, tax_rate)
            self.repo.update(event)

    def delete_events_for_trade(self, trade_id: int) -> None:
        """Delete only automatic events owned by FIFO. Linked manual or legacy rows are
        independent data and explicitly block trade deletion instead of being silently
        cascaded or causing a generic foreign-key error.
        """
        linked = self.repo.list_for_trades([trade_id])
        blockers = [event for event in linked if event.origin != ORIGIN_AUTOMATIC_TRADE]
        if blockers:
            raise ConflictError(
                "Cannot delete the trade: linked manual or legacy tax events exist; "
                "unlink or explicitly manage them first",
                detail={
                    "trade_id": trade_id,
                    "tax_event_ids": [event.id for event in blockers],
                },
            )
        for event in linked:
            self.repo.delete(event.id)

    def ensure_income_source_can_be_deleted(self, income_id: int) -> None:
        """Reject implicit loss of tax references to income. No automatic coupon tax events are
        generated, so linked manual or legacy rows must be explicitly unlinked, corrected, or
        deleted before removing the income payment.
        """
        linked = self.repo.list_for_income(income_id)
        if linked:
            raise ConflictError(
                "Cannot delete the income payment: linked tax events exist; "
                "unlink or explicitly manage them first",
                detail={
                    "income_event_id": income_id,
                    "tax_event_ids": [event.id for event in linked],
                    "tax_event_origins": [event.origin for event in linked],
                },
            )
