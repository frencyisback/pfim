"""Service: SecurityService."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.finance.portfolio import trade_sort_key
from app.models.income_event import IncomeEvent
from app.models.security import Security
from app.models.trade import Trade
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.repositories.trade_repo import TradeRepository
from app.schemas.security import SecurityCreate, SecurityUpdate
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_8_4, normalize_numeric_18_6


def _normalize_optional_security_number(
    value: Decimal | None,
    *,
    field: str,
    label: str,
    normalizer,
) -> Decimal | None:
    if value is None:
        return None
    try:
        return normalizer(value, label=label)
    except ValueError as exc:
        raise ValidationErrorPFIM(
            str(exc),
            detail={"field": field, "value": str(value)},
        ) from exc


def _normalize_security_numbers(values: dict) -> None:
    if "coupon_rate" in values:
        values["coupon_rate"] = _normalize_optional_security_number(
            values["coupon_rate"],
            field="coupon_rate",
            label="The coupon rate",
            normalizer=normalize_numeric_8_4,
        )
    if "face_value" in values:
        values["face_value"] = _normalize_optional_security_number(
            values["face_value"],
            field="face_value",
            label="The face value",
            normalizer=normalize_numeric_18_6,
        )


class SecurityService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = SecurityRepository(db)
        self.price_repo = PriceRepository(db)
        self.trade_repo = TradeRepository(db)

    def list_securities(self, *, only_active: bool = False) -> list[Security]:
        return self.repo.list(only_active=only_active)

    def get_security(self, security_id: int) -> Security:
        security = self.repo.get(security_id)
        if security is None:
            raise NotFoundError(
                f"Security {security_id} not found", detail={"security_id": security_id}
            )
        return security

    def create_security(self, data: SecurityCreate) -> Security:
        if self.repo.get_by_ticker(data.ticker) is not None:
            raise ConflictError(
                f"A security with ticker '{data.ticker}' already exists",
                detail={"ticker": data.ticker},
            )
        if data.isin and self.repo.get_by_isin(data.isin) is not None:
            raise ConflictError(
                f"A security with ISIN '{data.isin}' already exists",
                detail={"isin": data.isin},
            )
        values = data.model_dump()
        _normalize_security_numbers(values)
        security = Security(**values, is_active=True)
        return self.repo.add(security)

    def update_security(self, security_id: int, data: SecurityUpdate) -> Security:
        security = self.get_security(security_id)
        requested = data.model_dump(exclude_unset=True)
        _normalize_security_numbers(requested)
        if requested.get("is_active") is False and security.is_active:
            self._ensure_can_deactivate(security_id)
        for field, value in requested.items():
            setattr(security, field, value)
        return self.repo.update(security)

    def _ensure_can_deactivate(self, security_id: int) -> None:
        today = dt.date.today()
        quantities: dict[int, Decimal] = {}
        inconsistent: dict[int, dict] = {}
        future_trades = []
        for trade in sorted(self.trade_repo.list(security_id=security_id), key=trade_sort_key):
            if trade.date > today:
                future_trades.append(
                    {
                        "trade_id": trade.id,
                        "account_id": trade.account_id,
                        "date": trade.date.isoformat(),
                    }
                )
                continue
            quantity = Decimal(trade.quantity)
            balance = quantities.get(trade.account_id, Decimal(0)) + (
                -quantity if trade.type == "sell" else quantity
            )
            quantities[trade.account_id] = balance
            if balance < 0 and trade.account_id not in inconsistent:
                inconsistent[trade.account_id] = {
                    "account_id": trade.account_id,
                    "trade_id": trade.id,
                    "date": trade.date.isoformat(),
                    "quantity": str(balance),
                }
        positions = [
            {"account_id": account_id, "quantity": str(quantity)}
            for account_id, quantity in sorted(quantities.items())
            if quantity != 0
        ]
        future_income = [
            {
                "income_event_id": income.id,
                "account_id": income.account_id,
                "payment_date": income.payment_date.isoformat(),
            }
            for income in self.db.scalars(
                select(IncomeEvent)
                .where(IncomeEvent.security_id == security_id, IncomeEvent.payment_date > today)
                .order_by(IncomeEvent.payment_date, IncomeEvent.id)
            )
        ]
        blockers = []
        if positions:
            blockers.append(f"{len(positions)} positions still open in investment accounts today")
        if inconsistent:
            blockers.append(f"{len(inconsistent)} investment accounts with inconsistent history")
        if future_trades:
            blockers.append(f"{len(future_trades)} future security trades")
        if future_income:
            blockers.append(f"{len(future_income)} coupons/dividends with future payment dates")
        if blockers:
            raise ConflictError(
                "Cannot deactivate the security: " + ", ".join(blockers),
                detail={
                    "security_id": security_id,
                    "as_of": today.isoformat(),
                    "open_quantity": str(sum(quantities.values(), Decimal(0))),
                    "positions": positions,
                    "inconsistent_accounts": list(inconsistent.values()),
                    "future_trades": future_trades,
                    "future_income_events": future_income,
                    "blockers": blockers,
                },
            )

    def delete_security(self, security_id: int) -> None:
        self.get_security(security_id)
        trade_count = self.db.scalar(
            select(func.count()).select_from(Trade).where(Trade.security_id == security_id)
        )
        if trade_count:
            raise ConflictError(
                f"Cannot delete: {trade_count} trades are linked to this security",
                detail={"security_id": security_id, "trades_count": trade_count},
            )
        income_count = self.db.scalar(
            select(func.count())
            .select_from(IncomeEvent)
            .where(IncomeEvent.security_id == security_id)
        )
        if income_count:
            raise ConflictError(
                f"Cannot delete: {income_count} coupons/dividends are linked to this security",
                detail={"security_id": security_id, "income_events_count": income_count},
            )
        # Price history belongs to the security and has no meaning without it. Delete it together
        # with the security to avoid orphans, which would also block deletion with foreign keys
        # enabled.
        for price in self.price_repo.list_for_security(security_id):
            self.db.delete(price)
        self.repo.delete(security_id)
