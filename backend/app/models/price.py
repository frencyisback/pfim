"""ORM model: Price."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Price(Base):
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("security_id", "date", name="uq_price_security_date"),
        UniqueConstraint("origin_trade_id", name="uq_prices_origin_trade_id"),
        CheckConstraint(
            "price_close >= 0.000001 AND price_close <= 999999999999.999999",
            name="ck_prices_price_close_positive",
        ),
        CheckConstraint(
            "fx_rate >= 0.00000001 AND fx_rate <= 9999999999.99999999",
            name="ck_prices_fx_rate_positive",
        ),
        CheckConstraint(
            "price_close_eur >= 0.000001 AND price_close_eur <= 999999999999.999999",
            name="ck_prices_price_close_eur_positive",
        ),
        CheckConstraint(
            "(source = 'trade' AND origin_trade_id IS NOT NULL) OR "
            "(source <> 'trade' AND origin_trade_id IS NULL)",
            name="ck_prices_trade_origin_consistent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # Market quote in the security's currency.
    price_close: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    # EUR equivalent fixed at entry (see app/finance/currency.py), used to value positions in
    # aggregate totals without looking up an exchange rate during calculation.
    #
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    price_close_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="csv_import", nullable=False)
    # Populated only for prices created automatically from a trade. The foreign key allows
    # deletion or reassignment of derived data without confusing it with an authoritative
    # manual or imported price.
    origin_trade_id: Mapped[int | None] = mapped_column(
        ForeignKey("trades.id", ondelete="CASCADE"), nullable=True
    )
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
