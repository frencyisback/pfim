import { useState } from "react";
import { useAddTradeCost, useDeleteTradeCost, useTradeCosts } from "@/api/trades";
import { formatEur, formatMoney, formatMoneyWithEur } from "@/lib/formatters";
import { EUR, needsFxRate } from "@/lib/currency";
import CurrencyFields from "@/components/common/CurrencyFields";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import QueryStateNotice from "@/components/common/QueryStateNotice";

interface Props {
  tradeId: number;
  tradeLabel: string;
  tradeTotalAmount: string;
  /** Trade currency and exchange rate inherited by percentage costs. */
  tradeCurrency: string;
  tradeFxRate: string;
  tradeDate: string;
  /** History remains viewable, but archived trades are read-only. */
  allowAdd: boolean;
  onClose: () => void;
}

/** Trade cost modal (fees, taxes, spreads; specification §5.2). Adding
 * or removing a cost recalculates the linked cash transaction. Costs may
 * be fixed amounts or percentages, frozen as amounts when saved.
 * Percentage costs inherit the trade currency and rate. Fixed costs
 * declare their own currency and rate, allowing euro fees on USD trades. */
export default function TradeCostsModal({
  tradeId,
  tradeLabel,
  tradeTotalAmount,
  tradeCurrency,
  tradeFxRate,
  tradeDate,
  allowAdd,
  onClose,
}: Props) {
  const { data: costs, isLoading, error: queryError } = useTradeCosts(tradeId);
  const addCost = useAddTradeCost(tradeId);
  const deleteCost = useDeleteTradeCost(tradeId);
  const { confirm, dialog } = useConfirmDialog();

  const [mode, setMode] = useState<"amount" | "percentage">("amount");
  const [form, setForm] = useState({
    cost_type: "commission",
    amount: "",
    percentage: "",
    currency: EUR,
    fx_rate: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);

  const previewAmount =
    mode === "percentage" && form.percentage
      ? (Number(tradeTotalAmount) * Number(form.percentage)) / 100
      : null;

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!allowAdd) {
      setError("Cannot add costs: the trade's security or account is inactive.");
      return;
    }
    if (mode === "amount" && !form.amount) {
      setError("Amount is required.");
      return;
    }
    if (mode === "percentage" && !form.percentage) {
      setError("Percentage is required.");
      return;
    }
    if (mode === "amount" && needsFxRate(form.currency) && !form.fx_rate) {
      setError(`Enter the exchange rate: euro value of 1 ${form.currency} on the trade date.`);
      return;
    }
    try {
      await addCost.mutateAsync({
        cost_type: form.cost_type,
        amount: mode === "amount" ? form.amount : undefined,
        percentage: mode === "percentage" ? form.percentage : undefined,
        currency: form.currency,
        fx_rate:
          mode === "amount" && needsFxRate(form.currency) ? form.fx_rate : undefined,
        description: form.description || null,
      });
      setForm({ ...form, amount: "", percentage: "", description: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Costs — {tradeLabel}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            ✕
          </button>
        </div>

        <QueryStateNotice isLoading={isLoading} error={queryError} />
        {!isLoading && !queryError && (
          <div className="mb-4 space-y-1">
            {costs?.map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between rounded border border-gray-100 px-2 py-1.5 text-sm"
              >
                <span>
                  {c.cost_type}
                  {c.description ? ` — ${c.description}` : ""}
                  {c.percentage_used && (
                    <span className="ml-1 text-xs text-gray-400">
                      ({Number(c.percentage_used).toString()}%)
                    </span>
                  )}
                </span>
                <div className="flex items-center gap-2">
                  <span className="font-medium">
                    {formatMoneyWithEur(Number(c.amount), c.currency, Number(c.amount_eur))}
                  </span>
                  {allowAdd && (
                    <button
                      onClick={() =>
                        confirm(
                          `Delete cost '${c.cost_type}' (${formatEur(Number(c.amount_eur))})?`,
                          () => deleteCost.mutate(c.id)
                        )
                      }
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>
            ))}
            {costs?.length === 0 && (
              <p className="text-sm text-gray-400">No costs recorded for this trade.</p>
            )}
          </div>
        )}

        {!allowAdd && (
          <p className="mb-3 rounded bg-gray-50 px-3 py-2 text-xs text-gray-600">
            Security or account unavailable on the trade date: existing costs remain viewable, but history is read-only.
          </p>
        )}

        {allowAdd && (
        <form onSubmit={handleAdd} className="space-y-2 border-t border-gray-100 pt-3">
          <div className="flex items-center gap-3 text-xs text-gray-500">
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "amount"}
                onChange={() => setMode("amount")}
              />
              Fixed amount
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "percentage"}
                onChange={() => setMode("percentage")}
              />
              Percentage of trade
            </label>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <select
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
              value={form.cost_type}
              onChange={(e) => setForm({ ...form, cost_type: e.target.value })}
            >
              <option value="commission">Fee</option>
              <option value="tax">Tax</option>
              <option value="spread">Spread</option>
              <option value="other">Other</option>
            </select>
            {mode === "amount" ? (
              <input
                type="number"
                step="0.01"
                placeholder="Amount"
                className="w-28 rounded border border-gray-300 px-2 py-1.5 text-sm"
                value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
              />
            ) : (
              <input
                type="number"
                step="0.01"
                placeholder="Percentage %"
                className="w-28 rounded border border-gray-300 px-2 py-1.5 text-sm"
                value={form.percentage}
                onChange={(e) => setForm({ ...form, percentage: e.target.value })}
              />
            )}
            <input
              type="text"
              placeholder="Description (optional)"
              className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
            <button
              type="submit"
              disabled={addCost.isPending}
              className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
          {mode === "amount" && (
            <CurrencyFields
              currency={form.currency}
              fxRate={form.fx_rate}
              onChange={({ currency, fxRate }) =>
                setForm((f) => ({ ...f, currency, fx_rate: fxRate }))
              }
              date={tradeDate}
              amount={form.amount}
            />
          )}
          {previewAmount !== null && (
            <p className="text-xs text-gray-500">
              Calculated amount:{" "}
              <strong>{formatMoney(previewAmount, tradeCurrency)}</strong>
              {needsFxRate(tradeCurrency) && (
                <> = {formatEur(previewAmount * Number(tradeFxRate))}</>
              )}{" "}
              (frozen on save, at the trade exchange rate)
            </p>
          )}
        </form>
        )}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>
      {dialog}
    </div>
  );
}
