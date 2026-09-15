"""ORM model: Transaction."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("amount <> 0", name="ck_transactions_amount_nonzero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed: balances, transaction lists, and period/category reports filter on these three
    # columns (specification §12.3).
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False, index=True
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)  # + income, - expense
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Entry-time conversion (app/finance/currency.py): never NULL. Account balances, net
    # worth, and income statements always sum amount_eur.
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    amount_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    import_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    import_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of free-form tags.
    transfer_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    income_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("income_events.id"), nullable=True
    )
    portfolio_cost_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_costs.id"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
