"""Adapt pure currency conversion in app.finance.currency to application HTTP errors. Convert
ValueError into the standard HTTP 400 response with a readable message. All services writing
monetary values share this validation path.
"""

from __future__ import annotations

from decimal import Decimal

from app.finance.currency import EUR
from app.finance.currency import convert as _convert
from app.finance.currency import normalize_currency, to_eur
from app.utils.errors import ValidationErrorPFIM

__all__ = ["EUR", "normalize_currency", "convert_to_eur", "to_eur"]


def convert_to_eur(
    amount: Decimal, currency: str | None, declared_rate: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Return (fx_rate, amount_in_eur), or raise HTTP 400 when the rate is absent or invalid.
    Calling with amount=0 validates an import rate before writing any rows.
    """
    try:
        return _convert(amount, currency, declared_rate)
    except ValueError as exc:
        raise ValidationErrorPFIM(
            str(exc),
            detail={
                "currency": normalize_currency(currency) or None,
                "fx_rate": str(declared_rate) if declared_rate is not None else None,
            },
        ) from exc
