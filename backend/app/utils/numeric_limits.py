"""Portable normalization for Numeric price and exchange-rate columns. SQLite does not enforce
NUMERIC precision and scale when binding. Explicitly normalize values before derived
calculations or persistence so domain calculations use the same values read back from the
database.
"""

from decimal import ROUND_HALF_EVEN, Decimal

# Numeric(18, 6) allows twelve integer digits, but SQLite's driver passes nonintegers
# through binary64. Beyond nine integer digits, ULP can exceed one micro-unit and lose the
# last declared digit on round-trip. The application limit guarantees that six-decimal
# values are read back unchanged on the reference SQLite runtime. Keep the broader DDL
# constraint for historical compatibility.
#
# Generic names also cover derived trade values. PRICE_* aliases keep price and quote
# contracts readable.
NUMERIC_18_6_QUANTUM = Decimal("0.000001")
NUMERIC_18_6_MIN_POSITIVE = NUMERIC_18_6_QUANTUM
NUMERIC_18_6_MAX = Decimal("999999999")
PRICE_MIN = NUMERIC_18_6_MIN_POSITIVE
PRICE_MAX = NUMERIC_18_6_MAX

# With eight decimals, the safe binary64 margin drops to seven integer digits.
NUMERIC_18_8_QUANTUM = Decimal("0.00000001")
FX_RATE_MIN = NUMERIC_18_8_QUANTUM
FX_RATE_MAX = Decimal("9999999")

# Application percentages and tax rates use NUMERIC(8, 4). Eight significant digits fit
# within binary64's safe margin, but canonicalize scale before using them in derived
# calculations.
NUMERIC_8_4_QUANTUM = Decimal("0.0001")
NUMERIC_8_4_MAX = Decimal("9999")


def _finite_decimal(value: Decimal, *, label: str) -> Decimal:
    decimal_value = Decimal(value)
    if not decimal_value.is_finite():
        raise ValueError(f"{label} must be a finite number")
    return decimal_value


def quantize_numeric_18_6(value: Decimal, *, label: str = "The value") -> Decimal:
    """Quantize a derived value to NUMERIC(18, 6). Derived subprecision values may become zero,
    for example a half-micro-euro FIFO difference too small to persist as a tax event.
    """
    decimal_value = _finite_decimal(value, label=label)
    if abs(decimal_value) > NUMERIC_18_6_MAX:
        raise ValueError(f"{label} must have an absolute value no greater than {NUMERIC_18_6_MAX}")
    normalized = decimal_value.quantize(NUMERIC_18_6_QUANTUM, rounding=ROUND_HALF_EVEN)
    # Avoid propagating signed zero into comparisons and serialization.
    return Decimal("0.000000") if normalized == 0 else normalized


def normalize_numeric_18_6(value: Decimal, *, label: str = "The value") -> Decimal:
    """Normalize a value for NUMERIC(18, 6). SQLite applies affinity without enforcing precision
    and scale. Reject nonzero underflow and overflow; retain zero where permitted, with sign
    rules enforced by callers. Round additional decimals using ROUND_HALF_EVEN so input,
    calculations, and reread values agree.
    """
    decimal_value = _finite_decimal(value, label=label)
    normalized = quantize_numeric_18_6(decimal_value, label=label)
    if decimal_value != 0 and normalized == 0:
        raise ValueError(
            f"{label} must be zero or have an absolute value between "
            f"{NUMERIC_18_6_MIN_POSITIVE} and {NUMERIC_18_6_MAX}"
        )
    return normalized


def normalize_fx_rate(value: Decimal, *, label: str = "The exchange rate") -> Decimal:
    """Normalize a positive exchange rate to NUMERIC(18, 8)."""
    decimal_value = _finite_decimal(value, label=label)
    if decimal_value <= 0:
        raise ValueError(f"{label} must be greater than zero")
    if decimal_value > FX_RATE_MAX:
        raise ValueError(f"{label} must be between {FX_RATE_MIN} and {FX_RATE_MAX}")
    normalized = decimal_value.quantize(NUMERIC_18_8_QUANTUM, rounding=ROUND_HALF_EVEN)
    if not FX_RATE_MIN <= normalized <= FX_RATE_MAX:
        raise ValueError(f"{label} must be between {FX_RATE_MIN} and {FX_RATE_MAX}")
    return normalized


def normalize_numeric_8_4(value: Decimal, *, label: str = "The value") -> Decimal:
    """Normalize a value for NUMERIC(8, 4)."""
    decimal_value = _finite_decimal(value, label=label)
    if abs(decimal_value) > NUMERIC_8_4_MAX:
        raise ValueError(f"{label} must have an absolute value no greater than {NUMERIC_8_4_MAX}")
    normalized = decimal_value.quantize(NUMERIC_8_4_QUANTUM, rounding=ROUND_HALF_EVEN)
    if decimal_value != 0 and normalized == 0:
        raise ValueError(
            f"{label} must be zero or have an absolute value between "
            f"{NUMERIC_8_4_QUANTUM} and {NUMERIC_8_4_MAX}"
        )
    return Decimal("0.0000") if normalized == 0 else normalized


# Compatibility alias for earlier external callers. The function now also returns the
# canonical representation to use and persist.
validate_numeric_18_6 = normalize_numeric_18_6
