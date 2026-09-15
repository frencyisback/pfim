"""ORM model: Security."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Date, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Security(Base):
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # stock|bond|etf_equity|etf_bond|fund|commodity (+ legacy 'etf'; see schemas.security)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    market: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(60), nullable=True)
    coupon_rate: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    coupon_freq: Mapped[str | None] = mapped_column(String(20), nullable=True)
    maturity_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    face_value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
