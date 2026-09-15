import { useState } from "react";
import { useAccounts } from "@/api/accounts";
import { useSecurities } from "@/api/securities";
import {
  useCreateIncomeEvent,
  useDeleteIncomeEvent,
  useIncomeEvents,
  useIncomeEventsSummary,
} from "@/api/incomeEvents";
import type { IncomeEvent } from "@/api/types";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { formatEur, formatMoneyWithEur } from "@/lib/formatters";
import { EUR, needsFxRate } from "@/lib/currency";
import CurrencyFields from "@/components/common/CurrencyFields";
import IncomeAmountFields from "@/components/income/IncomeAmountFields";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import { todayIso } from "@/lib/dates";
import {
  containsSelectedId,
  getWritableInvestmentAccounts,
  getWritableSecurities,
} from "@/lib/lifecycle";
import { useTableSort } from "@/lib/useTableSort";

const EVENT_TYPE_LABELS: Record<string, string> = {
  dividend: "Dividend",
  coupon: "Coupon",
  return_of_capital: "Return of capital",
};

/** Income page: record periodic coupons, dividends and returns of
 * capital for portfolio securities. Specification §5.2 and §6.5. */
export default function IncomeEvents() {
  const { data: securities, error: securitiesError } = useSecurities();
  const { data: accounts, error: accountsError } = useAccounts();
  const { data: events, isLoading, error } = useIncomeEvents();
  const { data: summary, error: summaryError } = useIncomeEventsSummary();
  const createEvent = useCreateIncomeEvent();
  const deleteEvent = useDeleteIncomeEvent();
  const { confirm, dialog } = useConfirmDialog();

  const [form, setForm] = useState({
    security_id: "",
    account_id: "",
    event_type: "dividend",
    ex_date: "",
    payment_date: todayIso(),
    total_amount: "",
    currency: EUR,
    fx_rate: "",
    tax_withheld: "0",
    notes: "",
  });
  const [formError, setFormError] = useState<string | null>(null);
  const activeSecurities = getWritableSecurities(securities);

  /** Suggest the security currency, usually used for coupon payments. */
  function handleSecurityChange(security_id: string) {
    const security = activeSecurities?.find((s) => String(s.id) === security_id);
    setForm({
      ...form,
      security_id,
      currency: security?.currency ?? form.currency,
      fx_rate: "",
    });
  }

  const securityLabel = (id: number) => {
    const s = securities?.find((sec) => sec.id === id);
    return s ? s.ticker : `#${id}`;
  };
  const accountName = (id: number) => accounts?.find((a) => a.id === id)?.name ?? `#${id}`;
  // Coupons and dividends require investment accounts (specification §5.2);
  // cash is always credited to their reference account.
  const investmentAccounts = getWritableInvestmentAccounts(accounts, form.payment_date);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!form.security_id || !form.account_id || !form.total_amount) {
      setFormError("Security, account and total gross amount are required.");
      return;
    }
    if (
      !containsSelectedId(activeSecurities, form.security_id) ||
      !containsSelectedId(investmentAccounts, form.account_id)
    ) {
      setFormError("Security and investment account must be active.");
      return;
    }
    if (needsFxRate(form.currency) && (
      !form.fx_rate.trim() || !Number.isFinite(Number(form.fx_rate)) || Number(form.fx_rate) <= 0
    )) {
      setFormError(`Enter a positive exchange rate: euro value of 1 ${form.currency} on the payment date.`);
      return;
    }
    try {
      await createEvent.mutateAsync({
        security_id: Number(form.security_id),
        account_id: Number(form.account_id),
        event_type: form.event_type,
        ex_date: form.ex_date || null,
        payment_date: form.payment_date,
        total_amount: form.total_amount,
        currency: form.currency,
        fx_rate: needsFxRate(form.currency) ? form.fx_rate : null,
        tax_withheld: form.tax_withheld || "0",
        notes: form.notes || null,
      });
      setForm({ ...form, total_amount: "", tax_withheld: "0", notes: "" });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  type EventSortKey = "date" | "security" | "type" | "gross" | "tax" | "net" | "account";
  const eventSort = useTableSort<IncomeEvent, EventSortKey>(
    events ?? [],
    { key: "date", direction: "desc" },
    (event, key) => {
      if (key === "date") return event.payment_date;
      if (key === "security") return securityLabel(event.security_id);
      if (key === "type") return EVENT_TYPE_LABELS[event.event_type] ?? event.event_type;
      if (key === "gross") return Number(event.total_eur);
      if (key === "tax") return Number(event.total_eur) - Number(event.net_amount_eur);
      if (key === "net") return Number(event.net_amount_eur);
      return accountName(event.account_id);
    }
  );

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Coupons and Dividends</h2>

      {summary && (
        <div className="rounded-lg border border-gray-200 bg-white p-3">
          <div className="text-xs text-gray-500">Total net received</div>
          <div className="mt-1 text-lg font-semibold text-green-600">
            {formatEur(Number(summary.total_net_eur))}
          </div>
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-4"
      >
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Security
          <select
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.security_id}
            onChange={(e) => handleSecurityChange(e.target.value)}
          >
            <option value="">Security...</option>
            {activeSecurities.map((s) => (
              <option key={s.id} value={s.id}>
                {s.ticker}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Investment account
          <select
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.account_id}
            onChange={(e) => setForm({ ...form, account_id: e.target.value })}
          >
            <option value="">Investment account...</option>
            {investmentAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Type
          <select
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.event_type}
            onChange={(e) => setForm({ ...form, event_type: e.target.value })}
          >
            <option value="dividend">Dividend</option>
            <option value="coupon">Coupon</option>
            <option value="return_of_capital">Return of capital</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Ex-date (optional)
          <input
            type="date"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.ex_date}
            onChange={(e) => setForm({ ...form, ex_date: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Payment date
          <input
            type="date"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.payment_date}
            onChange={(e) => setForm({ ...form, payment_date: e.target.value })}
          />
        </label>
        <IncomeAmountFields
          currency={form.currency}
          fxRate={form.fx_rate}
          gross={form.total_amount}
          withheld={form.tax_withheld}
          onGrossChange={(total_amount) => setForm((current) => ({ ...current, total_amount }))}
          onWithheldChange={(tax_withheld) => setForm((current) => ({ ...current, tax_withheld }))}
        />
        <label className="flex flex-col gap-1 text-xs text-gray-500 md:col-span-2">
          Notes (optional)
          <input
            type="text"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
        </label>
        <p className="col-span-full -mt-1 text-xs text-gray-400">
          Gross amount = amount credited to the account + tax withheld.
        </p>
        <button
          type="submit"
          disabled={createEvent.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createEvent.isPending ? "Saving..." : "Record"}
        </button>
        <CurrencyFields
          className="col-span-full border-t border-gray-100 pt-3"
          currency={form.currency}
          fxRate={form.fx_rate}
          onChange={({ currency, fxRate }) =>
            setForm((f) => ({ ...f, currency, fx_rate: fxRate }))
          }
          date={form.payment_date}
          showConversionPreview={false}
        />
        {formError && <p className="col-span-full text-sm text-red-600">{formError}</p>}
      </form>

      <QueryStateNotice
        isLoading={isLoading}
        error={error ?? summaryError ?? securitiesError ?? accountsError}
      />

      {events && (
        <CollapsibleTable title="Recorded coupons and dividends" count={events.length}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Payment date", "left"],
                  ["security", "Security", "left"],
                  ["type", "Type", "left"],
                  ["gross", "Gross", "right"],
                  ["tax", "Withholding tax", "right"],
                  ["net", "Net", "right"],
                  ["account", "Account", "left"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={eventSort.sort.key === key}
                    direction={eventSort.sort.direction}
                    onSort={() => eventSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {eventSort.sortedRows.map((ev) => (
                <tr key={ev.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">{ev.payment_date}</td>
                  <td className="px-3 py-2">{securityLabel(ev.security_id)}</td>
                  <td className="px-3 py-2">{EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type}</td>
                  {/* Gross income and withholding use their declared currency, with
                      the euro value alongside. Net income is already in euros. */}
                  <td className="px-3 py-2 text-right" title={`Applied exchange rate: ${ev.fx_rate}`}>
                    {formatMoneyWithEur(
                      Number(ev.total_amount),
                      ev.currency,
                      Number(ev.total_eur)
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {/* Euro withholding equals gross minus net: both are already in euros.
                        Multiplying tax_withheld by the exchange rate gives the same
                        result, but that field uses the declared currency. */}
                    {formatMoneyWithEur(
                      Number(ev.tax_withheld),
                      ev.currency,
                      Number(ev.total_eur) - Number(ev.net_amount_eur)
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-medium text-green-600">
                    {ev.net_amount_eur ? formatEur(Number(ev.net_amount_eur)) : "—"}
                  </td>
                  <td className="px-3 py-2">{accountName(ev.account_id)}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() =>
                        confirm(
                          `Delete the event on ${ev.payment_date} (${securityLabel(ev.security_id)})?`,
                          () => deleteEvent.mutate(ev.id)
                        )
                      }
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {eventSort.sortedRows.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-3 py-6 text-center text-gray-400">
                    No coupons or dividends recorded.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {dialog}
    </div>
  );
}
