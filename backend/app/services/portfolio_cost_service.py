"""Service: PortfolioCostService. Recurring portfolio charges such as stamp duty, custody, and
fees create linked cash outflows on the investment account's reference account.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.portfolio_cost import PortfolioCost
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.portfolio_cost_repo import PortfolioCostRepository
from app.schemas.portfolio_cost import PortfolioCostCreate
from app.services.account_service import require_active_account
from app.services.linked_transaction import LinkedCashMovement
from app.utils.currency import convert_to_eur, normalize_currency
from app.utils.date_ranges import validate_date_range
from app.utils.errors import NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import normalize_numeric_18_6

PORTFOLIO_COST_CATEGORY_NAME = "Security Costs"
COST_TYPE_LABELS = {
    "stamp_duty": "Stamp duty",
    "custody_fee": "Custody fee",
    "account_fee": "Securities account fee",
    "other": "Other cost",
}


class PortfolioCostService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = PortfolioCostRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.cash_movement = LinkedCashMovement(db)

    def _validate_account(self, account_id: int, *, effective_on: dt.date) -> None:
        account = self.account_repo.get(account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Account {account_id} not found", detail={"account_id": account_id}
            )
        require_active_account(
            account,
            action="record recurring costs",
            effective_on=effective_on,
        )
        if account.type != "investment":
            raise ValidationErrorPFIM(
                "Recurring costs can only be recorded on investment accounts",
                detail={"account_id": account_id, "type": account.type},
            )
        if account.reference_account_id is None:
            raise ValidationErrorPFIM(
                "The investment account has no reference account configured. "
                "Set one in Settings before recording costs.",
                detail={"account_id": account_id},
            )

    def get_cost(self, cost_id: int) -> PortfolioCost:
        cost = self.repo.get(cost_id)
        if cost is None:
            raise NotFoundError(f"Cost {cost_id} not found", detail={"cost_id": cost_id})
        return cost

    def list_costs(
        self,
        *,
        account_id: int | None = None,
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
    ) -> list[PortfolioCost]:
        validate_date_range(date_from, date_to)
        return self.repo.list(account_id=account_id, date_from=date_from, date_to=date_to)

    def create_cost(self, data: PortfolioCostCreate) -> PortfolioCost:
        self._validate_account(data.account_id, effective_on=data.date)
        payload = data.model_dump()
        currency = normalize_currency(payload.pop("currency"))
        raw_amount = payload["amount"]
        try:
            payload["amount"] = normalize_numeric_18_6(raw_amount, label="The cost amount")
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc), detail={"field": "amount", "value": str(raw_amount)}
            ) from exc
        fx_rate, amount_eur = convert_to_eur(payload["amount"], currency, payload.pop("fx_rate"))
        cash_account_id = self.cash_movement.resolve_cash_account_id(
            data.account_id,
            date=data.date,
        )
        cost = PortfolioCost(
            **payload,
            cash_account_id=cash_account_id,
            currency=currency,
            fx_rate=fx_rate,
            amount_eur=amount_eur,
        )
        saved = self.repo.add(cost)
        self._sync_linked_transaction(saved)
        return saved

    def delete_cost(self, cost_id: int) -> None:
        cost = self.get_cost(cost_id)
        self._validate_account(cost.account_id, effective_on=cost.date)
        self.cash_movement.delete(
            link_field="portfolio_cost_id",
            link_id=cost_id,
            investment_account_id=cost.account_id,
            cash_account_id=cost.cash_account_id,
            date=cost.date,
        )
        self.repo.delete(cost_id)

    def _sync_linked_transaction(self, cost: PortfolioCost) -> None:
        """Create or update the linked cash outflow. Costs always have a negative cash amount."""
        label = COST_TYPE_LABELS.get(cost.cost_type, cost.cost_type)

        cost.cash_account_id = self.cash_movement.sync(
            link_field="portfolio_cost_id",
            link_id=cost.id,
            investment_account_id=cost.account_id,
            cash_account_id=cost.cash_account_id,
            date=cost.date,
            amount_eur=-abs(Decimal(cost.amount_eur)),
            description=f"{label}{f' — {cost.description}' if cost.description else ''}",
            category_name=PORTFOLIO_COST_CATEGORY_NAME,
            category_type="expense",
        )
