"""ORM model: Account."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "type <> 'investment' OR " "(opening_balance = 0 AND reference_account_id IS NOT NULL)",
            name="ck_accounts_investment_cash_reference",
        ),
        CheckConstraint(
            "type = 'investment' OR reference_account_id IS NULL",
            name="ck_accounts_noninvestment_no_reference",
        ),
        CheckConstraint(
            "closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on",
            name="ck_accounts_lifecycle_dates",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # checking|savings|investment|cash
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    opening_balance: Mapped[float] = mapped_column(Numeric(18, 6), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Keep these columns nullable to avoid inventing backfill dates. NULL in legacy records
    # means an unknown date, so the account is included in every historical snapshot.
    #
    opened_on: Mapped[dt.date | None] = mapped_column(Date, default=dt.date.today, nullable=True)
    closed_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
