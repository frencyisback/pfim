"""Service: TradeService. CRUD orchestration for trades and costs, with FIFO validation rejecting
short sales through HTTP 409 CONFLICT.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from app.finance.portfolio import calculate_position, trade_sort_key
from app.models.price import Price
from app.models.trade import Trade
from app.models.trade_cost import TradeCost
from app.repositories.account_repo import AccountRepository
from app.repositories.category_repo import CategoryRepository
from app.repositories.price_repo import PriceRepository
from app.repositories.security_repo import SecurityRepository
from app.repositories.trade_repo import TradeRepository
from app.schemas.trade import TradeCostCreate, TradeCreate, TradeRead
from app.services.account_service import require_active_account
from app.services.linked_transaction import LinkedCashMovement
from app.services.tax_service import TaxService
from app.utils.currency import convert_to_eur, normalize_currency
from app.utils.errors import ConflictError, NotFoundError, ValidationErrorPFIM
from app.utils.numeric_limits import (
    NUMERIC_18_6_MAX,
    NUMERIC_18_6_MIN_POSITIVE,
    normalize_fx_rate,
    normalize_numeric_8_4,
    normalize_numeric_18_6,
)

BUY_CATEGORY_NAME = "Security Purchase"
SELL_CATEGORY_NAME = "Security Sale"


def _fmt_decimal(value) -> str:
    """Format a Decimal without unnecessary trailing zeros: 100.000000 becomes 100."""
    s = f"{Decimal(value):f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


@dataclass
class _CandidateTrade:
    """Lightweight, nonpersisted trade representation for validating FIFO before database writes.
    Avoid assigning an ID to an unsaved ORM instance, which would override database
    autoincrement.
    """

    id: int
    type: str
    date: dt.date
    quantity: Decimal
    price: Decimal


class TradeService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TradeRepository(db)
        self.security_repo = SecurityRepository(db)
        self.price_repo = PriceRepository(db)
        self.account_repo = AccountRepository(db)
        self.category_repo = CategoryRepository(db)
        self.tax_service = TaxService(db)
        self.cash_movement = LinkedCashMovement(db)

    def get_trade(self, trade_id: int) -> Trade:
        trade = self.repo.get(trade_id)
        if trade is None:
            raise NotFoundError(f"Trade {trade_id} not found", detail={"trade_id": trade_id})
        return trade

    def list_trades(
        self, *, security_id: int | None = None, account_id: int | None = None
    ) -> list[Trade]:
        return self.repo.list(security_id=security_id, account_id=account_id)

    def total_costs_eur(self, trade_id: int) -> Decimal:
        # Entry-time conversion guarantees amount_eur, so every cost can be included in the sum.
        #
        return sum(
            (Decimal(c.amount_eur) for c in self.repo.list_costs(trade_id)), start=Decimal("0")
        )

    def to_read_with_costs(self, trade: Trade) -> TradeRead:
        """Include total costs in TradeRead for immediate display without opening the costs
        dialog.
        """
        base = TradeRead.model_validate(trade)
        return base.model_copy(update={"total_costs_eur": self.total_costs_eur(trade.id)})

    def list_trades_with_costs(
        self, *, security_id: int | None = None, account_id: int | None = None
    ) -> list[TradeRead]:
        """List trades with cost totals, loading all costs in a batch to avoid a query per row."""
        trades = self.repo.list(security_id=security_id, account_id=account_id)
        costs_by_trade = self.repo.costs_grouped_by_trade()
        return [
            TradeRead.model_validate(t).model_copy(
                update={
                    "total_costs_eur": sum(
                        (Decimal(c.amount_eur) for c in costs_by_trade.get(t.id, [])),
                        start=Decimal("0"),
                    )
                }
            )
            for t in trades
        ]

    def _validate_refs(
        self,
        security_id: int,
        account_id: int,
        *,
        effective_on: dt.date,
    ):
        security = self.security_repo.get(security_id)
        if security is None:
            raise ValidationErrorPFIM(
                f"Security {security_id} not found", detail={"security_id": security_id}
            )
        if not security.is_active:
            raise ValidationErrorPFIM(
                f"Security {security.ticker} is inactive: it cannot receive new trades",
                detail={"security_id": security_id, "is_active": False},
            )
        account = self.account_repo.get(account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Account {account_id} not found", detail={"account_id": account_id}
            )
        require_active_account(
            account,
            action="record security trades",
            effective_on=effective_on,
        )
        if account.type != "investment":
            raise ValidationErrorPFIM(
                "Security purchases and sales can only be recorded on investment accounts",
                detail={"account_id": account_id, "type": account.type},
            )
        if account.reference_account_id is None:
            raise ValidationErrorPFIM(
                "The investment account has no reference account configured. "
                "Set one in Settings before recording trades.",
                detail={"account_id": account_id},
            )
        return security

    @staticmethod
    def _normalize_positive_numeric_18_6(value: Decimal, *, field: str, label: str) -> Decimal:
        """Normalize a positive value to its persisted representation. SQLite does not enforce
        NUMERIC(18, 6), so normalize both individual inputs and derived products.
        """
        try:
            decimal_value = normalize_numeric_18_6(Decimal(value), label=label)
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc),
                detail={"field": field, "value": str(value)},
            ) from exc
        if decimal_value < NUMERIC_18_6_MIN_POSITIVE:
            raise ValidationErrorPFIM(
                f"{label} must be between {NUMERIC_18_6_MIN_POSITIVE} " f"and {NUMERIC_18_6_MAX}",
                detail={"field": field, "value": str(value)},
            )
        return decimal_value

    def _resolve_quote_price(
        self,
        data: TradeCreate,
        *,
        settlement_price: Decimal,
        settlement_currency: str,
        quote_currency: str,
        price_eur: Decimal,
    ) -> Decimal:
        """Validate and normalize the price in the quotation currency."""
        quote_price = data.quote_price
        same_currency = settlement_currency == quote_currency
        if quote_price is None:
            if not same_currency:
                raise ValidationErrorPFIM(
                    "A price in the quotation currency is required when the "
                    "settlement currency differs from the security's currency",
                    detail={
                        "settlement_currency": settlement_currency,
                        "quote_currency": quote_currency,
                        "quote_price": None,
                    },
                )
            quote_price = settlement_price

        quote_price = self._normalize_positive_numeric_18_6(
            quote_price,
            field="quote_price",
            label="The quoted price",
        )
        if same_currency and quote_price != settlement_price:
            raise ValidationErrorPFIM(
                "The quoted price must equal the settlement price when " "the currencies match",
                detail={
                    "currency": quote_currency,
                    "price": str(settlement_price),
                    "quote_price": str(quote_price),
                },
            )

        if quote_currency == "EUR" and quote_price != price_eur:
            raise ValidationErrorPFIM(
                "The settlement price converted to EUR does not match the " "EUR quotation price",
                detail={
                    "price_eur": str(price_eur),
                    "quote_price": str(quote_price),
                },
            )
        return quote_price

    @classmethod
    def _quote_price_conversion_values(
        cls,
        *,
        quote_price: Decimal,
        price_eur: Decimal,
        quote_currency: str,
        known_quote_fx: Decimal | None = None,
    ) -> tuple[Decimal, Decimal]:
        """Consistent quoted-price exchange rate and EUR equivalent. When quote and settlement
        currencies match, retain the authoritative trade rate; derive an implied ratio only
        when they differ.
        """
        quote_price = cls._normalize_positive_numeric_18_6(
            quote_price,
            field="quote_price",
            label="The quoted price",
        )
        price_eur = cls._normalize_positive_numeric_18_6(
            price_eur,
            field="price_eur",
            label="The price in EUR",
        )
        if quote_currency == "EUR":
            return Decimal("1.00000000"), quote_price
        quote_fx = known_quote_fx if known_quote_fx is not None else price_eur / quote_price
        try:
            quote_fx = normalize_fx_rate(quote_fx, label="The implied exchange rate")
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc),
                detail={"field": "quote_fx_rate", "value": str(quote_fx)},
            ) from exc
        try:
            quote_price_eur = normalize_numeric_18_6(
                quote_price * quote_fx,
                label="The quoted price's EUR equivalent",
            )
        except ValueError as exc:
            raise ValidationErrorPFIM(
                str(exc),
                detail={"field": "quote_price_eur", "value": str(quote_price * quote_fx)},
            ) from exc
        return quote_fx, quote_price_eur

    @classmethod
    def _quote_price_conversion(
        cls, trade: Trade, *, quote_currency: str
    ) -> tuple[Decimal, Decimal]:
        return cls._quote_price_conversion_values(
            quote_price=Decimal(trade.quote_price),
            price_eur=Decimal(trade.price_eur),
            quote_currency=quote_currency,
            known_quote_fx=(
                Decimal(trade.fx_rate)
                if normalize_currency(trade.currency) == quote_currency
                else None
            ),
        )

    def _require_writable_trade(self, trade: Trade, *, action: str) -> None:
        account = self.account_repo.get(trade.account_id)
        if account is None:
            raise ValidationErrorPFIM(
                f"Account {trade.account_id} not found",
                detail={"account_id": trade.account_id, "trade_id": trade.id},
            )
        require_active_account(
            account,
            action=action,
            effective_on=trade.date,
        )
        security = self.security_repo.get(trade.security_id)
        if security is None:
            raise ValidationErrorPFIM(
                f"Security {trade.security_id} not found",
                detail={"security_id": trade.security_id, "trade_id": trade.id},
            )
        if not security.is_active:
            raise ConflictError(
                f"Security {security.ticker} is inactive: its history is read-only",
                detail={"security_id": security.id, "is_active": False, "action": action},
            )

    def _validate_fifo_feasibility(self, security_id: int, candidate_trades: list[Trade]) -> None:
        """Use the finance engine to verify that existing trades plus the candidate do not create
        a short sale.
        """
        try:
            calculate_position(candidate_trades)
        except ValueError as exc:
            raise ConflictError(str(exc), detail={"security_id": security_id}) from exc

    @staticmethod
    def _validate_account_quantities(
        account_id: int,
        security_id: int,
        candidate_trades: list[Trade | _CandidateTrade],
    ) -> None:
        """Check chronological ownership within one investment account. The caller supplies only
        that account/security pair. Use quantities without changing global FIFO for costs,
        returns, and taxes. Include later and future sales that a backdated write could leave
        uncovered.
        """
        available = Decimal("0")
        for trade in sorted(candidate_trades, key=trade_sort_key):
            quantity = Decimal(trade.quantity)
            if trade.type == "buy":
                available += quantity
            elif trade.type == "sell":
                if quantity > available:
                    raise ConflictError(
                        f"Sale in investment account {account_id} on {trade.date.isoformat()}: "
                        f"requested {_fmt_decimal(quantity)} units, "
                        f"available {_fmt_decimal(available)} in the same investment account",
                        detail={
                            "account_id": account_id,
                            "security_id": security_id,
                            "first_invalid_trade_id": (
                                None if isinstance(trade, _CandidateTrade) else trade.id
                            ),
                            "first_invalid_is_candidate": isinstance(trade, _CandidateTrade),
                            "date": trade.date.isoformat(),
                            "requested_quantity": str(quantity),
                            "available_quantity": str(available),
                        },
                    )
                available -= quantity

    def _linked_transaction_amount(self, trade: Trade) -> Decimal:
        """Trade cash impact in EUR: purchases are outflows of price plus costs; sales are
        inflows of price less costs. Entry-time conversion ensures total_eur and EUR costs
        exist so every trade creates its cash movement.
        """
        costs_eur = sum(
            (Decimal(c.amount_eur) for c in self.repo.list_costs(trade.id)), start=Decimal("0")
        )
        if trade.type == "buy":
            return -(Decimal(trade.total_eur) + costs_eur)
        return Decimal(trade.total_eur) - costs_eur

    def _record_trade_price(self, trade: Trade) -> None:
        """Fill price-history gaps with the trade's observed execution price. Never overwrite an
        existing manual or imported closing price, which is the official market observation
        for that date.
        """
        existing = self.price_repo.get_by_security_and_date(trade.security_id, trade.date)
        if existing is not None:
            return
        security = self.security_repo.get(trade.security_id)
        quote_currency = normalize_currency(security.currency)
        quote_fx, quote_price_eur = self._quote_price_conversion(
            trade, quote_currency=quote_currency
        )
        self.price_repo.upsert(
            Price(
                security_id=trade.security_id,
                date=trade.date,
                price_close=trade.quote_price,
                fx_rate=quote_fx,
                price_close_eur=quote_price_eur,
                source="trade",
                origin_trade_id=trade.id,
            )
        )

    def _reassign_owned_trade_price(self, trade: Trade, remaining: list[Trade]) -> None:
        """Transfer ownership of a derived price to the first surviving trade that day. Without a
        replacement, ON DELETE CASCADE removes it with its owner. Manual/imported prices have
        no owner and remain untouched.
        """
        owned_price = self.price_repo.get_by_origin_trade_id(trade.id)
        if owned_price is None:
            return
        replacements = [candidate for candidate in remaining if candidate.date == trade.date]
        if not replacements:
            return
        replacement = min(replacements, key=lambda candidate: candidate.id)
        security = self.security_repo.get(replacement.security_id)
        quote_fx, quote_price_eur = self._quote_price_conversion(
            replacement,
            quote_currency=normalize_currency(security.currency),
        )
        owned_price.price_close = replacement.quote_price
        owned_price.fx_rate = quote_fx
        owned_price.price_close_eur = quote_price_eur
        owned_price.source = "trade"
        owned_price.origin_trade_id = replacement.id
        self.db.flush()

    def _sync_linked_transaction(self, trade: Trade) -> None:
        """Create or update linked trade cash using the Security Purchase/Security Sale system
        categories. Always post to the investment account's reference account.
        LinkedCashMovement shares the procedure with income and costs.
        """
        security = self.security_repo.get(trade.security_id)
        ticker = security.ticker if security else "?"
        quantity_str = _fmt_decimal(trade.quantity)
        price_str = _fmt_decimal(trade.price)
        cash_amount = self._linked_transaction_amount(trade)
        if trade.type == "buy":
            description = f"Purchase {quantity_str} {ticker} @ {price_str}"
            category_name, category_type = BUY_CATEGORY_NAME, "expense"
        else:
            description = f"Sale {quantity_str} {ticker} @ {price_str}"
            if cash_amount < 0:
                # Do not repair incompatible legacy state by reclassifying a sale as an expense: sale
                # costs cannot exceed proceeds. Failing closed prevents later resynchronization from
                # making invalid data appear plausible instead of requiring explicit correction.
                #
                #
                raise ConflictError(
                    "The sale's total costs exceed its gross proceeds",
                    detail={
                        "trade_id": trade.id,
                        "gross_proceeds_eur": str(Decimal(trade.total_eur)),
                        "total_costs_eur": str(Decimal(trade.total_eur) - cash_amount),
                    },
                )
            category_name, category_type = SELL_CATEGORY_NAME, "income"

        trade.cash_account_id = self.cash_movement.sync(
            link_field="trade_id",
            link_id=trade.id,
            investment_account_id=trade.account_id,
            cash_account_id=trade.cash_account_id,
            date=trade.date,
            amount_eur=cash_amount,
            description=description,
            category_name=category_name,
            category_type=category_type,
        )

    def _delete_linked_transaction(self, trade: Trade) -> None:
        self.cash_movement.delete(
            link_field="trade_id",
            link_id=trade.id,
            investment_account_id=trade.account_id,
            cash_account_id=trade.cash_account_id,
            date=trade.date,
        )

    def _sync_capital_gain_events(self, security_id: int) -> None:
        """Synchronize the tax register with the security's current FIFO after every write
        changing its trade sequence, including purchases. Backdated purchases or deleted
        earlier sales alter the taxable amounts of later sales.
        """
        security = self.security_repo.get(security_id)
        self.tax_service.sync_capital_gain_events(
            self.repo.list(security_id=security_id),
            ticker=security.ticker if security else "?",
        )

    def create_trade(self, data: TradeCreate) -> Trade:
        security = self._validate_refs(
            data.security_id,
            data.account_id,
            effective_on=data.date,
        )

        quantity = self._normalize_positive_numeric_18_6(
            data.quantity,
            field="quantity",
            label="The quantity",
        )
        settlement_price = self._normalize_positive_numeric_18_6(
            data.price,
            field="price",
            label="The settlement price",
        )
        currency = normalize_currency(data.currency)
        total_amount = self._normalize_positive_numeric_18_6(
            quantity * settlement_price,
            field="total_amount",
            label="The settlement value",
        )
        fx_rate, total_eur = convert_to_eur(total_amount, currency, data.fx_rate)
        _, price_eur = convert_to_eur(settlement_price, currency, fx_rate)
        quote_price = self._resolve_quote_price(
            data,
            settlement_price=settlement_price,
            settlement_currency=currency,
            quote_currency=normalize_currency(security.currency),
            price_eur=price_eur,
        )
        # The implied quote-currency exchange rate is a trade invariant. Validate it even when an
        # authoritative quote already exists for the same date.
        #
        self._quote_price_conversion_values(
            quote_price=quote_price,
            price_eur=price_eur,
            quote_currency=normalize_currency(security.currency),
            known_quote_fx=(fx_rate if currency == normalize_currency(security.currency) else None),
        )
        cash_account_id = self.cash_movement.resolve_cash_account_id(
            data.account_id,
            date=data.date,
        )
        trade = Trade(
            security_id=data.security_id,
            account_id=data.account_id,
            cash_account_id=cash_account_id,
            type=data.type,
            date=data.date,
            quantity=quantity,
            price=settlement_price,
            quote_price=quote_price,
            currency=currency,
            fx_rate=fx_rate,
            price_eur=price_eur,
            total_amount=total_amount,
            total_eur=total_eur,
            notes=data.notes,
        )

        # Only sales can be infeasible: a purchase adds units and cannot leave a recorded sale
        # uncovered.
        if data.type == "sell":
            existing = self.repo.list(security_id=data.security_id)
            candidate = _CandidateTrade(
                id=max((t.id for t in existing), default=0) + 1,
                type=data.type,
                date=data.date,
                quantity=quantity,
                price=settlement_price,
            )
            self._validate_account_quantities(
                data.account_id,
                data.security_id,
                [t for t in existing if t.account_id == data.account_id] + [candidate],
            )
            self._validate_fifo_feasibility(data.security_id, existing + [candidate])

        saved_trade = self.repo.add(trade)
        self._sync_capital_gain_events(data.security_id)
        self._sync_linked_transaction(saved_trade)
        self._record_trade_price(saved_trade)
        return saved_trade

    def delete_trade(self, trade_id: int) -> None:
        trade = self.get_trade(trade_id)
        self._require_writable_trade(trade, action="delete the trade")
        security_id = (
            trade.security_id
        )  # Read before deletion, after which the instance is unreadable.
        remaining = [t for t in self.repo.list(security_id=security_id) if t.id != trade_id]
        if trade.type == "buy":
            self._validate_account_quantities(
                trade.account_id,
                security_id,
                [t for t in remaining if t.account_id == trade.account_id],
            )
        # Deleting a sale, like adding a purchase, cannot worsen legacy position deficits. Retain
        # all global and linked-source guards without forcing automatic correction.
        #
        # Recalculate FIFO without this trade. If another sale depends on this purchase, block
        # deletion with 409.
        self._validate_fifo_feasibility(security_id, remaining)
        self._delete_linked_transaction(trade)
        self.tax_service.delete_events_for_trade(trade_id)
        # Costs belong to the trade and are meaningless without it. Delete them explicitly to
        # avoid orphan trade_costs rows, which would block deletion with foreign keys enabled.
        #
        #
        for cost in self.repo.list_costs(trade_id):
            self.repo.delete_cost(cost.id)
        self._reassign_owned_trade_price(trade, remaining)
        self.repo.delete(trade_id)
        # Remaining sales now consume different lots. Update the tax register so it reflects the
        # new sequence rather than the previous amounts.
        #
        self._sync_capital_gain_events(security_id)

    def add_cost(self, trade_id: int, data: TradeCostCreate) -> TradeCost:
        """When percentage replaces amount, calculate it once on the trade total and freeze the
        resulting fixed charge; later trade edits do not recalculate it. Percentage costs
        inherit the trade currency and exchange rate. Explicit amounts instead use their own
        declared currency and rate.
        """
        trade = self.get_trade(trade_id)
        self._require_writable_trade(trade, action="add costs to a trade")
        percentage_used = None
        if data.percentage is not None:
            try:
                percentage_used = normalize_numeric_8_4(
                    data.percentage,
                    label="The cost percentage",
                )
            except ValueError as exc:
                raise ValidationErrorPFIM(
                    str(exc),
                    detail={"field": "percentage", "value": str(data.percentage)},
                ) from exc
            if percentage_used <= 0:
                raise ValidationErrorPFIM(
                    "The cost percentage must be greater than zero",
                    detail={"field": "percentage", "value": str(data.percentage)},
                )
            amount = Decimal(trade.total_amount) * percentage_used / Decimal("100")
            currency = trade.currency
            declared_rate = Decimal(trade.fx_rate)
        else:
            amount = data.amount
            currency = normalize_currency(data.currency)
            declared_rate = data.fx_rate

        amount = self._normalize_positive_numeric_18_6(
            amount,
            field="amount",
            label="The cost amount",
        )
        fx_rate, amount_eur = convert_to_eur(amount, currency, declared_rate)
        if trade.type == "sell":
            previous_costs_eur = self.total_costs_eur(trade_id)
            candidate_costs_eur = previous_costs_eur + amount_eur
            gross_proceeds_eur = Decimal(trade.total_eur)
            if candidate_costs_eur > gross_proceeds_eur:
                # Validate before INSERT or synchronization. On error, preserve both TradeCost records and
                # the linked sale cash flow. One commit/rollback per request (database.get_db) prevents
                # partial writes.
                #
                #
                raise ConflictError(
                    "Cannot add this cost: the sale's total costs "
                    "would exceed its gross proceeds",
                    detail={
                        "trade_id": trade_id,
                        "gross_proceeds_eur": str(gross_proceeds_eur),
                        "previous_costs_eur": str(previous_costs_eur),
                        "requested_cost_eur": str(amount_eur),
                        "candidate_costs_eur": str(candidate_costs_eur),
                    },
                )
        cost = TradeCost(
            trade_id=trade_id,
            cost_type=data.cost_type,
            description=data.description,
            amount=amount,
            currency=currency,
            fx_rate=fx_rate,
            amount_eur=amount_eur,
            percentage_used=percentage_used,
            notes=data.notes,
        )
        saved_cost = self.repo.add_cost(cost)
        self._sync_linked_transaction(trade)
        return saved_cost

    def list_costs(self, trade_id: int) -> list[TradeCost]:
        self.get_trade(trade_id)
        return self.repo.list_costs(trade_id)

    def delete_cost(self, trade_id: int, cost_id: int) -> None:
        trade = self.get_trade(trade_id)
        self._require_writable_trade(trade, action="delete costs from a trade")
        cost = self.repo.get_cost(cost_id)
        if cost is None or cost.trade_id != trade_id:
            raise NotFoundError(
                f"Cost {cost_id} not found for trade {trade_id}",
                detail={"trade_id": trade_id, "cost_id": cost_id},
            )
        self.repo.delete_cost(cost_id)
        self._sync_linked_transaction(trade)
