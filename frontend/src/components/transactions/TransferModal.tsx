import { useState } from "react";
import { useAccounts } from "@/api/accounts";
import { useCreateTransfer } from "@/api/transactions";
import CurrencyFields from "@/components/common/CurrencyFields";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { EUR, needsFxRate } from "@/lib/currency";
import { todayIso } from "@/lib/dates";
import { containsSelectedId, getWritableCashAccounts } from "@/lib/lifecycle";

interface Props {
  onClose: () => void;
}

/** Transfer modal: creates two linked transactions, negative at the
 * source and positive at the destination. See specification §5.1. */
export default function TransferModal({ onClose }: Props) {
  const {
    data: allAccounts,
    isLoading: accountsLoading,
    error: accountsError,
  } = useAccounts(true);
  // Investment accounts hold no cash of their own (specification §5.2)
  // and cannot be endpoints of a cash transfer.
  const createTransfer = useCreateTransfer();

  const [form, setForm] = useState({
    from_account_id: "",
    to_account_id: "",
    date: todayIso(),
    amount: "",
    currency: EUR,
    fx_rate: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);
  const accounts = getWritableCashAccounts(allAccounts, form.date);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.from_account_id || !form.to_account_id || !form.amount) {
      setError("Source account, destination account and amount are required.");
      return;
    }
    if (form.from_account_id === form.to_account_id) {
      setError("Source and destination accounts must differ.");
      return;
    }
    if (
      !containsSelectedId(accounts, form.from_account_id) ||
      !containsSelectedId(accounts, form.to_account_id)
    ) {
      setError("Source and destination must be active cash accounts.");
      return;
    }
    if (needsFxRate(form.currency) && !form.fx_rate) {
      setError(`Enter the exchange rate: euro value of 1 ${form.currency} on the transfer date.`);
      return;
    }
    try {
      await createTransfer.mutateAsync({
        from_account_id: Number(form.from_account_id),
        to_account_id: Number(form.to_account_id),
        date: form.date,
        amount: form.amount,
        currency: form.currency,
        fx_rate: needsFxRate(form.currency) ? form.fx_rate : null,
        description: form.description || null,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Transfer between accounts</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            ✕
          </button>
        </div>

        <QueryStateNotice isLoading={accountsLoading} error={accountsError} />

        <form onSubmit={handleSubmit} className="space-y-3">
          <label className="flex flex-col gap-1 text-sm">
            Source account
            <select
              className="rounded border border-gray-300 px-2 py-1.5"
              value={form.from_account_id}
              onChange={(e) => setForm({ ...form, from_account_id: e.target.value })}
            >
              <option value="">Select...</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Destination account
            <select
              className="rounded border border-gray-300 px-2 py-1.5"
              value={form.to_account_id}
              onChange={(e) => setForm({ ...form, to_account_id: e.target.value })}
            >
              <option value="">Select...</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Date
            <input
              type="date"
              className="rounded border border-gray-300 px-2 py-1.5"
              value={form.date}
              onChange={(e) => setForm({ ...form, date: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            Amount
            <input
              type="number"
              step="0.01"
              min="0"
              placeholder="0.00"
              className="rounded border border-gray-300 px-2 py-1.5"
              value={form.amount}
              onChange={(e) => setForm({ ...form, amount: e.target.value })}
            />
          </label>
          <CurrencyFields
            currency={form.currency}
            fxRate={form.fx_rate}
            onChange={({ currency, fxRate }) =>
              setForm((f) => ({ ...f, currency, fx_rate: fxRate }))
            }
            date={form.date}
            amount={form.amount}
          />

          <label className="flex flex-col gap-1 text-sm">
            Description (optional)
            <input
              type="text"
              className="rounded border border-gray-300 px-2 py-1.5"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </label>

          {error && <p className="text-sm text-red-600">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={createTransfer.isPending}
              className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
            >
              {createTransfer.isPending ? "Saving..." : "Record transfer"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
