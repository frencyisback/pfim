import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAccounts } from "@/api/accounts";
import { useCsvImportProfiles } from "@/api/csvProfiles";
import {
  confirmCsvImport,
  csvProfileFromSaved,
  DEFAULT_PROFILE,
  previewCsvImport,
  type CsvProfile,
} from "@/api/importCsv";
import { CURRENCY_OPTIONS, needsFxRate } from "@/lib/currency";
import {
  CATEGORY_COLUMN_REQUIRED_MESSAGE,
  validateCategoryColumn,
} from "@/lib/csvImportRules";
import { containsSelectedId, getWritableCashAccounts } from "@/lib/lifecycle";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import {
  createCsvImportSession,
  EMPTY_CSV_IMPORT_STATE,
} from "@/lib/csvImportSession";

/** Transaction CSV import wizard (4 steps, specification §8.1):
 * 1. Upload file
 * 2. Select bank profile
 * 3. Map columns
 * 4. Preview and confirm */
interface Props {
  onClose: () => void;
}

type Step = 1 | 2 | 3 | 4;

export default function ImportCsvWizard({ onClose }: Props) {
  const qc = useQueryClient();
  const {
    data: accounts,
    isLoading: accountsLoading,
    error: accountsError,
  } = useAccounts(true);
  const {
    data: savedProfiles,
    isLoading: profilesLoading,
    error: profilesError,
  } = useCsvImportProfiles();

  const [inputStep, setStep] = useState<Step>(1);
  const [file, setFile] = useState<File | null>(null);
  const [profileName, setProfileName] = useState("Custom");
  const [profile, setProfile] = useState<CsvProfile>(DEFAULT_PROFILE);
  const [accountId, setAccountId] = useState<string>("");
  // One exchange rate applies to the whole file because a bank statement
  // uses a single currency (docs/multi-currency.md).
  const [fxRate, setFxRate] = useState("");
  const [validationError, setError] = useState<string | null>(null);
  const [importState, setImportState] = useState(EMPTY_CSV_IMPORT_STATE);
  const [session] = useState(() => createCsvImportSession({
    preview: previewCsvImport,
    confirm: confirmCsvImport,
    onImported: () => {
      for (const key of ["transactions", "accounts", "reports"]) {
        void qc.invalidateQueries({ queryKey: [key] });
      }
    },
  }, setImportState));
  useEffect(() => () => session.invalidate(false), [session]);
  const { preview, result, snapshot } = importState;
  const loading = importState.pending !== null;
  const error = validationError ?? importState.error;
  const step = preview ? 4 : inputStep;
  const foreignFile = needsFxRate(profile.default_currency);
  const missingCategoryMapping = validateCategoryColumn(profile.category_column) !== null;
  const writableAccounts = getWritableCashAccounts(accounts);
  const selectedAccountName =
    writableAccounts.find((a) => a.id === (snapshot?.accountId ?? Number(accountId)))?.name ??
    "no account selected";

  function invalidatePreview() {
    session.invalidate();
    setError(null);
  }

  function handleProfileChange(next: CsvProfile) {
    invalidatePreview();
    setProfile(next);
  }

  function handleBack(next: Step) {
    invalidatePreview();
    setStep(next);
  }

  function handleClose() {
    invalidatePreview();
    onClose();
  }

  function handleFileSelect(f: File) {
    invalidatePreview();
    setFile(f);
    setStep(2);
  }

  function handleProfileSelect(name: string) {
    invalidatePreview();
    setProfileName(name);
    setFxRate("");
    if (name === "Custom") {
      setProfile(DEFAULT_PROFILE);
    } else {
      const saved = savedProfiles?.find((p) => p.name === name);
      if (saved) setProfile(csvProfileFromSaved(saved));
    }
    setStep(3);
  }

  // Select the account before previewing: duplicate detection applies
  // to a specific destination account (docs/csv-formats.md).
  // Asking for the account afterwards would make the Status column
  // answer a different question from the operation the user is about
  // to perform.
  function handlePreview() {
    if (!file) return;
    const categoryColumnError = validateCategoryColumn(profile.category_column);
    if (categoryColumnError) {
      setError(categoryColumnError);
      return;
    }
    if (!containsSelectedId(writableAccounts, accountId)) {
      setError("Select an active cash account as the destination.");
      return;
    }
    setError(null);
    void session.preview({ file, profile, accountId: Number(accountId), fxRate });
  }

  function handlePreviewPage(page: number) {
    if (!snapshot || !preview || page < 1 || page > preview.total_pages) return;
    if (!containsSelectedId(writableAccounts, String(snapshot.accountId))) {
      setError("The selected account is no longer active: go back and select another.");
      return;
    }
    setError(null);
    void session.page(page);
  }

  function handleConfirm() {
    if (!snapshot || !containsSelectedId(writableAccounts, String(snapshot.accountId))) {
      setError("Select an active cash account as the destination.");
      return;
    }
    setError(null);
    void session.confirm();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <fieldset
        disabled={loading}
        aria-busy={loading}
        role="dialog"
        aria-modal="true"
        aria-labelledby="csv-import-title"
        className="max-h-[85vh] min-w-0 w-full max-w-2xl overflow-auto rounded-lg bg-white p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 id="csv-import-title" className="text-lg font-semibold">Import transactions from CSV</h3>
          <button onClick={handleClose} disabled={loading} className="text-gray-400 hover:text-gray-700 disabled:opacity-50">
            ✕
          </button>
        </div>

        <StepIndicator current={step} />

        <QueryStateNotice
          isLoading={accountsLoading || profilesLoading}
          error={accountsError ?? profilesError}
        />

        {step === 1 && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">Select the CSV file exported by your bank.</p>
            <input
              type="file"
              accept=".csv"
              onChange={(e) => e.target.files?.[0] && handleFileSelect(e.target.files[0])}
              className="block w-full text-sm"
            />
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Selected file: <strong>{file?.name}</strong>. Choose a bank profile or customise the mapping in the next step.
            </p>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => handleProfileSelect("Custom")}
                className={`rounded border px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                  profileName === "Custom" ? "border-gray-900" : "border-gray-300"
                }`}
              >
                Custom
              </button>
              {savedProfiles?.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleProfileSelect(p.name)}
                  className={`rounded border px-3 py-2 text-left text-sm hover:bg-gray-50 ${
                    profileName === p.name ? "border-gray-900" : "border-gray-300"
                  }`}
                >
                  <span>{p.name}</span>
                  {!p.category_column?.trim() && (
                    <span className="ml-2 text-xs text-amber-700">
                      — category mapping required
                    </span>
                  )}
                </button>
              ))}
              {savedProfiles?.length === 0 && (
                <p className="text-xs text-gray-400">
                  No saved profiles. Create one in Settings → CSV import templates or continue with Custom.
                </p>
              )}
            </div>
            <button onClick={() => handleBack(1)} className="text-xs text-gray-400 hover:underline">
              ← Back
            </button>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              Column mapping (profile: <strong>{profileName}</strong>). Adjust if needed.
            </p>
            <p className="text-xs text-gray-500">
              A category column is required. Each CSV value must exactly match an existing category name in Settings, ignoring case; otherwise the preview marks the row as an error.
            </p>
            {missingCategoryMapping && (
              <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {profileName === "Custom"
                  ? CATEGORY_COLUMN_REQUIRED_MESSAGE
                  : `Saved profile “${profileName}” has no category mapping. ${CATEGORY_COLUMN_REQUIRED_MESSAGE}`}
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 text-sm">
              <label className="flex flex-col gap-1">
                Delimiter
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.delimiter}
                  onChange={(e) => handleProfileChange({ ...profile, delimiter: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Rows to skip
                <input
                  type="number"
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.skip_rows}
                  onChange={(e) => handleProfileChange({ ...profile, skip_rows: Number(e.target.value) })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Date format
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.date_format}
                  onChange={(e) => handleProfileChange({ ...profile, date_format: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Decimal separator
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.decimal_separator}
                  onChange={(e) => handleProfileChange({ ...profile, decimal_separator: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Date column
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.date_column}
                  onChange={(e) => handleProfileChange({ ...profile, date_column: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Description column
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.description_column}
                  onChange={(e) => handleProfileChange({ ...profile, description_column: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Amount column
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.amount_column}
                  onChange={(e) => handleProfileChange({ ...profile, amount_column: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                Category column (required)
                <input
                  className="rounded border border-gray-300 px-2 py-1"
                  placeholder="e.g. Category"
                  value={profile.category_column}
                  onChange={(e) => {
                    handleProfileChange({ ...profile, category_column: e.target.value });
                  }}
                  aria-invalid={missingCategoryMapping}
                  required
                />
              </label>
              <label className="flex flex-col gap-1">
                Default currency
                <select
                  className="rounded border border-gray-300 px-2 py-1"
                  value={profile.default_currency}
                  onChange={(e) => {
                    handleProfileChange({ ...profile, default_currency: e.target.value });
                    setFxRate("");
                  }}
                >
                  {CURRENCY_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.value}
                    </option>
                  ))}
                </select>
              </label>
              {foreignFile && (
                <label className="flex flex-col gap-1">
                  Exchange rate (1 {profile.default_currency} = ? €)
                  <input
                    type="number"
                    step="0.00000001"
                    min="0"
                    placeholder="0,00000000"
                    className="rounded border border-gray-300 px-2 py-1"
                    value={fxRate}
                    onChange={(e) => {
                      invalidatePreview();
                      setFxRate(e.target.value);
                    }}
                  />
                </label>
              )}
            </div>
            {foreignFile && (
              <p className="text-xs text-gray-500">
                The file uses {profile.default_currency}: this exchange rate applies to{" "}
                <strong>all</strong> rows and is frozen on each transaction. Without a rate, the import is rejected before any rows are written.
              </p>
            )}

            <label className="flex flex-col gap-1 text-sm">
              Destination account
              <select
                className="rounded border border-gray-300 px-2 py-1.5"
                value={accountId}
                onChange={(e) => {
                  invalidatePreview();
                  setAccountId(e.target.value);
                }}
              >
                <option value="">Select...</option>
                {writableAccounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-xs text-gray-500">
              Required now: preview detects duplicates by comparing rows with transactions <strong>in this account</strong>. The same transaction in another account is a separate transaction rather than a duplicate.
            </p>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex justify-between pt-2">
              <button onClick={() => handleBack(2)} className="text-xs text-gray-400 hover:underline">
                ← Back
              </button>
              <button
                onClick={handlePreview}
                disabled={
                  loading ||
                  missingCategoryMapping ||
                  !containsSelectedId(writableAccounts, accountId) ||
                  (foreignFile && !fxRate)
                }
                className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {loading ? "Analysing..." : "Generate preview →"}
              </button>
            </div>
          </div>
        )}

        {step === 4 && preview && !result && (
          <div className="space-y-3">
            <p className="text-sm text-gray-600">
              File: <strong>{snapshot?.file.name}</strong> · Currency: <strong>{snapshot?.profile.default_currency}</strong>
              {snapshot && needsFxRate(snapshot.profile.default_currency) && (
                <> · Exchange rate: <strong>{snapshot.fxRate}</strong> EUR per {snapshot.profile.default_currency}</>
              )}
            </p>
            <div className="flex gap-4 text-sm">
              <span>Total rows: <strong>{preview.total_rows}</strong></span>
              <span className="text-yellow-600">Duplicates: <strong>{preview.duplicate_rows}</strong></span>
              <span className="text-red-600">Errors: <strong>{preview.error_rows}</strong></span>
            </div>

            <div className="max-h-64 overflow-auto rounded border border-gray-200">
              <table className="w-full text-xs">
                <thead className="bg-gray-50 text-left text-gray-500">
                  <tr>
                    <th className="px-2 py-1">#</th>
                    <th className="px-2 py-1">Date</th>
                    <th className="px-2 py-1">Description</th>
                    <th className="px-2 py-1 text-right">Amount</th>
                    <th className="px-2 py-1">Category</th>
                    <th className="px-2 py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.map((r) => (
                    <tr
                      key={r.row_number}
                      className={`border-t border-gray-100 ${r.errors.length ? "bg-red-50" : r.is_duplicate ? "bg-yellow-50" : ""}`}
                    >
                      <td className="px-2 py-1">{r.row_number}</td>
                      <td className="px-2 py-1">{r.date ?? "—"}</td>
                      <td className="px-2 py-1">{r.description ?? "—"}</td>
                      <td className="px-2 py-1 text-right">{r.amount ?? "—"}</td>
                      <td className="px-2 py-1">{r.category ?? "—"}</td>
                      <td className="px-2 py-1">
                        {r.errors.length ? r.errors.join("; ") : r.is_duplicate ? "Duplicate" : "OK"}
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

            <p className="text-sm text-gray-600">
              Destination: <strong>{selectedAccountName}</strong>. Duplicates are rows already present in this account or repeated within the file.
            </p>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <div className="flex justify-between pt-2">
              <button onClick={() => handleBack(3)} className="text-xs text-gray-400 hover:underline">
                ← Back
              </button>
              <button
                onClick={handleConfirm}
                disabled={
                  loading ||
                  missingCategoryMapping ||
                  !snapshot || !containsSelectedId(writableAccounts, String(snapshot.accountId)) ||
                  preview.error_rows > 0
                }
                className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
              >
                {loading ? (importState.pending === "confirm" ? "Importing..." : "Analysing...") : `Confirm import (${preview.total_rows - preview.duplicate_rows - preview.error_rows} rows)`}
              </button>
            </div>
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <p className="text-sm">
              ✅ Imported <strong>{result.imported}</strong> transactions. Skipped{" "}
              <strong>{result.skipped_duplicates}</strong> duplicates, <strong>{result.errors}</strong> errors.
            </p>
            <button
              onClick={handleClose}
              className="rounded bg-gray-900 px-4 py-1.5 text-sm text-white hover:bg-gray-700"
            >
              Close
            </button>
          </div>
        )}
      </fieldset>
    </div>
  );
}

function StepIndicator({ current }: { current: Step }) {
  const labels = ["Upload", "Profile", "Mapping", "Preview"];
  return (
    <div className="mb-4 flex gap-2 text-xs">
      {labels.map((label, i) => (
        <div
          key={label}
          className={`flex-1 rounded px-2 py-1 text-center ${
            current === i + 1 ? "bg-gray-900 text-white" : "bg-gray-100 text-gray-500"
          }`}
        >
          {i + 1}. {label}
        </div>
      ))}
    </div>
  );
}
