import { useEffect, useState } from "react";
import { useAccounts } from "@/api/accounts";
import { useCategories } from "@/api/categories";
import {
  useCreateTransaction,
  useDeleteTransaction,
  useTransactions,
  type SortDir,
  type TransactionSortBy,
} from "@/api/transactions";
import { formatEur, formatMoneyWithEur } from "@/lib/formatters";
import { EUR, needsFxRate } from "@/lib/currency";
import ImportCsvWizard from "@/components/transactions/ImportCsvWizard";
import TransferModal from "@/components/transactions/TransferModal";
import CurrencyFields from "@/components/common/CurrencyFields";
import { useConfirmDialog } from "@/components/common/ConfirmDialog";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SortableHeader from "@/components/common/SortableHeader";
import { todayIso } from "@/lib/dates";
import {
  getAssignableTransactionCategories,
  validateManualTransaction,
} from "@/lib/transactionRules";
import { containsSelectedId, getWritableCashAccounts } from "@/lib/lifecycle";
import { clampPageToTotal } from "@/lib/pagination";

const PAGE_SIZE = 20;

/** Cash Flow page: transactions, entry form and filters. Specification §7.3. */
export default function CashFlow() {
  const [accountFilter, setAccountFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [dateFrom, setDateFrom] = useState<string>("");
  const [dateTo, setDateTo] = useState<string>("");
  const [sortBy, setSortBy] = useState<TransactionSortBy>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(1);
  const [showImportWizard, setShowImportWizard] = useState(false);
  const [showTransferModal, setShowTransferModal] = useState(false);
  const { data: accounts, error: accountsError } = useAccounts();
  const { data: categories, error: categoriesError } = useCategories();
  const { data: txPage, isLoading, error } = useTransactions({
    account_id: accountFilter ? Number(accountFilter) : undefined,
    category_id: categoryFilter ? Number(categoryFilter) : undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    page,
    page_size: PAGE_SIZE,
    sort_by: sortBy,
    sort_dir: sortDir,
  });

  // Two states: clicking the same column reverses the order.
  function handleSort(column: TransactionSortBy) {
    if (sortBy !== column) {
      setSortBy(column);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else setSortDir("asc");
    setPage(1);
  }

  const createTx = useCreateTransaction();
  const deleteTx = useDeleteTransaction();
  const { confirm, dialog } = useConfirmDialog();

  const [form, setForm] = useState({
    account_id: "",
    category_id: "",
    date: todayIso(),
    amount: "",
    currency: EUR,
    fx_rate: "",
    description: "",
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const categoryName = (id: number | null) =>
    categories?.find((c) => c.id === id)?.name ?? "—";
  const accountName = (id: number) => accounts?.find((a) => a.id === id)?.name ?? `#${id}`;
  // Investment accounts hold no cash of their own (specification §5.2)
  // Investment accounts cannot receive manual transactions. Security trades
  // use their reference cash account through the Securities page.
  const historicalCashAccounts = accounts?.filter((a) => a.type !== "investment") ?? [];
  const writableCashAccounts = getWritableCashAccounts(accounts, form.date);
  const assignableCategories = getAssignableTransactionCategories(categories ?? []);
  const incomeCategories = assignableCategories.filter((category) => category.type === "income");
  const expenseCategories = assignableCategories.filter((category) => category.type === "expense");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const validationError = validateManualTransaction({
      accountId: form.account_id,
      categoryId: form.category_id,
      amount: form.amount,
      categories: categories ?? [],
    });
    if (validationError) {
      setFormError(validationError);
      return;
    }
    if (!containsSelectedId(writableCashAccounts, form.account_id)) {
      setFormError("The selected account is inactive or cannot receive manual transactions.");
      return;
    }
    if (needsFxRate(form.currency) && !form.fx_rate) {
      setFormError(`Enter the exchange rate: euro value of 1 ${form.currency} on the transaction date.`);
      return;
    }
    try {
      await createTx.mutateAsync({
        account_id: Number(form.account_id),
        category_id: Number(form.category_id),
        date: form.date,
        amount: form.amount as unknown as string,
        currency: form.currency,
        fx_rate: needsFxRate(form.currency) ? form.fx_rate : null,
        description: form.description || null,
      });
      setForm({ ...form, amount: "", description: "" });
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleDelete(id: number) {
    setDeleteError(null);
    try {
      await deleteTx.mutateAsync(id);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  const totalPages = txPage ? Math.max(1, Math.ceil(txPage.total / PAGE_SIZE)) : 1;

  // Deletion can remove one row or both sides of a transfer. If the last
  // page disappears, immediately load the last valid page instead of
  // displaying a page number greater than the page count.
  useEffect(() => {
    if (!txPage) return;
    const validPage = clampPageToTotal(page, txPage.total, PAGE_SIZE);
    if (validPage !== page) setPage(validPage);
  }, [page, txPage]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Cash Flow</h2>
        <div className="flex gap-2">
          <button
            onClick={() => setShowTransferModal(true)}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            🔁 Transfer
          </button>
          <button
            onClick={() => setShowImportWizard(true)}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            📥 Import CSV
          </button>
        </div>
      </div>

      {showImportWizard && <ImportCsvWizard onClose={() => setShowImportWizard(false)} />}
      {showTransferModal && <TransferModal onClose={() => setShowTransferModal(false)} />}

      <form
        onSubmit={handleSubmit}
        className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-6"
      >
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.account_id}
          onChange={(e) => setForm({ ...form, account_id: e.target.value })}
        >
          <option value="">Account...</option>
          {writableCashAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.category_id}
          onChange={(e) => setForm({ ...form, category_id: e.target.value })}
          required
        >
          <option value="">Required category...</option>
          {incomeCategories.length > 0 && (
            <optgroup label="Inflows (+)">
              {incomeCategories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </optgroup>
          )}
          {expenseCategories.length > 0 && (
            <optgroup label="Outflows (-)">
              {expenseCategories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
        <input
          type="date"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.date}
          onChange={(e) => setForm({ ...form, date: e.target.value })}
        />
        <input
          type="number"
          step="0.01"
          placeholder="Amount (+ inflow / - outflow)"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={form.amount}
          onChange={(e) => setForm({ ...form, amount: e.target.value })}
          required
        />
        <input
          type="text"
          placeholder="Description"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm md:col-span-1"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <button
          type="submit"
          disabled={createTx.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createTx.isPending ? "Saving..." : "Add"}
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
        {formError && <p className="col-span-full text-sm text-red-600">{formError}</p>}
      </form>

      <div className="flex gap-3">
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={accountFilter}
          onChange={(e) => {
            setAccountFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All accounts</option>
          {historicalCashAccounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}{a.is_active ? "" : " (inactive)"}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          value={categoryFilter}
          onChange={(e) => {
            setCategoryFilter(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All categories</option>
          {categories?.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-gray-500">
          From
          <input
            type="date"
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={dateFrom}
            onChange={(e) => {
              setDateFrom(e.target.value);
              setPage(1);
            }}
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-gray-500">
          To
          <input
            type="date"
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={dateTo}
            onChange={(e) => {
              setDateTo(e.target.value);
              setPage(1);
            }}
          />
        </label>
        {(dateFrom || dateTo) && (
          <button
            onClick={() => {
              setDateFrom("");
              setDateTo("");
              setPage(1);
            }}
            className="text-xs text-gray-400 hover:underline"
          >
            Clear period
          </button>
        )}
      </div>

      <QueryStateNotice
        isLoading={isLoading}
        error={error ?? accountsError ?? categoriesError}
      />
      {deleteError && <p className="text-sm text-red-600">{deleteError}</p>}
      {txPage && (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([ 
                  ["date", "Date", "left"],
                  ["account_id", "Account", "left"],
                  ["category_id", "Category", "left"],
                  ["description", "Description", "left"],
                  ["amount", "Amount", "right"],
                ] as const).map(([column, label, align]) => (
                  <SortableHeader
                    key={column}
                    active={sortBy === column}
                    direction={sortDir}
                    onSort={() => handleSort(column)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
                <th scope="col" className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {txPage.items.map((t) => (
                <tr key={t.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">{t.date}</td>
                  <td className="px-3 py-2">{accountName(t.account_id)}</td>
                  <td className="px-3 py-2">
                    {categoryName(t.category_id)}
                    {t.transfer_group_id && (
                      <span className="ml-1 text-xs text-gray-400" title="Transfer between accounts">
                        🔁
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2">{t.description ?? "—"}</td>
                  <td
                    className={`px-3 py-2 text-right font-medium ${
                      Number(t.amount_eur) >= 0 ? "text-green-600" : "text-red-600"
                    }`}
                    title={`Applied exchange rate: ${t.fx_rate}`}
                  >
                    {formatMoneyWithEur(Number(t.amount), t.currency, Number(t.amount_eur))}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {/* Transactions generated by another operation are managed at their
                        source. Offer deletion only for directly editable transactions. */}
                    {t.trade_id ? (
                      <span className="text-xs text-gray-400" title="Generated by a securities trade">
                        Managed in Securities
                      </span>
                    ) : t.income_event_id ? (
                      <span className="text-xs text-gray-400" title="Generated by a coupon/dividend">
                        Managed in Income
                      </span>
                    ) : t.portfolio_cost_id ? (
                      <span className="text-xs text-gray-400" title="Generated by a recurring portfolio cost">
                        Managed in Securities
                      </span>
                    ) : (
                      <button
                        onClick={() =>
                          confirm(
                            t.transfer_group_id
                              ? `Delete the transfer on ${t.date} (${formatEur(Number(t.amount_eur))})? The linked transaction in the other account will also be deleted.`
                              : `Delete the transaction on ${t.date} (${formatEur(Number(t.amount_eur))})?`,
                            () => handleDelete(t.id)
                          )
                        }
                        className="text-xs text-gray-400 hover:text-red-600"
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {txPage.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-gray-400">
                    No transactions found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="flex items-center justify-between border-t border-gray-100 px-3 py-2 text-xs text-gray-500">
            <span>
              Page {page} of {totalPages} — {txPage.total} total transactions
            </span>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
      {dialog}
    </div>
  );
}
