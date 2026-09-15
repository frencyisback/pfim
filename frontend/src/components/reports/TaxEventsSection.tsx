import { useState } from "react";
import { type DateRange } from "@/api/reports";
import {
  TAX_EVENT_TYPES,
  taxEventTypeLabel,
  useCreateTaxEvent,
  useDeleteTaxEvent,
  useTaxEvents,
  useUpdateTaxEvent,
  type TaxEvent,
} from "@/api/tax";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SortableHeader from "@/components/common/SortableHeader";
import { todayIso } from "@/lib/dates";
import { formatEur } from "@/lib/formatters";
import { useTableSort } from "@/lib/useTableSort";
import { describeTaxEvent } from "@/lib/taxEventPresentation";
import TaxEventActions from "./TaxEventActions";

/** Flexible tax register (specification §11.1). Sales generate capital
 * gains/loss events automatically. This tab records external withholding,
 * carried-forward losses and separately paid taxes. Automatic entries
 * can only be changed through their source trade to maintain consistency. */
export function TaxEventsSection({ range }: { range: DateRange }) {
  const { data: events, isLoading, error: queryError } = useTaxEvents(range);
  const createEvent = useCreateTaxEvent();
  const deleteEvent = useDeleteTaxEvent();
  const updateEvent = useUpdateTaxEvent();
  const { confirm, dialog } = useConfirmDialog();

  const [form, setForm] = useState({
    event_date: todayIso(),
    event_type: "other",
    description: "",
    gross_amount: "",
    tax_amount: "",
  });
  const [error, setError] = useState<string | null>(null);
  type TaxSortKey = "date" | "type" | "description" | "gross" | "tax" | "origin";
  const eventSort = useTableSort<TaxEvent, TaxSortKey>(
    events ?? [],
    { key: "date", direction: "desc" },
    (event, key) => {
      if (key === "date") return event.event_date;
      if (key === "type") return taxEventTypeLabel(event.event_type);
      if (key === "description") return event.description;
      if (key === "gross") return event.gross_amount === null ? null : Number(event.gross_amount);
      if (key === "tax") return event.tax_amount === null ? null : Number(event.tax_amount);
      return describeTaxEvent(event).label;
    }
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.description) {
      setError("Description is required.");
      return;
    }
    try {
      await createEvent.mutateAsync({
        event_date: form.event_date,
        event_type: form.event_type,
        description: form.description,
        gross_amount: form.gross_amount || null,
        tax_amount: form.tax_amount || null,
      });
      setForm({ ...form, description: "", gross_amount: "", tax_amount: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await deleteEvent.mutateAsync(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleUnlink(event: TaxEvent) {
    if (!describeTaxEvent(event).canUnlink) return;
    setError(null);
    try {
      await updateEvent.mutateAsync({
        id: event.id,
        data: { related_trade_id: null, related_income_id: null },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium text-gray-600">Recorded tax entries</h3>

      <p className="max-w-3xl text-xs text-gray-500">
        Capital gains and losses from sales appear here <strong>automatically</strong>. Manually add only information unavailable to the system: external withholding, prior losses and separately paid taxes.
        <br />
        Estimates based on tax rates do not replace tax documents: consult a professional before filing.
      </p>

      <form
        onSubmit={handleCreate}
        className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-6"
      >
        <input
          type="date"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.event_date}
          onChange={(e) => setForm({ ...form, event_date: e.target.value })}
        />
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.event_type}
          onChange={(e) => setForm({ ...form, event_type: e.target.value })}
        >
          {TAX_EVENT_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Description"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm md:col-span-2"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <input
          type="number"
          step="0.01"
          placeholder="Gross amount €"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.gross_amount}
          onChange={(e) => setForm({ ...form, gross_amount: e.target.value })}
        />
        <input
          type="number"
          step="0.01"
          placeholder="Tax €"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.tax_amount}
          onChange={(e) => setForm({ ...form, tax_amount: e.target.value })}
        />
        <button
          type="submit"
          disabled={createEvent.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50 md:col-span-1"
        >
          {createEvent.isPending ? "Saving..." : "Add entry"}
        </button>
        {error && <p className="col-span-full text-sm text-red-600">{error}</p>}
      </form>

      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (
        <CollapsibleTable title="Tax register" count={events?.length ?? 0}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Date", "left"],
                  ["type", "Type", "left"],
                  ["description", "Description", "left"],
                  ["gross", "Gross", "right"],
                  ["tax", "Tax", "right"],
                  ["origin", "Origin", "left"],
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
              {eventSort.sortedRows.map((ev) => {
                const presentation = describeTaxEvent(ev);
                return (
                  <tr key={ev.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">{ev.event_date}</td>
                    <td className="px-3 py-2">{taxEventTypeLabel(ev.event_type)}</td>
                    <td className="px-3 py-2">{ev.description}</td>
                    <td
                      className={`px-3 py-2 text-right ${
                        Number(ev.gross_amount ?? 0) < 0 ? "text-red-600" : "text-green-600"
                      }`}
                    >
                      {ev.gross_amount === null ? "—" : formatEur(Number(ev.gross_amount))}
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500">
                      {ev.tax_amount === null ? "—" : formatEur(Number(ev.tax_amount))}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-400">
                      {presentation.label}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <TaxEventActions
                        event={ev}
                        pending={deleteEvent.isPending || updateEvent.isPending}
                        onDelete={() => confirm(`Delete entry '${ev.description}'?`, () => handleDelete(ev.id))}
                        onUnlink={() => confirm(
                          `Unlink the source from '${ev.description}'? The tax entry and its origin will be retained.`,
                          () => handleUnlink(ev),
                          "Unlink"
                        )}
                      />
                    </td>
                  </tr>
                );
              })}
              {events?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-gray-400">
                    No tax entries in this period.
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
