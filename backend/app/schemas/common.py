"""Shared pagination schemas and field descriptions. The standard error response is built
directly by the exception handler in app/main.py.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


def fx_rate_description(moment: str, *, also: str = "") -> str:
    """Shared fx_rate description for /docs across entities accepting foreign-currency amounts.
    moment identifies the applicable operation, payment, or cost date. Prices use a separate
    description because their currency belongs to the security rather than the payload.
    """
    return (
        f"EUR per unit of currency {moment}. "
        "Required when `currency` is not EUR; omit it for EUR, where it is always 1."
        f"The EUR equivalent is calculated and frozen when saved{also}: "
        ""
    )
