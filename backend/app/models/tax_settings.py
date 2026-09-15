"""ORM model: TaxSetting. A flexible key/value table for tax rates that users can configure in
Settings.
"""

from __future__ import annotations

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaxSetting(Base):
    __tablename__ = "tax_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)  # Percentage, e.g. 26.00.
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
