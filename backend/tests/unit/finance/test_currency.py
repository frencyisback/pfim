"""Unit tests for the pure currency conversion module (app/finance/currency.py).

Check the RULE, not arithmetic: when a rate is required, implicit,
or invalid to declare.
"""

from decimal import Decimal

import pytest

from app.finance.currency import (
    EUR,
    convert,
    normalize_currency,
    resolve_fx_rate,
    to_eur,
)


class TestNormalizeCurrency:
    def test_uppercases_and_strips(self):
        assert normalize_currency("  usd ") == "USD"

    def test_none_becomes_empty(self):
        assert normalize_currency(None) == ""


class TestResolveFxRate:
    def test_eur_is_always_one_without_declaring_it(self):
        """The base currency needs no exchange rate and must not prompt the user."""
        assert resolve_fx_rate(EUR, None) == Decimal("1")

    def test_eur_accepts_an_explicit_one(self):
        """A client explicitly sending 1 must not be rejected."""
        assert resolve_fx_rate("EUR", Decimal("1")) == Decimal("1")

    def test_eur_with_a_different_rate_is_an_error(self):
        """EUR to EUR has no exchange conversion: a rate other than 1 is a typo that would silently falsify every total."""
        with pytest.raises(ValueError, match="does not need an exchange rate"):
            resolve_fx_rate("EUR", Decimal("0.92"))

    def test_foreign_currency_requires_a_rate(self):
        with pytest.raises(ValueError, match="required"):
            resolve_fx_rate("USD", None)

    def test_error_message_names_the_currency(self):
        """The end-user message must name the currency and required input, rather than merely reporting missing information."""
        with pytest.raises(ValueError) as exc:
            resolve_fx_rate("GBP", None)
        assert "GBP" in str(exc.value)
        assert "EUR value of 1 GBP" in str(exc.value)

    def test_foreign_currency_returns_the_declared_rate(self):
        assert resolve_fx_rate("USD", Decimal("0.92")) == Decimal("0.92")

    def test_foreign_currency_is_normalized_before_it_is_used(self):
        assert resolve_fx_rate("USD", Decimal("0.123456789")) == Decimal("0.12345679")

    @pytest.mark.parametrize("rate", [Decimal("0"), Decimal("-0.5")])
    def test_non_positive_rate_is_rejected(self, rate):
        with pytest.raises(ValueError, match="greater than zero"):
            resolve_fx_rate("USD", rate)

    def test_currency_is_normalized_before_the_check(self):
        assert resolve_fx_rate(" eur ", None) == Decimal("1")

    def test_missing_currency_is_rejected(self):
        with pytest.raises(ValueError, match="Currency is required"):
            resolve_fx_rate("", Decimal("1"))


class TestToEur:
    def test_multiplies(self):
        assert to_eur(Decimal("100"), Decimal("0.92")) == Decimal("92.00")

    def test_does_not_round(self):
        """Rounding here would accumulate errors across summed rows: preserve precision up to the Numeric(18, 6) column."""
        assert to_eur(Decimal("1"), Decimal("0.123456789")) == Decimal("0.123456789")

    def test_keeps_the_sign_of_the_amount(self):
        """An expense remains an expense after conversion."""
        assert to_eur(Decimal("-100"), Decimal("0.92")) == Decimal("-92.00")


class TestConvert:
    def test_returns_both_rate_and_converted_amount(self):
        rate, amount_eur = convert(Decimal("100"), "USD", Decimal("0.92"))
        assert rate == Decimal("0.92")
        assert amount_eur == Decimal("92.00")

    def test_eur_passes_through_unchanged(self):
        rate, amount_eur = convert(Decimal("100"), "EUR", None)
        assert rate == Decimal("1")
        assert amount_eur == Decimal("100")

    def test_propagates_the_validation_error(self):
        with pytest.raises(ValueError):
            convert(Decimal("100"), "USD", None)

    @pytest.mark.parametrize(
        ("amount", "currency", "rate", "message"),
        [
            (Decimal("NaN"), "EUR", None, "finite number"),
            (Decimal("sNaN"), "EUR", None, "finite number"),
            (Decimal("Infinity"), "EUR", None, "finite number"),
            (Decimal("0.0000001"), "EUR", None, "declared currency"),
            (Decimal("1000000000"), "EUR", None, "declared currency"),
            (Decimal("0.000001"), "USD", Decimal("0.00000001"), "EUR equivalent"),
            (
                Decimal("999999999"),
                "USD",
                Decimal("9999999"),
                "EUR equivalent",
            ),
        ],
    )
    def test_rejects_values_that_numeric_18_6_cannot_store(self, amount, currency, rate, message):
        with pytest.raises(ValueError, match=message):
            convert(amount, currency, rate)

    def test_zero_remains_valid_when_conversion_is_only_validating_a_rate(self):
        rate, amount_eur = convert(Decimal("0"), "USD", Decimal("0.92"))
        assert rate == Decimal("0.92")
        assert amount_eur == 0

    def test_uses_the_stored_amount_and_rate_to_compute_the_eur_value(self):
        rate, amount_eur = convert(
            Decimal("100.0000005"),
            "USD",
            Decimal("0.123456789"),
        )

        # ROUND_HALF_EVEN rounds the amount tie to 100.000000; the rate
        # is first rounded to the eight decimals actually persisted.
        assert rate == Decimal("0.12345679")
        assert amount_eur == Decimal("12.345679")
