"""Pydantic schemas: Category."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CategoryBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    type: str = Field(..., pattern="^(income|expense|transfer)$")
    parent_id: int | None = None
    color: str | None = Field(default=None, max_length=7)
    icon: str | None = Field(default=None, max_length=50)


class CategoryCreate(CategoryBase):
    pass


class CategoryRead(CategoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_system: bool
