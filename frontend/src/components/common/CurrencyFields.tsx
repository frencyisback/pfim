import { useSuggestedFxRate } from "@/api/fxRates";
import { CURRENCY_OPTIONS, EUR, needsFxRate, previewEur } from "@/lib/currency";
import { formatEur } from "@/lib/formatters";

/** Shared currency and exchange-rate fields for monetary forms.
 * Euro amounts need no rate. Foreign amounts require a rate and may use
 * the latest archived suggestion for the date, which remains editable.
 * The preview shows the frozen EUR amount before saving. Forms with
 * their own preview, such as net income, can replace the generic one. */
export interface CurrencySelection {
  currency: string;
  fxRate: string;
}

export interface CurrencyFieldsProps {
  currency: string;
  fxRate: string;
  /** One callback returns both values. A currency change also clears
   * the exchange rate; two updates derived from the same state would
   * overwrite one another. A single callback keeps the update atomic. */
  onChange: (selection: CurrencySelection) => void;
  /** Transaction date: determines the suggested exchange rate. */
  date: string;
  /** Native amount used to preview the EUR value. */
  amount?: string;
  /** Forms with their own preview, such as net income, can replace the generic one. */
  showConversionPreview?: boolean;
  /** Externally fixed currency, for example prices that must use
   * the security's quoted currency. */
  lockedCurrencyLabel?: string;
  className?: string;
}

export default function CurrencyFields({
  currency,
  fxRate,
  onChange,
  date,
  amount,
  showConversionPreview = true,
  lockedCurrencyLabel,
  className = "",
}: CurrencyFieldsProps) {
  const foreign = needsFxRate(currency);
  const { data: suggestion } = useSuggestedFxRate(foreign ? currency : null, date || null);
  const converted = previewEur(amount ?? "", currency, fxRate);
  const suggested = suggestion?.rate ?? null;

  return (
    <div className={`flex flex-wrap items-end gap-2 ${className}`}>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        Currency
        {lockedCurrencyLabel ? (
          <span className="rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-sm text-gray-700">
            {lockedCurrencyLabel}
          </span>
        ) : (
          <select
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={currency}
            // Clear the rate when the currency changes: the previous rate
            // applies to a different currency and retaining it would produce
            // a plausible but incorrect conversion.
            onChange={(e) => onChange({ currency: e.target.value, fxRate: "" })}
          >
            {CURRENCY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.value}
              </option>
            ))}
          </select>
        )}
      </label>

      {foreign && (
        <>
          <label className="flex flex-col gap-1 text-xs text-gray-500">
            Exchange rate (1 {currency} = ? €)
            <input
              type="number"
              step="0.00000001"
              min="0"
              required
              placeholder="0,00000000"
              className="w-36 rounded border border-gray-300 px-2 py-1.5 text-sm"
              value={fxRate}
              onChange={(e) => onChange({ currency, fxRate: e.target.value })}
            />
          </label>
          {suggested && suggested !== fxRate && (
            <button
              type="button"
              onClick={() => onChange({ currency, fxRate: suggested })}
              className="rounded border border-gray-300 px-2 py-1.5 text-xs text-gray-600 hover:bg-gray-50"
              title={
                suggestion?.rate_date
                  ? `Latest archived rate, dated ${suggestion.rate_date}`
                  : undefined
              }
            >
              Use {suggested}
              {suggestion?.rate_date ? ` (${suggestion.rate_date})` : ""}
            </button>
          )}
        </>
      )}

      {foreign && showConversionPreview && (
        <p className="w-full text-xs text-gray-500">
          {converted === null ? (
            <>Enter the exchange rate on the transaction date: the EUR value is
            saved now and will not change.</>
          ) : (
            <>
              Will be saved as <strong>{formatEur(converted)}</strong>. The original amount
              is also retained in {currency}.
            </>
          )}
        </p>
      )}
    </div>
  );
}

/** Default form currency for the majority of transactions. */
export const DEFAULT_CURRENCY = EUR;
