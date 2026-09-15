"""Yield on cost and current yield. Both functions compare total period income with the value of
the entire position, never a per-unit value. Mixing units would multiply the reported
percentage by the number of units held.
"""

from __future__ import annotations

from decimal import Decimal


def yield_on_cost(annual_income_eur: Decimal, invested_eur: Decimal) -> Decimal:
    """Yield on cost = annualized income / total acquisition cost * 100. Return a percentage (4.5
    means 4.5%). invested_eur is Position.total_invested for the entire open position and must
    use the same aggregate units as annual_income_eur.
    """
    if invested_eur == 0:
        raise ValueError("invested_eur cannot be zero")
    return (annual_income_eur / invested_eur) * 100


def current_yield(annual_income_eur: Decimal, current_value_eur: Decimal) -> Decimal:
    """Current yield = annualized income / total market value * 100. Return a percentage.
    current_value_eur is quantity times price for the entire position, not its unit price.
    """
    if current_value_eur == 0:
        raise ValueError("current_value_eur cannot be zero")
    return (annual_income_eur / current_value_eur) * 100
