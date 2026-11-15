import type { NetWorthAccountComposition, NetWorthReport } from "@/api/reports";
import { formatEur } from "@/lib/formatters";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";

const ISSUE_LABELS: Record<NetWorthAccountComposition["issues"][number]["reason"], string> = {
  negative_quantity: "Recorded sales exceed purchases in this account.",
  account_not_present: "Holdings fall outside the account’s opening or closing dates.",
  not_investment_account: "Holdings are linked to an account that is not an investment account.",
};

function AccountRow({ name, value, note }: { name: string; value: string | null; note?: string }) {
  return (
    <li role="treeitem" className="rounded border border-gray-100 bg-gray-50 px-3 py-2 text-sm">
      <div className="flex items-center justify-between gap-4">
        <span className="min-w-0 truncate text-gray-700" title={name}>{name}</span>
        <span className="shrink-0 tabular-nums text-gray-900">
          {value === null ? "—" : formatEur(Number(value))}
        </span>
      </div>
      {note && <p className="mt-1 text-xs text-amber-800">{note}</p>}
    </li>
  );
}

/** Account balances and security holdings use the same dated snapshot as the total. */
export function NetWorthComposition({ netWorth }: { netWorth: NetWorthReport }) {
  const composition = netWorth.account_composition;
  const fallbackWarning = getPortfolioCostFallbackWarning(netWorth.portfolio_valuation);
  const unallocatedCash = Number(composition.unallocated_account_balance) !== 0;
  const unallocatedPortfolio = Number(composition.unallocated_portfolio_value) !== 0;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-gray-700">Net worth composition</h3>
          <p className="mt-1 text-xs text-gray-500">
            Snapshot on {netWorth.as_of_date}: each branch explains its contribution to the total.
          </p>
        </div>
        <span className="text-xs text-gray-400">Account balances + Portfolio value</span>
      </div>

      <div role="tree" aria-label="Net worth calculation" className="max-w-3xl">
        <div role="treeitem" aria-expanded="true" className="flex items-center justify-between gap-4 rounded-md bg-gray-900 px-4 py-3 text-white">
          <span className="font-semibold">Net worth</span>
          <span className="font-semibold tabular-nums">{formatEur(Number(netWorth.net_worth))}</span>
        </div>

        <div role="group" className="ml-5 space-y-3 border-l-2 border-gray-200 pb-1 pl-5 pt-3">
          <div role="treeitem" aria-label="Account balances" aria-expanded="true">
            <div className="flex items-center justify-between gap-4 rounded-md border border-sky-200 bg-sky-50 px-4 py-2.5">
              <span className="font-medium text-sky-950">Account balances</span>
              <span className="font-semibold tabular-nums text-sky-950">{formatEur(Number(netWorth.total_accounts_balance))}</span>
            </div>
            <div role="group" className="ml-5 border-l border-sky-200 pl-4 pt-2">
              {composition.cash_accounts.length > 0 || unallocatedCash ? (
                <ul className="space-y-1.5">
                  {composition.cash_accounts.map((account) => (
                    <AccountRow key={account.account_id} name={account.name} value={account.balance} />
                  ))}
                  {unallocatedCash && (
                    <AccountRow
                      name="Unallocated account balance"
                      value={composition.unallocated_account_balance}
                      note="Recorded cash on investment accounts is included here pending reconciliation."
                    />
                  )}
                </ul>
              ) : (
                <p className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-500">No cash accounts present on the report date.</p>
              )}
            </div>
          </div>

          <div role="treeitem" aria-label="Portfolio value" aria-expanded="true">
            <div className="flex items-center justify-between gap-4 rounded-md border border-violet-200 bg-violet-50 px-4 py-2.5">
              <span className="font-medium text-violet-950">Portfolio value</span>
              <span className="font-semibold tabular-nums text-violet-950">{formatEur(Number(netWorth.total_portfolio_value))}</span>
            </div>
            <div role="group" className="ml-5 border-l border-violet-200 pl-4 pt-2">
              {composition.investment_accounts.length > 0 || unallocatedPortfolio ? (
                <ul className="space-y-1.5">
                  {composition.investment_accounts.map((account) => (
                    <AccountRow
                      key={account.account_id}
                      name={account.name}
                      value={account.value}
                      note={account.value === null
                        ? "Valuation unavailable: the recorded history does not allow reliable attribution."
                        : account.cost_fallback_securities.length > 0
                          ? `Includes an allocated FIFO cost estimate for ${account.cost_fallback_securities.map((security) => security.ticker).join(", ")}.`
                          : undefined}
                    />
                  ))}
                  {unallocatedPortfolio && (
                    <AccountRow
                      name="Unallocated portfolio value"
                      value={composition.unallocated_portfolio_value}
                      note="Included in the total; the recorded account history does not allow a reliable split."
                    />
                  )}
                </ul>
              ) : (
                <p className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-500">No investment accounts present on the report date.</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {fallbackWarning && (
        <div role="status" className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <strong>Estimated valuation:</strong> for {fallbackWarning.securitiesLabel} no quote exists on or before the report date.
          The total uses FIFO acquisition cost, allocated between accounts in proportion to their holdings where attribution is possible.
          This is a cost estimate; enter a historical price to obtain a market valuation.
        </div>
      )}
      {composition.issues.length > 0 && (
        <div role="status" className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <p className="font-medium">Some holdings cannot be reliably attributed to investment accounts.</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {composition.issues.map((issue) => (
              <li key={`${issue.account_id}-${issue.security_id}-${issue.reason}`}>
                {issue.name} — {issue.ticker}: {ISSUE_LABELS[issue.reason]}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
