"""Currency normalization using conversion at entry. Every incoming amount declares its currency
and, unless EUR, the exchange rate at the time of the operation. Its EUR value is calculated
and stored once. This keeps cash flow and portfolio totals comparable, preserves historical
acquisition costs, and avoids missing rates during reporting. fx_rate means EUR per unit of
the declared currency: 100 USD at 0.92 equals 92 EUR, matching fx_rates from_currency to
to_currency=EUR. This pure module has no database or HTTP dependencies. It raises ValueError;
app.utils.currency translates it to an application HTTP 400 error.
"""

from __future__ import annotations

from decimal import Decimal

from app.utils.numeric_limits import normalize_fx_rate, normalize_numeric_18_6

EUR = "EUR"


def normalize_currency(currency: str | None) -> str:
    """Uppercase a currency code and remove surrounding whitespace ('  usd ' -> 'USD')."""
    return (currency or "").strip().upper()


def resolve_fx_rate(currency: str | None, declared_rate: Decimal | None) -> Decimal:
    """Determine the rate for an amount in currency. EUR always uses 1; any other declared rate
    is invalid. Other currencies require a positive declared_rate. Raise ValueError with a
    user-readable message.
    """
    code = normalize_currency(currency)
    if not code:
        raise ValueError("Currency is required")

    if code == EUR:
        normalized_rate = (
            normalize_fx_rate(declared_rate) if declared_rate is not None else Decimal("1.00000000")
        )
        if normalized_rate != Decimal("1.00000000"):
            raise ValueError(
                "An amount in EUR does not need an exchange rate: leave the field empty "
                "or enter 1"
            )
        return normalized_rate

    if declared_rate is None:
        raise ValueError(
            f"An exchange rate is required for an amount in {code}: enter the EUR value "
            f"of 1 {code} on the operation date"
        )

    return normalize_fx_rate(declared_rate)


def to_eur(amount: Decimal, fx_rate: Decimal) -> Decimal:
    """Multiply without implicit rounding. Persistence goes through convert, which normalizes
    input, rate, and result once to their declared scales.
    """
    return Decimal(amount) * Decimal(fx_rate)


def convert(
    amount: Decimal, currency: str | None, declared_rate: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Validate the rate and convert in one call. Return (applied_fx_rate, amount_in_eur).
    Persist both: the rate makes the conversion auditable, and reports aggregate the EUR
    amount.
    """
    stored_amount = normalize_numeric_18_6(
        Decimal(amount), label="The amount in the declared currency"
    )
    rate = resolve_fx_rate(currency, declared_rate)
    amount_eur = normalize_numeric_18_6(to_eur(stored_amount, rate), label="The EUR equivalent")
    return rate, amount_eur
