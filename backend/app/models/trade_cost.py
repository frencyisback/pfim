"""ORM model: TradeCost."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TradeCost(Base):
    __tablename__ = "trade_costs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"), nullable=False)
    cost_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Entry-time conversion (app/finance/currency.py): never NULL, so cost reports sum EUR
    # amounts without runtime conversion.
    fx_rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False, default=1)
    amount_eur: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    percentage_used: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
