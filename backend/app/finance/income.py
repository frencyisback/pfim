"""Yield on cost and current yield. Both functions compare total period income with the value of
the entire position, never a per-unit value. Mixing units would multiply the reported
percentage by the number of units held.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal


def open_distribution_fractions(trades: list, events: list) -> dict[int, Decimal]:
    """Fraction of each distribution earned by units still held in its account.

    Supply trades through the valuation date. At the ex-date use the position
    before trading; in its absence use end-of-payment-day holdings. Within
    each account, FIFO consumes the earliest purchased units first. Of the
    units bought by entitlement, only those beyond *all* sales can survive.
    If recorded payment quantity exceeds known holdings, the unknown units
    receive their share too. The input cash amount is never modified.
    """
    trades_by_position = defaultdict(list)
    events_by_position = defaultdict(list)
    for trade in trades:
        trades_by_position[trade.security_id, trade.account_id].append(trade)
    for event in events:
        events_by_position[event.security_id, event.account_id].append(event)

    fractions = {}
    for key, payments in events_by_position.items():
        history = sorted(trades_by_position[key], key=lambda trade: (trade.date, trade.id))
        total_sold = sum((trade.quantity for trade in history if trade.type == "sell"), Decimal(0))
        bought = sold = Decimal(0)
        index = 0
        for event in sorted(
            payments, key=lambda e: (e.ex_date or e.payment_date, e.ex_date is None)
        ):
            day = event.ex_date or event.payment_date
            while index < len(history):
                trade = history[index]
                if trade.date > day or (trade.date == day and event.ex_date is not None):
                    break
                if trade.type == "buy":
                    bought += trade.quantity
                else:
                    sold += trade.quantity
                index += 1
            entitled = max(bought - sold, event.quantity_held or Decimal(0))
            surviving = max(bought - total_sold, Decimal(0))
            fractions[event.id] = surviving / entitled if entitled > 0 else Decimal(0)
    return fractions


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
