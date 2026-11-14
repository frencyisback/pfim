"""Estimate EUR tax at the configured percentage, using PFIM's fiscal rounding."""

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def capital_gains_tax(gain: Decimal, rate: Decimal) -> Decimal:
    return (max(gain, Decimal("0")) * rate / 100).quantize(_CENT, rounding=ROUND_HALF_UP)


def remaining_capital_gains_tax(gain: Decimal, rate: Decimal, withheld: Decimal) -> Decimal:
    paid = withheld.quantize(_CENT, rounding=ROUND_HALF_UP)
    return max(capital_gains_tax(gain, rate) - paid, Decimal("0.00"))
