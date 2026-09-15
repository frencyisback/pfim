"""Calendar conventions shared by financial calculations. Centralize the 365-day year and its
inclusive trailing-window boundary so every last-12-month calculation includes the same income
events. This pure module only uses numbers and dates.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

# Conventional financial year, also used for annualization (§9.5.1), XIRR (§9.4), and
# every trailing-12-month indicator.
#
DAYS_PER_YEAR = 365

# Average month length (365.25 / 12), used to convert days to months. Dividing a full year
# by 30 would give 12.17 months and understate the monthly average by 1.4%.
#
DAYS_PER_MONTH = Decimal("30.44")

# Months in the trailing-12-month window for monthly averages. The consistent divisor is
# DAYS_PER_YEAR / DAYS_PER_MONTH, rather than exactly 12.
#
MONTHS_PER_TRAILING_YEAR = Decimal(DAYS_PER_YEAR) / DAYS_PER_MONTH


def trailing_year_start(as_of: dt.date) -> dt.date:
    """Return the first included day of the trailing year ending at as_of. The window contains
    exactly DAYS_PER_YEAR days, including as_of and excluding the day exactly one year
    earlier. All callers compare day >= trailing_year_start(as_of).
    """
    return as_of - dt.timedelta(days=DAYS_PER_YEAR - 1)
