"""ORM model: FxRate."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import CheckConstraint, Date, DateTime, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint("date", "from_currency", "to_currency", name="uq_fxrate_date_pair"),
        CheckConstraint(
            "rate >= 0.00000001 AND rate <= 9999999999.99999999",
            name="ck_fx_rates_rate_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    rate: Mapped[float] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="csv_import", nullable=False)
    imported_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
