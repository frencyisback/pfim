"""ORM model: Category."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # 'income' | 'expense' | 'transfer'
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # Hex color for the UI.
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
