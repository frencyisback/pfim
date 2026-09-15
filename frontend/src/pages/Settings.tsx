import { useState } from "react";
import {
  useAccounts,
  useCreateAccount,
  useDeactivateAccount,
  useDeleteAccount,
  useUpdateAccount,
} from "@/api/accounts";
import type { Account, CsvImportProfile } from "@/api/types";
import { useCategories, useCreateCategory, useDeleteCategory } from "@/api/categories";
import { useFxRates, useImportFxRates, type FxRate, type FxRateImportResult } from "@/api/fxRates";
import { FxImportResultNotice } from "@/components/settings/FxImportResultNotice";
import { useTaxSettings, useUpdateTaxSetting, type TaxSetting } from "@/api/tax";
import {
  useCreateCsvImportProfile,
  useCsvImportProfiles,
  useDeleteCsvImportProfile,
} from "@/api/csvProfiles";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SortableHeader from "@/components/common/SortableHeader";
import { validateCategoryColumn } from "@/lib/csvImportRules";
import { todayIso } from "@/lib/dates";
import { containsSelectedId, getWritableCashAccounts } from "@/lib/lifecycle";
import { useTableSort } from "@/lib/useTableSort";

/**
 * Settings page: account, category and tax rate management, plus CSV mapping
 * templates for transaction imports.
 * Specification §7.7, §8.1 and §11.3.
 *
 * Backup and restore are in Reports → Backup, alongside the other exportable
 * reports.
 */
export default function Settings() {
  return (
    <div className="space-y-8">
      <h2 className="text-xl font-semibold">Settings</h2>
      <AccountsSection />
      <CategoriesSection />
      <TaxSettingsSection />
      <FxRatesSection />
      <CsvProfilesSection />
    </div>
  );
}

/**
 * Exchange rate archive.
 *
 * Calculations use the exchange rate declared when each transaction is
 * entered. This archive lets forms suggest a value so users do not have
 * to look it up elsewhere each time.
 */
function FxRatesSection() {
  const { data: rates, isLoading, error: queryError } = useFxRates();
  const importRates = useImportFxRates();
  const [result, setResult] = useState<FxRateImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  type FxSortKey = "date" | "pair" | "rate" | "source";
  const rateSort = useTableSort<FxRate, FxSortKey>(
    rates ?? [],
    { key: "date", direction: "desc" },
    (rate, key) => {
      if (key === "date") return rate.date;
      if (key === "pair") return `${rate.from_currency}/${rate.to_currency}`;
      if (key === "rate") return Number(rate.rate);
      return rate.source;
    }
  );

  async function handleFile(file: File) {
    setError(null);
    setResult(null);
    try {
      const res = await importRates.mutateAsync(file);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-1 font-medium">Exchange rate archive</h3>
      <p className="mb-3 max-w-3xl text-xs text-gray-500">
        Used only to <strong>suggest</strong> an exchange rate when recording a transaction in a foreign
        currency. The value you confirm when saving is authoritative and remains fixed
        on that transaction. If the archive is empty, simply enter the rate manually.
        <br />
        File format, delimiter <code>;</code>: <code>date;from;to;rate</code>. When importing{" "}
        <code>USD;EUR</code> the reciprocal is calculated automatically.
      </p>

      <input
        type="file"
        accept=".csv"
        onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        className="mb-3 block text-sm"
      />
      {importRates.isPending && <p className="text-xs text-gray-400">Importing...</p>}
      {result && <FxImportResultNotice result={result} />}
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (rates && rates.length > 0 ? (
        <CollapsibleTable title="Archived rates" count={rates.length}>
          <div className="max-h-56 max-w-xl overflow-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Date", "left"],
                  ["pair", "Pair", "left"],
                  ["rate", "Rate", "right"],
                  ["source", "Origin", "left"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={rateSort.sort.key === key}
                    direction={rateSort.sort.direction}
                    onSort={() => rateSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
              </tr>
            </thead>
            <tbody>
              {rateSort.sortedRows.map((r) => (
                <tr key={r.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">{r.date}</td>
                  <td className="px-3 py-2">
                    {r.from_currency} → {r.to_currency}
                  </td>
                  <td className="px-3 py-2 text-right">{r.rate}</td>
                  <td className="px-3 py-2 text-xs text-gray-400">{r.source}</td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      ) : (
        <p className="text-sm text-gray-400">
          No rates archived. You can enter exchange rates directly in the forms.
        </p>
      ))}
    </section>
  );
}

const EMPTY_CSV_PROFILE_FORM = {
  name: "",
  delimiter: ";",
  skip_rows: "0",
  date_format: "%d/%m/%Y",
  date_column: "Date",
  description_column: "Description",
  amount_column: "Amount",
  category_column: "",
  decimal_separator: ",",
  default_currency: "EUR",
};

function CsvProfilesSection() {
  const { data: profiles, isLoading, error: queryError } = useCsvImportProfiles();
  const createProfile = useCreateCsvImportProfile();
  const deleteProfile = useDeleteCsvImportProfile();
  const { confirm, dialog } = useConfirmDialog();
  const [form, setForm] = useState(EMPTY_CSV_PROFILE_FORM);
  const [error, setError] = useState<string | null>(null);
  type ProfileSortKey = "name" | "delimiter" | "columns" | "dateFormat";
  const profileSort = useTableSort<CsvImportProfile, ProfileSortKey>(
    profiles ?? [],
    { key: "name", direction: "asc" },
    (profile, key) => {
      if (key === "name") return profile.name;
      if (key === "delimiter") return profile.delimiter;
      if (key === "columns") {
        return `${profile.date_column}/${profile.description_column}/${profile.amount_column}/${profile.category_column ?? ""}`;
      }
      return profile.date_format;
    }
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name || !form.date_column || !form.amount_column) {
      setError("Name, date column and amount column are required.");
      return;
    }
    const categoryColumnError = validateCategoryColumn(form.category_column);
    if (categoryColumnError) {
      setError(categoryColumnError);
      return;
    }
    try {
      await createProfile.mutateAsync({
        name: form.name,
        delimiter: form.delimiter,
        skip_rows: Number(form.skip_rows) || 0,
        date_format: form.date_format,
        date_column: form.date_column,
        description_column: form.description_column,
        amount_column: form.amount_column,
        category_column: form.category_column.trim(),
        decimal_separator: form.decimal_separator,
        default_currency: form.default_currency,
      });
      setForm(EMPTY_CSV_PROFILE_FORM);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-1 font-medium">CSV import templates — Cash Flow transactions</h3>
      <p className="mb-3 text-xs text-gray-500">
        These profiles apply <strong>only</strong> to bank transaction imports
        (Cash Flow → Import CSV), whose format varies by bank. The category column is
        required, and its CSV value must match the name of an existing category.
        <br />
        Importing <strong>security prices</strong> (Securities → Prices → Import CSV) uses a fixed format (<code>date;ticker;close;fx_rate</code>) and does not use these profiles or require any configuration.
      </p>
      <form
        onSubmit={handleCreate}
        className="mb-4 grid grid-cols-2 gap-2 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-5"
      >
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Profile name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Delimiter"
          value={form.delimiter}
          onChange={(e) => setForm({ ...form, delimiter: e.target.value })}
        />
        <input
          type="number"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Rows to skip"
          value={form.skip_rows}
          onChange={(e) => setForm({ ...form, skip_rows: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Date format"
          value={form.date_format}
          onChange={(e) => setForm({ ...form, date_format: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Decimal separator"
          value={form.decimal_separator}
          onChange={(e) => setForm({ ...form, decimal_separator: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Date column"
          value={form.date_column}
          onChange={(e) => setForm({ ...form, date_column: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Description column"
          value={form.description_column}
          onChange={(e) => setForm({ ...form, description_column: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Amount column"
          value={form.amount_column}
          onChange={(e) => setForm({ ...form, amount_column: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Category column"
          value={form.category_column}
          onChange={(e) => setForm({ ...form, category_column: e.target.value })}
          required
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Default currency"
          value={form.default_currency}
          onChange={(e) => setForm({ ...form, default_currency: e.target.value })}
        />
        <button
          type="submit"
          disabled={createProfile.isPending}
          className="col-span-2 rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50 md:col-span-1"
        >
          {createProfile.isPending ? "Saving..." : "Add profile"}
        </button>
        {error && <p className="col-span-full text-sm text-red-600">{error}</p>}
      </form>

      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (
        <CollapsibleTable title="Saved CSV profiles" count={profiles?.length ?? 0}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["name", "Name"],
                  ["delimiter", "Delimiter"],
                  ["columns", "Columns (date/description/amount/category)"],
                  ["dateFormat", "Date format"],
                ] as const).map(([key, label]) => (
                  <SortableHeader
                    key={key}
                    active={profileSort.sort.key === key}
                    direction={profileSort.sort.direction}
                    onSort={() => profileSort.requestSort(key)}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {profileSort.sortedRows.map((p) => (
                <tr key={p.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium">{p.name}</td>
                  <td className="px-3 py-2">{p.delimiter}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">
                    {p.date_column} / {p.description_column} / {p.amount_column} /{" "}
                    {p.category_column?.trim() ? (
                      p.category_column
                    ) : (
                      <span className="font-medium text-amber-700">
                        Category mapping missing
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">{p.date_format}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() =>
                        confirm(`Delete profile '${p.name}'?`, () =>
                          deleteProfile.mutate(p.id)
                        )
                      }
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {profiles?.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-gray-400">
                    No CSV profiles configured.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {dialog}
    </section>
  );
}

function TaxSettingsSection() {
  const { data: taxSettings, isLoading, error: queryError } = useTaxSettings();
  const updateSetting = useUpdateTaxSetting();
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const taxSort = useTableSort<TaxSetting, "setting">(
    taxSettings ?? [],
    { key: "setting", direction: "asc" },
    (setting) => `${setting.key} ${setting.description ?? ""}`
  );

  async function handleSave(key: string) {
    setError(null);
    const raw = editing[key];
    if (raw === undefined) return;
    if (raw.trim() === "") {
      setError("Enter a rate between 0% and 100%.");
      return;
    }
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0 || value > 100) {
      setError("Each rate must be between 0% and 100%.");
      return;
    }
    try {
      await updateSetting.mutateAsync({ key, value });
      setEditing((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-1 font-medium">Taxation</h3>
      <p className="mb-3 text-xs text-gray-500">
        Rates used to estimate taxes in the tax register. You can change them at any
        time; recorded sales retain the rate applied at the time of sale.
      </p>
      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (
        <CollapsibleTable title="Tax rates" count={taxSettings?.length ?? 0}>
          <table className="w-full max-w-xl text-sm">
            <thead className="text-left text-gray-500">
              <tr>
                <SortableHeader
                  active
                  direction={taxSort.sort.direction}
                  onSort={() => taxSort.requestSort("setting")}
                  className="py-2 pr-4"
                >
                  Parameter
                </SortableHeader>
                <th className="py-2 text-right">Editable value</th>
              </tr>
            </thead>
            <tbody>
            {taxSort.sortedRows.map((s) => (
              <tr key={s.key} className="border-t border-gray-100">
                <td className="py-2 pr-4">
                  <div className="font-medium">{s.key}</div>
                  <div className="text-xs text-gray-400">{s.description}</div>
                </td>
                <td className="py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.0001"
                      className="w-20 rounded border border-gray-300 px-2 py-1 text-right text-sm"
                      value={editing[s.key] ?? s.value}
                      onChange={(e) => setEditing({ ...editing, [s.key]: e.target.value })}
                    />
                    <span className="text-xs text-gray-400">%</span>
                    <button
                      type="button"
                      onClick={() => handleSave(s.key)}
                      disabled={updateSetting.isPending}
                      className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50"
                    >
                      Save
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            </tbody>
          </table>
        </CollapsibleTable>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-600">
          {error}
        </p>
      )}
    </section>
  );
}

const ACCOUNT_TYPE_LABELS: Record<string, string> = {
  checking: "Checking account",
  savings: "Deposit",
  investment: "Investment",
  cash: "Cash",
};

function AccountsSection() {
  const { data: accounts, isLoading, error: queryError } = useAccounts();
  const createAccount = useCreateAccount();
  const updateAccount = useUpdateAccount();
  const deactivateAccount = useDeactivateAccount();
  const deleteAccount = useDeleteAccount();
  const { confirm, dialog } = useConfirmDialog();
  const [form, setForm] = useState({
    name: "",
    type: "checking",
    opening_balance: "0",
    opened_on: todayIso(),
    reference_account_id: "",
  });
  const [error, setError] = useState<string | null>(null);

  const referenceOptions = getWritableCashAccounts(accounts);
  const referenceOptionsAtOpening = getWritableCashAccounts(accounts, form.opened_on);
  const accountName = (id: number | null) =>
    id === null ? "None" : accounts?.find((account) => account.id === id)?.name ?? `#${id}`;
  type AccountSortKey = "name" | "type" | "currency" | "status";
  const accountSort = useTableSort<Account, AccountSortKey>(
    accounts ?? [],
    { key: "name", direction: "asc" },
    (account, key) => {
      if (key === "name") return account.name;
      if (key === "type") return ACCOUNT_TYPE_LABELS[account.type] ?? account.type;
      if (key === "currency") return account.currency;
      return account.is_active;
    }
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name) {
      setError("Account name is required.");
      return;
    }
    if (form.type === "investment" && !form.reference_account_id) {
      setError(
        "Investment accounts require a linked cash account for purchases, sales and income."
      );
      return;
    }
    if (
      form.type === "investment" &&
      !containsSelectedId(referenceOptionsAtOpening, form.reference_account_id)
    ) {
      setError("The linked cash account must be active.");
      return;
    }
    try {
      await createAccount.mutateAsync({
        name: form.name,
        type: form.type as "checking" | "savings" | "investment" | "cash",
        currency: "EUR",
        opening_balance: form.opening_balance as unknown as string,
        opened_on: form.opened_on,
        reference_account_id:
          form.type === "investment" ? Number(form.reference_account_id) : null,
      });
      setForm({
        name: "",
        type: "checking",
        opening_balance: "0",
        opened_on: todayIso(),
        reference_account_id: "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await deleteAccount.mutateAsync(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDeactivate(id: number) {
    setError(null);
    try {
      await deactivateAccount.mutateAsync(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleReactivate(id: number) {
    setError(null);
    try {
      await updateAccount.mutateAsync({ id, data: { is_active: true } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleReferenceChange(accountId: number, referenceAccountId: string) {
    setError(null);
    if (referenceAccountId && !containsSelectedId(referenceOptions, referenceAccountId)) {
      setError("The linked cash account must be active.");
      return;
    }
    try {
      await updateAccount.mutateAsync({
        id: accountId,
        data: { reference_account_id: referenceAccountId ? Number(referenceAccountId) : null },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-3 font-medium">Accounts</h3>
      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap items-end gap-2">
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Account name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.type}
          onChange={(e) => setForm({ ...form, type: e.target.value, reference_account_id: "" })}
        >
          <option value="checking">Checking account</option>
          <option value="savings">Deposit</option>
          <option value="investment">Investment</option>
          <option value="cash">Cash</option>
        </select>
        <input
          type="number"
          step="0.01"
          className="w-40 rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Opening balance"
          value={form.opening_balance}
          onChange={(e) => setForm({ ...form, opening_balance: e.target.value })}
        />
        <label className="flex flex-col gap-0.5 text-[11px] text-gray-500">
          Opening date
          <input
            type="date"
            max={todayIso()}
            className="rounded border border-gray-300 px-2 py-1.5 text-sm text-gray-900"
            value={form.opened_on}
            onChange={(e) => setForm({ ...form, opened_on: e.target.value })}
            required
          />
        </label>
        {form.type === "investment" && (
          <select
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.reference_account_id}
            onChange={(e) => setForm({ ...form, reference_account_id: e.target.value })}
          >
            <option value="">Linked cash account...</option>
            {referenceOptionsAtOpening.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        )}
        <button
          type="submit"
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700"
        >
          Add account
        </button>
      </form>
      {form.type === "investment" && (
        <p className="mb-3 -mt-2 text-xs text-gray-500">
          An investment account never holds cash directly. Purchases, sales and income
          recorded on it move cash through the linked cash account selected here.
        </p>
      )}
      <p className="mb-3 -mt-1 text-xs text-gray-500">
        Accounts are <strong>always in euros</strong>. Record foreign-currency transactions here as well,
        specifying their currency and exchange rate on the transaction itself. The account
        balance remains a single amount in euros.
      </p>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (
        <CollapsibleTable title="Configured accounts" count={accounts?.length ?? 0}>
          <table className="w-full max-w-3xl text-sm">
            <thead className="text-left text-gray-500">
            <tr>
              {([ ["name", "Name"], ["type", "Type"], ["currency", "Currency"] ] as const).map(
                ([key, label]) => (
                  <SortableHeader
                    key={key}
                    active={accountSort.sort.key === key}
                    direction={accountSort.sort.direction}
                    onSort={() => accountSort.requestSort(key)}
                    className="py-1"
                  >
                    {label}
                  </SortableHeader>
                )
              )}
              <th className="py-1">Linked cash account</th>
              <SortableHeader
                active={accountSort.sort.key === "status"}
                direction={accountSort.sort.direction}
                onSort={() => accountSort.requestSort("status")}
                className="py-1"
              >
                Status
              </SortableHeader>
              <th className="py-1"></th>
            </tr>
          </thead>
          <tbody>
            {accountSort.sortedRows.map((a) => (
              <tr key={a.id} className="border-t border-gray-100">
                <td className="py-1.5">{a.name}</td>
                <td className="py-1.5">{ACCOUNT_TYPE_LABELS[a.type] ?? a.type}</td>
                <td className="py-1.5">{a.currency}</td>
                <td className="py-1.5">
                  {a.type === "investment" && a.is_active ? (
                    <select
                      className="rounded border border-gray-300 px-1.5 py-1 text-xs"
                      value={a.reference_account_id ?? ""}
                      onChange={(e) => handleReferenceChange(a.id, e.target.value)}
                    >
                      <option value="">None (blocked)</option>
                      {referenceOptions.map((ref) => (
                        <option key={ref.id} value={ref.id}>
                          {ref.name}
                        </option>
                      ))}
                    </select>
                  ) : a.type === "investment" ? (
                    <span className="text-xs text-gray-500">
                      {accountName(a.reference_account_id)} (historical)
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="py-1.5">
                  <span>{a.is_active ? "Active" : "Inactive"}</span>
                  {a.is_active && a.opened_on && (
                    <span className="block text-[10px] text-gray-400">since {a.opened_on}</span>
                  )}
                  {!a.is_active && a.closed_on && (
                    <span className="block text-[10px] text-gray-400">closed on {a.closed_on}</span>
                  )}
                </td>
                <td className="py-1.5 text-right">
                  <div className="flex justify-end gap-2">
                    {a.is_active ? (
                      <button
                        onClick={() => handleDeactivate(a.id)}
                        disabled={deactivateAccount.isPending}
                        className="text-xs text-gray-400 hover:text-gray-700"
                      >
                        Deactivate
                      </button>
                    ) : (
                      <button
                        onClick={() => handleReactivate(a.id)}
                        disabled={updateAccount.isPending}
                        className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-50"
                      >
                        Reactivate
                      </button>
                    )}
                    <button
                      onClick={() =>
                        confirm(`Permanently delete account '${a.name}'?`, () =>
                          handleDelete(a.id)
                        )
                      }
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
          </table>
        </CollapsibleTable>
      )}
      {dialog}
    </section>
  );
}

function CategoriesSection() {
  const { data: categories, isLoading, error: queryError } = useCategories();
  const createCategory = useCreateCategory();
  const deleteCategory = useDeleteCategory();
  const { confirm, dialog } = useConfirmDialog();
  const [form, setForm] = useState({ name: "", type: "expense", parent_id: "" });
  const [error, setError] = useState<string | null>(null);

  const topLevelCategories = categories?.filter((c) => c.parent_id === null) ?? [];
  const childrenByParent = new Map<number, typeof topLevelCategories>();
  categories?.forEach((c) => {
    if (c.parent_id !== null) {
      childrenByParent.set(c.parent_id, [...(childrenByParent.get(c.parent_id) ?? []), c]);
    }
  });
  const parentOptionsForType = topLevelCategories.filter((c) => c.type === form.type);

  const TYPE_SECTIONS: { type: "income" | "expense" | "transfer"; label: string; accent: string }[] = [
    { type: "income", label: "Inflows", accent: "border-l-green-400" },
    { type: "expense", label: "Outflows", accent: "border-l-red-400" },
    { type: "transfer", label: "Transfers", accent: "border-l-blue-400" },
  ];

  function handleParentChange(parentIdRaw: string) {
    const parent = categories?.find((c) => c.id === Number(parentIdRaw));
    setForm({ ...form, parent_id: parentIdRaw, type: parent ? parent.type : form.type });
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name) {
      setError("Category name is required.");
      return;
    }
    try {
      await createCategory.mutateAsync({
        name: form.name,
        type: form.type as "income" | "expense" | "transfer",
        parent_id: form.parent_id ? Number(form.parent_id) : null,
      });
      setForm({ name: "", type: "expense", parent_id: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteCategory.mutateAsync(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  function CategoryRow({
    category,
    indent,
    accent,
  }: {
    category: NonNullable<typeof categories>[number];
    indent: boolean;
    accent: string;
  }) {
    return (
      <div
        className={`flex items-center justify-between gap-2 rounded border border-l-4 border-gray-100 bg-gray-50/50 px-2 py-1.5 ${accent} ${
          indent ? "ml-6" : ""
        }`}
      >
        <span className="min-w-0 flex-1 truncate" title={category.name}>
          {indent && <span className="text-gray-300">↳ </span>}
          {category.name}{" "}
          {category.is_system && <span className="text-xs text-gray-400">(system)</span>}
        </span>
        <button
          onClick={() =>
            confirm(`Delete category '${category.name}'?`, () => handleDelete(category.id))
          }
          className="shrink-0 text-xs text-gray-400 hover:text-red-600"
        >
          ✕
        </button>
      </div>
    );
  }

  return (
    <section>
      <h3 className="mb-3 font-medium">Categories</h3>
      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap gap-2">
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Category name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.type}
          onChange={(e) => setForm({ ...form, type: e.target.value })}
          disabled={!!form.parent_id}
        >
          <option value="income">Inflow</option>
          <option value="expense">Outflow</option>
          <option value="transfer">Transfer</option>
        </select>
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.parent_id}
          onChange={(e) => handleParentChange(e.target.value)}
        >
          <option value="">Top-level category</option>
          {parentOptionsForType.map((c) => (
            <option key={c.id} value={c.id}>
              Subcategory of: {c.name}
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700"
        >
          Add category
        </button>
      </form>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <QueryStateNotice isLoading={isLoading} error={queryError} />
      {!isLoading && !queryError && (
        <div className="max-w-2xl space-y-5 text-sm">
          {TYPE_SECTIONS.map((section) => {
            const sectionCategories = topLevelCategories.filter((c) => c.type === section.type);
            return (
              <div key={section.type}>
                <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">
                  {section.label}
                </h4>
                <div className="space-y-1">
                  {sectionCategories.map((c) => (
                    <div key={c.id} className="space-y-1">
                      <CategoryRow category={c} indent={false} accent={section.accent} />
                      {(childrenByParent.get(c.id) ?? []).map((child) => (
                        <CategoryRow key={child.id} category={child} indent accent={section.accent} />
                      ))}
                    </div>
                  ))}
                  {sectionCategories.length === 0 && (
                    <p className="px-2 py-1 text-xs text-gray-400">No categories.</p>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {dialog}
    </section>
  );
}
