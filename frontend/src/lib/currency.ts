/** Frontend currency and conversion rules. The backend converts values
 * at entry time (docs/multi-currency.md): each amount declares a currency
 * and foreign amounts require a rate. Helpers support forms and tables
 * displaying native and converted values side by side. */
export const EUR = "EUR";

/** Suggested currencies in display order. */
export const CURRENCY_OPTIONS: { value: string; label: string }[] = [
  { value: "EUR", label: "EUR — Euro" },
  { value: "USD", label: "USD — US dollar" },
  { value: "GBP", label: "GBP — Pound sterling" },
  { value: "CHF", label: "CHF — Swiss franc" },
  { value: "JPY", label: "JPY — Yen" },
  { value: "SEK", label: "SEK — Swedish krona" },
  { value: "CAD", label: "CAD — Canadian dollar" },
];

/** A rate is declared only for non-base currencies. */
export function needsFxRate(currency: string | null | undefined): boolean {
  return !!currency && currency.trim().toUpperCase() !== EUR;
}

/** Trades settled in a currency different from the quote currency
 * declare both prices: one determines cash, the other updates prices. */
export function needsSeparateQuotePrice(
  settlementCurrency: string | null | undefined,
  quoteCurrency: string | null | undefined
): boolean {
  if (!settlementCurrency || !quoteCurrency) return false;
  return settlementCurrency.trim().toUpperCase() !== quoteCurrency.trim().toUpperCase();
}

/** Euro value for form previews. Returns null when inputs are incomplete
 * so users do not see a misleading zero while still typing. */
export function previewEur(amount: string, currency: string, fxRate: string): number | null {
  const value = Number(amount);
  if (!amount || Number.isNaN(value)) return null;
  if (!needsFxRate(currency)) return value;
  const rate = Number(fxRate);
  if (!fxRate || Number.isNaN(rate) || rate <= 0) return null;
  return value * rate;
}
