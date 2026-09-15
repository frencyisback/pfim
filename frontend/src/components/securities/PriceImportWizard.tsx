import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  confirmPriceImport,
  invalidatePriceRelated,
  previewPriceImport,
  type PriceImportPreviewResult,
  type PriceImportResult,
} from "@/api/prices";
import { createLatestRequestGate } from "@/lib/latestRequest";
import { PricePreviewStatus } from "./PricePreviewStatus";

/** Security price CSV import wizard (2 steps, specification §5.3, §8.2).
 * Fixed date;ticker;close;fx_rate format: upload, preview rows, confirm.
 * No column mapping is needed, unlike bank transaction imports. */
interface Props {
  onClose: () => void;
}

type Step = 1 | 2;

export default function PriceImportWizard({ onClose }: Props) {
  const qc = useQueryClient();

  const [step, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<PriceImportPreviewResult | null>(null);
  const [result, setResult] = useState<PriceImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // Each new preview invalidates earlier responses: selecting file B while
  // A is in flight must never display A and then import B.
  const previewRequestGate = useRef(createLatestRequestGate()).current;

  async function handleFileSelect(f: File) {
    const requestId = previewRequestGate.begin();
    setFile(f);
    setPreview(null);
    setResult(null);
    setError(null);
    setLoading(true);
    try {
      const res = await previewPriceImport(f, 1);
      if (!previewRequestGate.isCurrent(requestId)) return;
      setPreview(res);
      setStep(2);
    } catch (err) {
      if (!previewRequestGate.isCurrent(requestId)) return;
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (previewRequestGate.isCurrent(requestId)) setLoading(false);
    }
  }

  async function handlePreviewPage(page: number) {
    if (!file || !preview || page < 1 || page > preview.total_pages) return;
    const requestId = previewRequestGate.begin();
    setError(null);
    setLoading(true);
    try {
      const res = await previewPriceImport(file, page, preview.page_size);
      if (!previewRequestGate.isCurrent(requestId)) return;
      setPreview(res);
    } catch (err) {
      if (!previewRequestGate.isCurrent(requestId)) return;
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      if (previewRequestGate.isCurrent(requestId)) setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!file) return;
    setError(null);
    setLoading(true);
    try {
      const res = await confirmPriceImport(file);
      setResult(res);
      invalidatePriceRelated(qc);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  const importableRows = preview ? preview.new_rows + preview.update_rows : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="max-h-[85vh] w-full max-w-2xl overflow-auto rounded-lg bg-white p-6 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold">Import prices from CSV</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">
            ✕
          </button>
        </div>

        <div className="mb-4 flex gap-2 text-xs">
          {["Upload", "Preview"].map((label, i) => (
            <div
              key={label}
              className={`flex-1 rounded px-2 py-1 text-center ${
                step === i + 1 ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-500"
              }`}
            >
              {i + 1}. {label}
            </div>
          ))}
        </div>

        {step === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Select a CSV file with columns:{" "}
              <code>date;ticker;close;fx_rate</code>. Only <code>date</code>, <code>ticker</code> and{" "}
              <code>close</code> are required (date format:{" "}
              <code>YYYY-MM-DD</code>). Securities are matched by exact ticker or, alternatively, ISIN.
            </p>
            <p className="text-xs text-gray-500">
              Columns are separated by a <strong>semicolon</strong> (<code>;</code>), rather than a comma, so prices may be entered as{" "}
              <code>17,50</code> or <code>17.50</code> without splitting columns.
            </p>
            <p className="text-xs text-gray-500">
              The <code>fx_rate</code> column is required <strong>only for securities quoted in currencies other than euros</strong>: it specifies the euro value of one currency unit on the row's date and is frozen with the price. For euro securities, leave it empty or omit the column entirely; existing files remain supported.
            </p>
            <input
              type="file"
              accept=".csv"
              disabled={loading}
              onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
              className="block w-full text-sm"
            />
            {loading && <p className="text-xs text-gray-400">Analysing file...</p>}
            {error && <p className="text-sm text-red-600">{error}</p>}
          </div>
        )}

        {step === 2 && preview && !result && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Selected file: <strong>{file?.name}</strong>
            </p>
            <div className="flex flex-wrap gap-4 text-sm">
              <span>Total rows: <strong>{preview.total_rows}</strong></span>
              <span className="text-green-600">New: <strong>{preview.new_rows}</strong></span>
              <span className="text-blue-600">Updates: <strong>{preview.update_rows}</strong></span>
              <span className="text-yellow-600">
                Unrecognised tickers: <strong>{preview.skipped_unrecognized_ticker}</strong>
              </span>
              <span className="text-red-600">Errors: <strong>{preview.error_rows}</strong></span>
            </div>

            <p className="text-xs text-gray-500">
              For the same security and date, the last valid row in the file takes precedence, even on another page. Counts follow all rows in order; preview does not reserve prices, which are revalidated on confirmation.
            </p>
            <div className="max-h-64 overflow-auto rounded border border-gray-200">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-left text-gray-500">
                  <tr>
                    <th className="px-2 py-1">#</th>
                    <th className="px-2 py-1">Date</th>
                    <th className="px-2 py-1">Ticker</th>
                    <th className="px-2 py-1 text-right">Price</th>
                    <th className="px-2 py-1 text-right">Exchange rate</th>
                    <th className="px-2 py-1 text-right">In euros</th>
                    <th className="px-2 py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr
                      key={r.row_number}
                      className={`border-t border-gray-100 ${
                        r.errors.length
                          ? "bg-red-50"
                          : r.security_id === null
                            ? "bg-yellow-50"
                            : r.is_update
                              ? "bg-blue-50"
                              : ""
                      }`}
                    >
                      <td className="px-2 py-1">{r.row_number}</td>
                      <td className="px-2 py-1">{r.date ?? "—"}</td>
                      <td className="px-2 py-1">
                        {r.ticker ?? "—"}
                        {r.currency && r.currency !== "EUR" && (
                          <span className="ml-1 text-[10px] text-amber-700">{r.currency}</span>
                        )}
                      </td>
                      <td className="px-2 py-1 text-right">{r.close ?? "—"}</td>
                      {/* Show the exchange rate and euro value only where needed:
                          for a euro security these would be two columns of "1". */}
                      <td className="px-2 py-1 text-right text-gray-500">
                        {r.currency && r.currency !== "EUR" ? (r.fx_rate ?? "—") : ""}
                      </td>
                      <td className="px-2 py-1 text-right text-gray-500">
                        {r.currency && r.currency !== "EUR" ? (r.close_eur ?? "—") : ""}
                      </td>
                      <td className="px-2 py-1">
                        <PricePreviewStatus row={r} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between text-xs text-gray-500">
              <button
                onClick={() => handlePreviewPage(preview.page - 1)}
                disabled={loading || preview.page <= 1}
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              >
                ← Previous
              </button>
              <span>
                Page <strong>{preview.page}</strong> of <strong>{preview.total_pages}</strong>
                {" · "}{preview.rows.length} rows displayed out of {preview.total_rows}
              </span>
              <button
                onClick={() => handlePreviewPage(preview.page + 1)}
                disabled={loading || preview.page >= preview.total_pages}
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              >
                Next →
              </button>
            </div>

            {preview.error_rows > 0 && (
              <p className="text-sm text-red-600">
                Correct all {preview.error_rows} rows with errors before confirming, including those on other pages.
              </p>
            )}

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex justify-between pt-2">
              <button
                onClick={() => {
                  previewRequestGate.invalidate();
                  setLoading(false);
                  setStep(1);
                  setPreview(null);
                }}
                disabled={loading}
                className="text-xs text-gray-400 hover:underline"
              >
                ← Back
              </button>
              <button
                onClick={handleConfirm}
                disabled={loading || importableRows === 0 || preview.error_rows > 0}
                className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {loading ? "Importing..." : `Confirm import (${importableRows} rows)`}
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <p className="text-sm">
              ✅ Imported <strong>{result.imported}</strong> new prices, updated{" "}
              <strong>{result.updated}</strong>. Skipped <strong>{result.skipped_unrecognized_ticker}</strong>{" "}
              for unrecognised tickers, <strong>{result.errors}</strong> errors.
            </p>
            <button
              onClick={onClose}
              className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
