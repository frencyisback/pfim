"""ORM model: ForecastScenario."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ForecastScenario(Base):
    __tablename__ = "forecast_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    horizon_years: Mapped[int] = mapped_column(Integer, nullable=False)
    parameters: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
