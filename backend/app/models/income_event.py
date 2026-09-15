"""ORM model: IncomeEvent."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IncomeEvent(Base):
    __tablename__ = "income_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # Cash destination fixed at creation. NULL is allowed only for legacy records without a
    # linked transaction from which to recover it.
    cash_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # dividend|coupon|return_of_capital
    ex_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    quantity_held: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    amount_per_unit: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Entry-time conversion (app/finance/currency.py): never NULL. total_eur is gross;
    # net_amount_eur is net of withholding and feeds cash balances and returns.
    #
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    total_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    tax_withheld: Mapped[float] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    net_amount_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
