"""ORM model: TaxEvent."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaxEvent(Base):
    __tablename__ = "tax_events"
    __table_args__ = (
        CheckConstraint(
            "origin IN ('manual', 'automatic_trade', 'legacy_unknown')",
            name="ck_tax_events_origin",
        ),
        CheckConstraint(
            "related_trade_id IS NULL OR related_income_id IS NULL",
            name="ck_tax_events_single_related_source",
        ),
        CheckConstraint(
            "origin <> 'automatic_trade' OR "
            "(related_trade_id IS NOT NULL AND related_income_id IS NULL)",
            name="ck_tax_events_automatic_trade_source",
        ),
        Index(
            "uq_tax_events_automatic_trade",
            "related_trade_id",
            unique=True,
            sqlite_where=text("origin = 'automatic_trade'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Origin and linkage are distinct: a manual row can reference a source without becoming a
    # derived record that synchronization may rewrite or delete.
    #
    origin: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual", server_default="manual"
    )
    related_trade_id: Mapped[int | None] = mapped_column(ForeignKey("trades.id"), nullable=True)
    related_income_id: Mapped[int | None] = mapped_column(
        ForeignKey("income_events.id"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    gross_amount: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    tax_rate: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    # Gross tax on this event before offsetting gains and losses: a detail, not tax due, and
    # never summed across events. ReportService.fiscal_position calculates the offset total.
    #
    #
    tax_amount: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    net_amount: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    is_compensated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
