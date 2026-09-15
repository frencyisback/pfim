import { needsFxRate } from "./currency";

export interface IncomePreviewInput {
  gross: string;
  withheld: string;
  currency: string;
  fxRate: string;
}

/** Informational preview; accounting amounts are calculated by the backend. */
export function previewIncomeNet({ gross, withheld, currency, fxRate }: IncomePreviewInput): {
  native: number;
  eur: number | null;
} | null {
  if (!gross.trim() || !withheld.trim() || !currency.trim()) return null;
  const grossAmount = Number(gross);
  const withholding = Number(withheld);
  if (
    !Number.isFinite(grossAmount) || !Number.isFinite(withholding) ||
    grossAmount < 0 || withholding < 0 || withholding > grossAmount
  ) return null;

  const native = grossAmount - withholding;
  if (!needsFxRate(currency)) return { native, eur: native };

  const rate = Number(fxRate);
  const converted = native * rate;
  const eur = fxRate.trim() && Number.isFinite(rate) && rate > 0 && Number.isFinite(converted)
    ? converted
    : null;
  return { native, eur };
}
