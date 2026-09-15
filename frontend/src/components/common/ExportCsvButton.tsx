import { useState } from "react";
import { downloadFile } from "@/api/client";
import type { DateRange } from "@/api/reports";

/** Export a report as CSV (specification §8.4).
 * Pass the tab's selected period to the backend's format=csv endpoint
 * so the exported data matches the report currently displayed. */
export interface ExportCsvButtonProps {
  /** Report path without its prefix, e.g. spending-analysis. */
  endpoint: string;
  /** Currently selected period, if the tab has one. */
  range?: DateRange;
  /** Suggested download filename. */
  filename: string;
  label?: string;
}

export default function ExportCsvButton({
  endpoint,
  range,
  filename,
  label = "⬇ Export CSV",
}: ExportCsvButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setBusy(true);
    setError(null);
    try {
      const params = new URLSearchParams({ format: "csv" });
      if (range?.from) params.set("date_from", range.from);
      if (range?.to) params.set("date_to", range.to);
      await downloadFile(`/reports/${endpoint}?${params.toString()}`, filename);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex flex-col items-end">
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
      >
        {busy ? "Preparing..." : label}
      </button>
      {error && <span className="mt-1 text-xs text-red-600">{error}</span>}
    </span>
  );
}
