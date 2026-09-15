"""ORM model: CsvImportProfile. Persisted transaction CSV column mappings, editable by users in
Settings.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CsvImportProfile(Base):
    __tablename__ = "csv_import_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    delimiter: Mapped[str] = mapped_column(String(5), nullable=False, default=",")
    skip_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    date_format: Mapped[str] = mapped_column(String(30), nullable=False, default="%Y-%m-%d")
    date_column: Mapped[str] = mapped_column(String(60), nullable=False, default="date")
    description_column: Mapped[str] = mapped_column(
        String(60), nullable=False, default="description"
    )
    amount_column: Mapped[str] = mapped_column(String(60), nullable=False, default="amount")
    category_column: Mapped[str | None] = mapped_column(String(60), nullable=True)
    decimal_separator: Mapped[str] = mapped_column(String(1), nullable=False, default=".")
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )
