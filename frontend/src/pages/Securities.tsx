import { useState } from "react";
import { useAccounts } from "@/api/accounts";
import {
  useCreateSecurity,
  useDeleteSecurity,
  useSecurities,
  useUpdateSecurity,
} from "@/api/securities";
import { useCreateTrade, useDeleteTrade, useTrades } from "@/api/trades";
import { useAddPrice, useLatestPrices, type Price } from "@/api/prices";
import {
  PORTFOLIO_COST_TYPES,
  portfolioCostTypeLabel,
  useCreatePortfolioCost,
  useDeletePortfolioCost,
  usePortfolioCosts,
  type PortfolioCost,
} from "@/api/portfolioCosts";
import type { Security, Trade } from "@/api/types";
import { formatEur, formatMoney, formatMoneyWithEur } from "@/lib/formatters";
import { EUR, needsFxRate, needsSeparateQuotePrice } from "@/lib/currency";
import CurrencyFields from "@/components/common/CurrencyFields";
import {
  SECURITY_TYPE_OPTIONS,
  securityTypeLabel,
  type SecurityType,
} from "@/lib/securityTypes";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import TradeCostsModal from "@/components/transactions/TradeCostsModal";
import PriceImportWizard from "@/components/securities/PriceImportWizard";
import { calendarDaysSince, todayIso } from "@/lib/dates";
import {
  containsSelectedId,
  getWritableInvestmentAccounts,
  getWritableSecurities,
} from "@/lib/lifecycle";
import { useTableSort } from "@/lib/useTableSort";

const STALE_PRICE_DAYS = 7;

/** Securities page: security records, prices and purchase/sale history.
 * Current quantities and valuations are on Portfolio.
 * Specification §5.2, §6.3 and §6.4. */
export default function Securities() {
  return (
    <div className="space-y-8">
      <h2 className="text-xl font-semibold">Securities</h2>
      <SecuritiesRegistrySection />
      <PricesSection />
      <TradesSection />
      <RecurringCostsSection />
    </div>
  );
}

function PricesSection() {
  const {
    data: securities,
    isLoading: securitiesLoading,
    error: securitiesError,
  } = useSecurities();
  const { data: latestPrices, isLoading: pricesLoading, error: pricesError } = useLatestPrices();
  const [showImport, setShowImport] = useState(false);
  const latestBySecurity = new Map(
    (latestPrices ?? []).map((price) => [price.security_id, price] as const)
  );
  const priceRows = (securities ?? []).map((security) => ({
    security,
    price: latestBySecurity.get(security.id),
  }));
  type PriceSortKey = "security" | "price" | "date";
  const priceSort = useTableSort(priceRows, { key: "security" as PriceSortKey, direction: "asc" },
    (row, key) => {
      if (key === "security") return `${row.security.ticker} ${row.security.name}`;
      if (key === "price") return row.price ? Number(row.price.price_close_eur) : null;
      return row.price?.date;
    }
  );

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-medium">Prices</h3>
        <button
          onClick={() => setShowImport(true)}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
        >
          📥 Import CSV
        </button>
      </div>
      <p className="mb-3 text-xs text-gray-500">
        Net worth always uses the latest available price for each security, even if it is
        old. The date is always shown, with a warning if it is older than{" "}
        {STALE_PRICE_DAYS} days.
      </p>
      <QueryStateNotice
        isLoading={securitiesLoading || pricesLoading}
        error={securitiesError ?? pricesError}
      />
      {!securitiesLoading && !pricesLoading && !securitiesError && !pricesError && (
        <CollapsibleTable title="Latest prices" count={securities?.length ?? 0}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["security", "Security", "left"],
                  ["price", "Latest price", "right"],
                  ["date", "Date", "left"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={priceSort.sort.key === key}
                    direction={priceSort.sort.direction}
                    onSort={() => priceSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th className="px-3 py-2">Update</th>
              </tr>
            </thead>
            <tbody>
              {priceSort.sortedRows.map(({ security, price }) => (
                <PriceRow key={security.id} security={security} price={price} />
              ))}
              {securities?.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-gray-400">
                    No securities registered.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {showImport && <PriceImportWizard onClose={() => setShowImport(false)} />}
    </section>
  );
}

function PriceRow({ security, price }: { security: Security; price: Price | undefined }) {
  const addPrice = useAddPrice();
  // A price always uses the security currency; it cannot be selected.
  const foreign = needsFxRate(security.currency);
  const [form, setForm] = useState({
    date: todayIso(),
    price_close: "",
    fx_rate: "",
  });
  const [error, setError] = useState<string | null>(null);

  const daysSince = price ? calendarDaysSince(price.date) : null;
  const isStale = daysSince !== null && daysSince > STALE_PRICE_DAYS;

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.price_close) {
      setError("Price is required.");
      return;
    }
    if (foreign && !form.fx_rate) {
      setError(`Enter the exchange rate: euro value of 1 ${security.currency} on that date.`);
      return;
    }
    try {
      await addPrice.mutateAsync({
        security_id: security.id,
        date: form.date,
        price_close: form.price_close,
        fx_rate: foreign ? form.fx_rate : null,
      });
      setForm({ ...form, price_close: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <tr className="border-t border-gray-100">
      <td className="px-3 py-2 font-medium">
        {security.ticker}
        {!security.is_active && (
          <span className="ml-1.5 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-normal text-gray-500">
            inactive
          </span>
        )}
        {foreign && (
          <span className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-normal text-amber-700">
            {security.currency}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-right">
        {price
          ? formatMoneyWithEur(
              Number(price.price_close),
              security.currency,
              Number(price.price_close_eur)
            )
          : "—"}
      </td>
      <td className="px-3 py-2">
        {price ? (
          <span className={isStale ? "text-amber-600" : "text-gray-500"}>
            {price.date}
            {isStale && ` — ⚠ ${daysSince} days ago`}
          </span>
        ) : (
          <span className="text-gray-400">no price</span>
        )}
      </td>
      <td className="px-3 py-2">
        {security.is_active ? (
        <form onSubmit={handleAdd} className="flex items-center gap-1">
          <input
            type="date"
            className="rounded border border-gray-300 px-1.5 py-1 text-xs"
            value={form.date}
            onChange={(e) => setForm({ ...form, date: e.target.value })}
          />
          <input
            type="number"
            step="0.0001"
            placeholder="Price"
            className="w-20 rounded border border-gray-300 px-1.5 py-1 text-xs"
            value={form.price_close}
            onChange={(e) => setForm({ ...form, price_close: e.target.value })}
          />
          {foreign && (
            <input
              type="number"
              step="0.00000001"
              placeholder={`1 ${security.currency} = ? €`}
              title={`Exchange rate on the price date: how many euros 1 ${security.currency}`}
              className="w-28 rounded border border-gray-300 px-1.5 py-1 text-xs"
              value={form.fx_rate}
              onChange={(e) => setForm({ ...form, fx_rate: e.target.value })}
            />
          )}
          <button
            type="submit"
            disabled={addPrice.isPending}
            className="rounded border border-gray-300 px-2 py-1 text-xs hover:bg-gray-50 disabled:opacity-50"
          >
            Save
          </button>
        </form>
        ) : (
          <span className="text-xs text-gray-400">Read-only history</span>
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
      </td>
    </tr>
  );
}

/**
 * Recurring portfolio costs (specification §11.5): stamp duty, custody
 * and account fees. Like trades and income, each cost creates a cash outflow
 * on the linked cash account, so it is recorded here, outside Cash Flow.
 */
function RecurringCostsSection() {
  const { data: costs, isLoading, error: costsError } = usePortfolioCosts();
  const { data: accounts, error: accountsError } = useAccounts();
  const createCost = useCreatePortfolioCost();
  const deleteCost = useDeletePortfolioCost();
  const { confirm, dialog } = useConfirmDialog();

  const accountName = (id: number) => accounts?.find((a) => a.id === id)?.name ?? `#${id}`;
  type CostSortKey = "date" | "type" | "description" | "account" | "amount";
  const costSort = useTableSort<PortfolioCost, CostSortKey>(
    costs ?? [],
    { key: "date", direction: "desc" },
    (cost, key) => {
      if (key === "date") return cost.date;
      if (key === "type") return portfolioCostTypeLabel(cost.cost_type);
      if (key === "description") return cost.description;
      if (key === "account") return accountName(cost.account_id);
      return Number(cost.amount_eur);
    }
  );

  const [form, setForm] = useState({
    date: todayIso(),
    cost_type: "custody_fee",
    account_id: "",
    amount: "",
    currency: EUR,
    fx_rate: "",
    description: "",
  });
  const [error, setError] = useState<string | null>(null);
  const investmentAccounts = getWritableInvestmentAccounts(accounts, form.date);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.account_id || !form.amount) {
      setError("Account and amount are required.");
      return;
    }
    if (!containsSelectedId(investmentAccounts, form.account_id)) {
      setError("Select an active investment account.");
      return;
    }
    if (needsFxRate(form.currency) && !form.fx_rate) {
      setError(`Enter the exchange rate: euro value of 1 ${form.currency} on the cost date.`);
      return;
    }
    try {
      await createCost.mutateAsync({
        date: form.date,
        cost_type: form.cost_type,
        account_id: Number(form.account_id),
        amount: form.amount,
        currency: form.currency,
        fx_rate: needsFxRate(form.currency) ? form.fx_rate : null,
        description: form.description || null,
      });
      setForm({ ...form, amount: "", description: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-3 font-medium">Recurring costs</h3>
      <p className="mb-3 text-xs text-gray-500">
        Stamp duty, custody fees and account fees apply to the portfolio as a whole,
        rather than an individual trade. Each cost automatically creates an outflow on
        the linked cash account, so do not also record it in Cash Flow.
      </p>

      <form
        onSubmit={handleCreate}
        className="mb-4 grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-5"
      >
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Date
          <input
            type="date"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.date}
            onChange={(e) => setForm({ ...form, date: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Type
          <select
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.cost_type}
            onChange={(e) => setForm({ ...form, cost_type: e.target.value })}
          >
            {PORTFOLIO_COST_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
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
            <option value="">Account...</option>
            {investmentAccounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Amount
          <input
            type="number"
            step="0.01"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Description (optional)
          <input
            type="text"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
        </label>
        <button
          type="submit"
          disabled={createCost.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createCost.isPending ? "Saving..." : "Record cost"}
        </button>
        <CurrencyFields
          className="col-span-full border-t border-gray-100 pt-3"
          currency={form.currency}
          fxRate={form.fx_rate}
          onChange={({ currency, fxRate }) =>
            setForm((f) => ({ ...f, currency, fx_rate: fxRate }))
          }
          date={form.date}
          amount={form.amount}
        />
        {error && <p className="col-span-full text-sm text-red-600">{error}</p>}
      </form>

      {investmentAccounts.length === 0 && (
        <p className="mb-4 text-xs text-gray-500">
          No investment accounts configured. Create one in Settings with a linked cash
          account before recording a cost.
        </p>
      )}

      <QueryStateNotice isLoading={isLoading} error={costsError ?? accountsError} />

      {costs && (
        <CollapsibleTable title="Recorded recurring costs" count={costs.length}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Date", "left"],
                  ["type", "Type", "left"],
                  ["description", "Description", "left"],
                  ["account", "Account", "left"],
                  ["amount", "Amount", "right"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={costSort.sort.key === key}
                    direction={costSort.sort.direction}
                    onSort={() => costSort.requestSort(key)}
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
              {costSort.sortedRows.map((c) => (
                <tr key={c.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">{c.date}</td>
                  <td className="px-3 py-2">{portfolioCostTypeLabel(c.cost_type)}</td>
                  <td className="px-3 py-2 text-gray-500">{c.description ?? "—"}</td>
                  <td className="px-3 py-2">{accountName(c.account_id)}</td>
                  <td className="px-3 py-2 text-right font-medium text-red-600">
                    {formatMoneyWithEur(Number(c.amount), c.currency, Number(c.amount_eur))}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() =>
                        confirm(
                          `Delete the cost dated ${c.date} (${formatEur(Number(c.amount_eur))})? The linked cash outflow will also be removed.`,
                          () => deleteCost.mutate(c.id)
                        )
                      }
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {costs.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-gray-400">
                    No recurring costs recorded.
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

function SecuritiesRegistrySection() {
  const { data: securities, isLoading, error: securitiesError } = useSecurities();
  const createSecurity = useCreateSecurity();
  const updateSecurity = useUpdateSecurity();
  const deleteSecurity = useDeleteSecurity();
  const { confirm, dialog } = useConfirmDialog();
  const emptyForm = {
    ticker: "",
    name: "",
    type: "stock",
    currency: "EUR",
    isin: "",
    sector: "",
    industry: "",
    country: "",
  };
  const [form, setForm] = useState(emptyForm);
  const [editingSecurity, setEditingSecurity] = useState<Security | null>(null);
  const [classification, setClassification] = useState({ sector: "", industry: "", country: "" });
  const [error, setError] = useState<string | null>(null);
  type SecuritySortKey =
    | "ticker"
    | "name"
    | "isin"
    | "type"
    | "currency"
    | "sector"
    | "industry"
    | "country"
    | "status";
  const securitySort = useTableSort<Security, SecuritySortKey>(
    securities ?? [],
    { key: "ticker", direction: "asc" },
    (security, key) => {
      if (key === "ticker") return security.ticker;
      if (key === "name") return security.name;
      if (key === "isin") return security.isin;
      if (key === "type") return securityTypeLabel(security.type);
      if (key === "currency") return security.currency;
      if (key === "sector") return security.sector;
      if (key === "industry") return security.industry;
      if (key === "country") return security.country;
      return security.is_active;
    }
  );

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.ticker || !form.name) {
      setError("Ticker and name are required.");
      return;
    }
    try {
      await createSecurity.mutateAsync({
        ticker: form.ticker,
        name: form.name,
        type: form.type as SecurityType,
        currency: form.currency,
        isin: form.isin || null,
        sector: form.sector.trim() || null,
        industry: form.industry.trim() || null,
        country: form.country.trim() || null,
      });
      setForm(emptyForm);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete(id: number) {
    setError(null);
    try {
      await deleteSecurity.mutateAsync(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleActivityChange(id: number, isActive: boolean) {
    setError(null);
    try {
      await updateSecurity.mutateAsync({ id, data: { is_active: isActive } });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  function beginClassificationEdit(security: Security) {
    setEditingSecurity(security);
    setClassification({
      sector: security.sector ?? "",
      industry: security.industry ?? "",
      country: security.country ?? "",
    });
  }

  async function handleClassificationSave(e: React.FormEvent) {
    e.preventDefault();
    if (!editingSecurity) return;
    setError(null);
    try {
      await updateSecurity.mutateAsync({
        id: editingSecurity.id,
        data: {
          sector: classification.sector.trim() || null,
          industry: classification.industry.trim() || null,
          country: classification.country.trim() || null,
        },
      });
      setEditingSecurity(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <section>
      <h3 className="mb-3 font-medium">Security records</h3>
      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap items-end gap-2">
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Ticker (e.g. ENI.MI)"
          value={form.ticker}
          onChange={(e) => setForm({ ...form, ticker: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.type}
          onChange={(e) => setForm({ ...form, type: e.target.value })}
        >
          {SECURITY_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <input
          className="w-20 rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Currency"
          value={form.currency}
          onChange={(e) => setForm({ ...form, currency: e.target.value })}
        />
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="ISIN (optional)"
          value={form.isin}
          onChange={(e) => setForm({ ...form, isin: e.target.value })}
        />
        <input
          maxLength={100}
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Sector (optional)"
          value={form.sector}
          onChange={(e) => setForm({ ...form, sector: e.target.value })}
        />
        <input
          maxLength={120}
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Industry (optional)"
          value={form.industry}
          onChange={(e) => setForm({ ...form, industry: e.target.value })}
        />
        <input
          maxLength={60}
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Country (optional)"
          value={form.country}
          onChange={(e) => setForm({ ...form, country: e.target.value })}
        />
        <button
          type="submit"
          disabled={createSecurity.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          Add security
        </button>
      </form>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}

      <QueryStateNotice isLoading={isLoading} error={securitiesError} />
      {!isLoading && !securitiesError && (
        <CollapsibleTable title="Registered securities" count={securities?.length ?? 0}>
          <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["ticker", "Ticker"],
                  ["name", "Name"],
                  ["isin", "ISIN"],
                  ["type", "Type"],
                  ["currency", "Currency"],
                  ["sector", "Sector"],
                  ["industry", "Industry"],
                  ["country", "Country"],
                  ["status", "Status"],
                ] as const).map(([key, label]) => (
                  <SortableHeader
                    key={key}
                    active={securitySort.sort.key === key}
                    direction={securitySort.sort.direction}
                    onSort={() => securitySort.requestSort(key)}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {securitySort.sortedRows.map((s) => (
                <tr key={s.id} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium">{s.ticker}</td>
                  <td className="px-3 py-2">{s.name}</td>
                  <td className="px-3 py-2 text-xs text-gray-500">{s.isin ?? "—"}</td>
                  <td className="px-3 py-2">{securityTypeLabel(s.type)}</td>
                  <td className="px-3 py-2">{s.currency}</td>
                  <td className="px-3 py-2">{s.sector ?? "—"}</td>
                  <td className="px-3 py-2">{s.industry ?? "—"}</td>
                  <td className="px-3 py-2">{s.country ?? "—"}</td>
                  <td className="px-3 py-2">{s.is_active ? "Active" : "Inactive"}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => beginClassificationEdit(s)}
                        className="text-xs text-gray-400 hover:text-gray-700"
                      >
                        Classify
                      </button>
                      <button
                        onClick={() => handleActivityChange(s.id, !s.is_active)}
                        disabled={updateSecurity.isPending}
                        className="text-xs text-gray-400 hover:text-gray-700 disabled:opacity-50"
                      >
                        {s.is_active ? "Deactivate" : "Reactivate"}
                      </button>
                      <button
                        onClick={() =>
                          confirm(`Delete security '${s.ticker}' from the registry?`, () =>
                            handleDelete(s.id)
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
              {securities?.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-6 text-center text-gray-400">
                    No securities registered.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {editingSecurity && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <form
            onSubmit={handleClassificationSave}
            className="w-full max-w-md space-y-4 rounded-lg bg-white p-5 shadow-xl"
          >
            <div>
              <h4 className="font-medium">Classification {editingSecurity.ticker}</h4>
              <p className="mt-1 text-xs text-gray-500">
                Free-form descriptive fields. For ETFs, these indicate the summary
                classification chosen for the security, rather than weighted exposure to holdings.
              </p>
            </div>
            {(["sector", "industry", "country"] as const).map((field) => (
              <label key={field} className="flex flex-col gap-1 text-xs text-gray-500">
                {field === "sector" ? "Sector" : field === "industry" ? "Industry" : "Country"}
                <input
                  maxLength={field === "sector" ? 100 : field === "industry" ? 120 : 60}
                  className="rounded border border-gray-300 px-2 py-1.5 text-sm"
                  value={classification[field]}
                  onChange={(event) =>
                    setClassification({ ...classification, [field]: event.target.value })
                  }
                />
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditingSecurity(null)}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={updateSecurity.isPending}
                className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {updateSecurity.isPending ? "Saving..." : "Save"}
              </button>
            </div>
          </form>
        </div>
      )}
      {dialog}
    </section>
  );
}

function TradesSection() {
  const { data: securities, error: securitiesError } = useSecurities();
  const { data: accounts, error: accountsError } = useAccounts();
  const { data: trades, isLoading, error } = useTrades();
  const createTrade = useCreateTrade();
  const deleteTrade = useDeleteTrade();
  const { confirm, dialog } = useConfirmDialog();
  const [costsModalTrade, setCostsModalTrade] = useState<{
    id: number;
    label: string;
    totalAmount: string;
    currency: string;
    fxRate: string;
    date: string;
    securityId: number;
    accountId: number;
  } | null>(null);
  // Trades can only be recorded on investment accounts (specification §5.2):
  // cash always moves through their linked cash account, never the investment account.
  const activeSecurities = getWritableSecurities(securities);

  const [form, setForm] = useState({
    security_id: "",
    account_id: "",
    type: "buy",
    date: todayIso(),
    quantity: "",
    price: "",
    quote_price: "",
    currency: EUR,
    fx_rate: "",
  });
  const [formError, setFormError] = useState<string | null>(null);
  const investmentAccounts = getWritableInvestmentAccounts(accounts, form.date);
  const selectedSecurity = activeSecurities.find(
    (security) => String(security.id) === form.security_id
  );
  const quotePriceRequired = needsSeparateQuotePrice(
    form.currency,
    selectedSecurity?.currency
  );

  /**
   * Selecting a security aligns the currency with its quote currency, which
   * is the most common case. It remains editable because the trade uses the
   * SETTLEMENT currency, which may differ: a US security bought on a European
   * market may settle in euros.
   */
  function handleSecurityChange(security_id: string) {
    const security = activeSecurities?.find((s) => String(s.id) === security_id);
    setForm({
      ...form,
      security_id,
      currency: security?.currency ?? form.currency,
      fx_rate: "",
      quote_price: "",
    });
  }

  const securityLabel = (id: number) => {
    const s = securities?.find((sec) => sec.id === id);
    return s ? `${s.ticker}${s.isin ? ` (${s.isin})` : ""}` : `#${id}`;
  };
  const accountName = (id: number) => accounts?.find((a) => a.id === id)?.name ?? `#${id}`;
  const securityCurrency = (id: number) =>
    securities?.find((security) => security.id === id)?.currency ?? EUR;

  async function handleTrade(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!form.security_id || !form.account_id || !form.quantity || !form.price) {
      setFormError("Security, account, quantity and price are required.");
      return;
    }
    if (
      !containsSelectedId(activeSecurities, form.security_id) ||
      !containsSelectedId(investmentAccounts, form.account_id)
    ) {
      setFormError("Security and investment account must be active.");
      return;
    }
    if (needsFxRate(form.currency) && !form.fx_rate) {
      setFormError(`Enter the exchange rate: euro value of 1 ${form.currency} on the trade date.`);
      return;
    }
    if (
      quotePriceRequired &&
      (!form.quote_price || !Number.isFinite(Number(form.quote_price)) || Number(form.quote_price) <= 0)
    ) {
      setFormError(
        `Enter the positive quote price in ${selectedSecurity?.currency}.`
      );
      return;
    }
    try {
      await createTrade.mutateAsync({
        security_id: Number(form.security_id),
        account_id: Number(form.account_id),
        type: form.type,
        date: form.date,
        quantity: form.quantity,
        price: form.price,
        quote_price: quotePriceRequired ? form.quote_price : undefined,
        currency: form.currency,
        fx_rate: needsFxRate(form.currency) ? form.fx_rate : null,
      });
      setForm({ ...form, quantity: "", price: "", quote_price: "" });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  type TradeSortKey = "date" | "security" | "type" | "quantity" | "price" | "total" | "costs" | "account";
  const tradeSort = useTableSort<Trade, TradeSortKey>(
    trades ?? [],
    { key: "date", direction: "desc" },
    (trade, key) => {
      if (key === "date") return trade.date;
      if (key === "security") return securityLabel(trade.security_id);
      if (key === "type") return trade.type === "buy" ? "Purchase" : "Sale";
      if (key === "quantity") return Number(trade.quantity);
      if (key === "price") return Number(trade.price);
      if (key === "total") return Number(trade.total_eur);
      if (key === "costs") return Number(trade.total_costs_eur);
      return accountName(trade.account_id);
    }
  );

  return (
    <section>
      <h3 className="mb-3 font-medium">Trades (purchases/sales)</h3>

      <form
        onSubmit={handleTrade}
        className="mb-4 flex flex-wrap items-end gap-2 rounded-lg border border-gray-200 bg-white p-4"
      >
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.security_id}
          onChange={(e) => handleSecurityChange(e.target.value)}
        >
          <option value="">Security...</option>
          {activeSecurities.map((s) => (
            <option key={s.id} value={s.id}>
              {s.ticker}
              {s.currency !== EUR ? ` (${s.currency})` : ""}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
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
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.type}
          onChange={(e) => setForm({ ...form, type: e.target.value })}
        >
          <option value="buy">Purchase</option>
          <option value="sell">Sale</option>
        </select>
        <input
          type="date"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.date}
          onChange={(e) => setForm({ ...form, date: e.target.value })}
        />
        <input
          type="number"
          step="0.000001"
          placeholder="Quantity"
          className="w-28 rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.quantity}
          onChange={(e) => setForm({ ...form, quantity: e.target.value })}
        />
        <label className="flex flex-col gap-1 text-xs text-gray-500">
          Settlement price ({form.currency})
          <input
            type="number"
            min="0"
            step="0.000001"
            className="w-36 rounded border border-gray-300 px-2 py-1.5 text-sm text-gray-900"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
          />
        </label>
        {quotePriceRequired && selectedSecurity && (
          <label className="flex flex-col gap-1 text-xs text-gray-500">
            Quote price ({selectedSecurity.currency})
            <input
              type="number"
              min="0"
              step="0.000001"
              className="w-36 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-sm text-gray-900"
              value={form.quote_price}
              onChange={(e) => setForm({ ...form, quote_price: e.target.value })}
              required
            />
          </label>
        )}
        <button
          type="submit"
          disabled={createTrade.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createTrade.isPending ? "Saving..." : "Record"}
        </button>
        <CurrencyFields
          className="w-full border-t border-gray-100 pt-3"
          currency={form.currency}
          fxRate={form.fx_rate}
          onChange={({ currency, fxRate }) =>
            setForm((f) => ({
              ...f,
              currency,
              fx_rate: fxRate,
              quote_price: needsSeparateQuotePrice(currency, selectedSecurity?.currency)
                ? f.quote_price
                : "",
            }))
          }
          date={form.date}
          amount={
            form.quantity && form.price
              ? String(Number(form.quantity) * Number(form.price))
              : ""
          }
        />
        {formError && <p className="w-full text-sm text-red-600">{formError}</p>}
      </form>
      {investmentAccounts.length === 0 && (
        <p className="mb-4 text-xs text-gray-500">
          No investment accounts configured. Create one in Settings with a linked cash
          account before recording a trade.
        </p>
      )}

      <QueryStateNotice
        isLoading={isLoading}
        error={error ?? securitiesError ?? accountsError}
      />

      {trades && (
        <CollapsibleTable title="Recorded trades" count={trades.length}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Date", "left"],
                  ["security", "Security", "left"],
                  ["type", "Type", "left"],
                  ["quantity", "Quantity", "right"],
                  ["price", "Price", "right"],
                  ["total", "Total", "right"],
                  ["costs", "Costs", "right"],
                  ["account", "Account", "left"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={tradeSort.sort.key === key}
                    direction={tradeSort.sort.direction}
                    onSort={() => tradeSort.requestSort(key)}
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
              {tradeSort.sortedRows.map((t) => (
                <tr key={t.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">{t.date}</td>
                  <td className="px-3 py-2">{securityLabel(t.security_id)}</td>
                  <td className={`px-3 py-2 ${t.type === "buy" ? "text-green-600" : "text-red-600"}`}>
                    {t.type === "buy" ? "Purchase" : "Sale"}
                  </td>
                  <td className="px-3 py-2 text-right">{Number(t.quantity).toLocaleString("it-IT")}</td>
                  {/* price moves cash in the settlement currency; quote_price updates
                      price history in the native security currency and is shown when
                      the two currencies differ. */}
                  <td className="px-3 py-2 text-right">
                    <div>{formatMoney(Number(t.price), t.currency)}</div>
                    {needsSeparateQuotePrice(t.currency, securityCurrency(t.security_id)) && (
                      <div className="text-xs text-gray-400">
                        quote {formatMoney(Number(t.quote_price), securityCurrency(t.security_id))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right" title={`Applied exchange rate: ${t.fx_rate}`}>
                    {formatMoneyWithEur(Number(t.total_amount), t.currency, Number(t.total_eur))}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-500">
                    {Number(t.total_costs_eur) > 0 ? formatEur(Number(t.total_costs_eur)) : "—"}
                  </td>
                  <td className="px-3 py-2">{accountName(t.account_id)}</td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex justify-end gap-3">
                      <button
                        onClick={() =>
                          setCostsModalTrade({
                            id: t.id,
                            label: `${t.type === "buy" ? "Purchase" : "Sale"} ${securityLabel(t.security_id)} on ${t.date}`,
                            totalAmount: t.total_amount,
                            currency: t.currency,
                            fxRate: t.fx_rate,
                            date: t.date,
                            securityId: t.security_id,
                            accountId: t.account_id,
                          })
                        }
                        className="text-xs text-gray-400 hover:text-gray-700"
                      >
                        Costs
                      </button>
                      <button
                        onClick={() =>
                          confirm(
                            `Delete the ${t.type === "buy" ? "purchase" : "sale"} on ${t.date} (${securityLabel(t.security_id)})?`,
                            () => deleteTrade.mutate(t.id)
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
              {tradeSort.sortedRows.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-gray-400">
                    No trades recorded.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      )}
      {dialog}
      {costsModalTrade && (
        <TradeCostsModal
          tradeId={costsModalTrade.id}
          tradeLabel={costsModalTrade.label}
          tradeTotalAmount={costsModalTrade.totalAmount}
          tradeCurrency={costsModalTrade.currency}
          tradeFxRate={costsModalTrade.fxRate}
          tradeDate={costsModalTrade.date}
          allowAdd={
            containsSelectedId(activeSecurities, String(costsModalTrade.securityId)) &&
            containsSelectedId(
              getWritableInvestmentAccounts(accounts, costsModalTrade.date),
              String(costsModalTrade.accountId)
            )
          }
          onClose={() => setCostsModalTrade(null)}
        />
      )}
    </section>
  );
}
