import { type DateRange } from "@/api/reports";
import { isoMonth, monthEndIso, monthStartIso, recentMonthRange } from "@/lib/dates";

/** Shared analysis period selector. Users select whole months; the first
 * and last months become their first and last days, preserving the ISO
 * date contract used by APIs and exports. */
export function DateRangeFilter({
  range,
  onChange,
}: {
  range: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const currentYear = new Date().getFullYear();

  function changeFrom(month: string) {
    if (!month) {
      onChange({ ...range, from: undefined });
      return;
    }
    const from = monthStartIso(month);
    const currentToMonth = isoMonth(range.to);
    const to = !currentToMonth || currentToMonth < month ? monthEndIso(month) : range.to;
    onChange({ from, to });
  }

  function changeTo(month: string) {
    if (!month) {
      onChange({ ...range, to: undefined });
      return;
    }
    const to = monthEndIso(month);
    const currentFromMonth = isoMonth(range.from);
    const from = !currentFromMonth || currentFromMonth > month ? monthStartIso(month) : range.from;
    onChange({ from, to });
  }

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-gray-200 bg-white p-3">
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        From month
        <input
          type="month"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={isoMonth(range.from)}
          onChange={(e) => changeFrom(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs text-gray-500">
        To month
        <input
          type="month"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={isoMonth(range.to)}
          onChange={(e) => changeTo(e.target.value)}
        />
      </label>
      {([1, 3] as const).map((months) => (
        <button
          type="button"
          key={months}
          onClick={() => onChange(recentMonthRange(months))}
          title={months === 1 ? "Current month" : "Current month and previous two months"}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
        >
          {months === 1 ? "1 month" : "3 months"}
        </button>
      ))}
      {[currentYear, currentYear - 1, currentYear - 2].map((y) => (
        <button
          type="button"
          key={y}
          onClick={() => onChange({ from: `${y}-01-01`, to: `${y}-12-31` })}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
        >
          {y}
        </button>
      ))}
      {(range.from || range.to) && (
        <button
          type="button"
          onClick={() => onChange({})}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
        >
          All history
        </button>
      )}
    </div>
  );
}
