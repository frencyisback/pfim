"""Hash-based import deduplication. Row identity includes date, amount, description, and
destination account, so matching movements on different accounts remain distinct despite the
table-wide unique import_hash.
"""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_EVEN, Decimal

from app.utils.numeric_limits import NUMERIC_18_6_QUANTUM


# Monetary columns are Numeric(18, 6): CSV may supply -1.5 while the database returns
# -1.500000. Canonicalizing both before hashing recognizes previously imported rows and
# lets migrations recalculate hashes that match import values.
#
#
def canonical_amount(amount: Decimal | str | int | float) -> str:
    """Canonical text representation of an amount at database precision."""
    return f"{Decimal(str(amount)).quantize(NUMERIC_18_6_QUANTUM, rounding=ROUND_HALF_EVEN):f}"


def compute_row_hash(account_id: int, date: str, amount, description: str | None) -> str:
    """Deterministic imported-row hash for deduplication. Pass date in ISO YYYY-MM-DD form;
    canonical_amount normalizes any numeric amount representation.
    """
    raw = f"{account_id}|{date}|{canonical_amount(amount)}|{description or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
