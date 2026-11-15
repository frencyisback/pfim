"""Attribute the existing net-worth valuation to the accounts holding the securities.

The fiscal FIFO stays global by security. Account quantities identify custody only;
without a quote, the global remaining cost is allocated across those quantities.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.finance.portfolio import calculate_position_eur
from app.schemas.report import (
    NetWorthAccountComposition,
    NetWorthAllocationIssue,
    NetWorthCashAccount,
    NetWorthInvestmentAccount,
    PortfolioValuationFallback,
)
from app.services.account_service import account_is_present_on
from app.utils.currency import to_eur

_ZERO = Decimal("0")
_CENT = Decimal("0.01")


def _rounded_components(values: list[Decimal], total: Decimal) -> list[Decimal]:
    """Round a complete allocation to cents while retaining the rounded total.

    Largest fractional remainders receive the residual cents, with the input order
    breaking ties. Empty accounts cannot receive a cent from another account.
    """
    rounded = [value.quantize(_CENT, rounding=ROUND_FLOOR) for value in values]
    target = total.quantize(_CENT, rounding=ROUND_HALF_UP)
    cents = int((target - sum(rounded, _ZERO)) / _CENT)
    order = sorted(range(len(values)), key=lambda i: (-(values[i] - rounded[i]), i))
    for index in order[:cents]:
        rounded[index] += _CENT
    return rounded


def account_composition(
    *,
    accounts: list,
    balances: dict[int, Decimal],
    trades: list,
    prices: list,
    securities: dict,
    as_of: dt.date,
    portfolio_value: Decimal,
) -> NetWorthAccountComposition:
    """Build a read-only account breakdown from preloaded records at one cutoff.

    Invalid legacy local quantities do not change the existing global valuation. An
    affected account has an unavailable value, and the unresolved amount remains in
    an explicit residual so it cannot silently disappear from net worth.
    """
    accounts_by_id = {account.id: account for account in accounts}
    present = sorted(
        (account for account in accounts if account_is_present_on(account, as_of)),
        key=lambda account: (account.name, account.id),
    )
    present_ids = {account.id for account in present}
    investments = [account for account in present if account.type == "investment"]
    investment_ids = {account.id for account in investments}
    values = {account.id: _ZERO for account in investments}
    fallback_ids: dict[int, set[int]] = defaultdict(set)
    unavailable: set[int] = set()
    issues: list[NetWorthAllocationIssue] = []

    by_security: dict[int, list] = defaultdict(list)
    quantities: dict[int, dict[int, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for trade in trades:
        if trade.date <= as_of:
            by_security[trade.security_id].append(trade)
            quantity = Decimal(trade.quantity)
            quantities[trade.security_id][trade.account_id] += (
                quantity if trade.type == "buy" else -quantity
            )
    latest_prices = {}
    for price in prices:
        if price.date <= as_of and (
            price.security_id not in latest_prices
            or latest_prices[price.security_id].date < price.date
        ):
            latest_prices[price.security_id] = price

    def issue(account_id: int, security_id: int, reason: str) -> None:
        issues.append(
            NetWorthAllocationIssue(
                account_id=account_id,
                name=accounts_by_id[account_id].name,
                security_id=security_id,
                ticker=securities[security_id].ticker,
                reason=reason,
            )
        )

    for security_id in sorted(by_security):
        holdings = {key: value for key, value in quantities[security_id].items() if value != 0}
        has_deficit = any(quantity < 0 for quantity in holdings.values())
        for account_id, quantity in sorted(holdings.items()):
            if quantity < 0:
                issue(account_id, security_id, "negative_quantity")
            if account_id not in present_ids:
                issue(account_id, security_id, "account_not_present")
            elif accounts_by_id[account_id].type != "investment":
                issue(account_id, security_id, "not_investment_account")
        if has_deficit:
            # A positive balance elsewhere cannot identify where these legacy units
            # really belong. Do not offset it against a different account's deficit.
            unavailable.update(investment_ids.intersection(holdings))
            continue

        quantity = sum(holdings.values(), _ZERO)
        if quantity <= 0:
            continue
        price = latest_prices.get(security_id)
        if price is None:
            security_value = calculate_position_eur(by_security[security_id]).total_invested
            for account_id in investment_ids.intersection(holdings):
                fallback_ids[account_id].add(security_id)
        else:
            security_value = to_eur(Decimal(price.price_close), Decimal(price.fx_rate)) * quantity

        # Allocate at full precision, carrying the final division remainder. This
        # preserves the global cost even when custody is split into thirds.
        remaining = security_value
        ordered = sorted(holdings.items())
        for index, (account_id, held_quantity) in enumerate(ordered):
            value = (
                remaining
                if index == len(ordered) - 1
                else security_value * held_quantity / quantity
            )
            remaining -= value
            if account_id in investment_ids:
                values[account_id] += value

    known_ids = [account.id for account in investments if account.id not in unavailable]
    known_values = [values[account_id] for account_id in known_ids]
    unallocated = portfolio_value - sum(known_values, _ZERO)
    rounded = _rounded_components([*known_values, unallocated], portfolio_value)
    rounded_values = dict(zip(known_ids, rounded[:-1]))

    return NetWorthAccountComposition(
        cash_accounts=[
            NetWorthCashAccount(
                account_id=account.id, name=account.name, balance=balances[account.id]
            )
            for account in present
            if account.type != "investment"
        ],
        investment_accounts=[
            NetWorthInvestmentAccount(
                account_id=account.id,
                name=account.name,
                value=rounded_values.get(account.id),
                cost_fallback_securities=[
                    PortfolioValuationFallback(
                        security_id=security_id,
                        ticker=securities[security_id].ticker,
                        name=securities[security_id].name,
                    )
                    for security_id in sorted(fallback_ids[account.id])
                ],
            )
            for account in investments
        ],
        unallocated_portfolio_value=rounded[-1],
        unallocated_account_balance=sum((balances[account.id] for account in investments), _ZERO),
        issues=issues,
    )
