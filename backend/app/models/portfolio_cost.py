"""ORM model: PortfolioCost. Recurring portfolio charges such as stamp duty, custody, and account
fees apply to the whole portfolio over time, unlike costs attached to an individual trade.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PortfolioCost(Base):
    __tablename__ = "portfolio_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed: reports filter these costs by period.
    date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    # stamp_duty | custody_fee | account_fee | other
    cost_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Investment account to which the cost relates: cash always leaves its reference account,
    # never the investment account (specification §5.2).
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # Account that actually paid the cost, fixed to prevent future reference changes from
    # rewriting historical cash flows. Nullable only when the legacy origin cannot be
    # determined.
    cash_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Entry-time conversion (app/finance/currency.py): never NULL.
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    amount_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
