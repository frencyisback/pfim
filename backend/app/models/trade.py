"""ORM model: Trade."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint(
            "quote_price >= 0.000001 AND quote_price <= 999999999999.999999",
            name="ck_trades_quote_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # Indexed: position calculations filter by security, and balances by account
    # (specification §12.3).
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    # Account where the cash movement occurred, fixed at creation so later reference-account
    # changes cannot reassign historical trades. Nullable only for legacy rows whose origin
    # cannot be reliably reconstructed.
    #
    cash_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # buy|sell
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    # Settlement unit price, expressed in currency.
    price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    # Unit price in the security's quote currency (securities.currency). Matches price only
    # when settlement and security currencies match. Native FIFO uses this field; cash and
    # totals continue to use the settlement price.
    #
    quote_price: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    # Trade settlement currency, which may differ from the security's quote currency: a US
    # security bought in a European market may settle in EUR. It is therefore not constrained
    # to securities.currency.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # Entry-time conversion (app/finance/currency.py): never NULL. Enables
    # calculate_position_eur and therefore every aggregate total.
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    price_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    total_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
