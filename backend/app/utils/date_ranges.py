"""Shared validation for inclusive API date ranges."""

from __future__ import annotations

import datetime as dt

from app.utils.errors import ValidationErrorPFIM


def validate_date_range(date_from: dt.date | None, date_to: dt.date | None) -> None:
    """Reject reversed ranges rather than returning a misleading empty result."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValidationErrorPFIM(
            "The start date cannot be after the end date",
            detail={
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
            },
        )
