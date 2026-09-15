import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePortfolioPerformance, type PortfolioPerformance } from "@/api/performance";
import { useNetWorth, useNetWorthHistory, type NetWorthReport } from "@/api/reports";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import { pctOrDash } from "@/components/reports/shared";
import { SavingsRateMetrics } from "@/components/reports/SavingsRateMetrics";
import { formatEur } from "@/lib/formatters";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";
import { useTableSort } from "@/lib/useTableSort";

/** Liquidity and runway (specification §7.5): how long readily available
 * cash lasts, indicating whether the emergency fund is sufficient. */
function LiquidityMetrics({ netWorth }: { netWorth: NetWorthReport }) {
  const runway = netWorth.runway_months;
  const months = runway === null ? null : Number(runway);
  // Conventional emergency fund thresholds: under 3 months is exposed;
  // over 6 months is considered solid.
  const tone =
    months === null ? undefined : months >= 6 ? true : months < 3 ? false : undefined;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Liquidity and runway</h3>
      <p className="mb-3 text-xs text-gray-400">
        How long readily available cash would last at the spending rate of the last 12 months. Liquidity includes only checking accounts; spending excludes security purchases and transfers between your own accounts.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <KpiCard
          label="Available liquidity"
          value={formatEur(Number(netWorth.liquid_balance))}
          formula={
            <>
              <Formula>Σ checking account balances on the report date</Formula>
              Includes only Checking accounts. Deposit, cash and investment accounts remain in total account balances, but are excluded from available liquidity.
            </>
          }
        />
        <KpiCard
          label="Average monthly spending"
          value={
            netWorth.average_monthly_expenses === null
              ? "—"
              : formatEur(Number(netWorth.average_monthly_expenses))
          }
          formula={
            <>
              <Formula>Σ monthly spending capped at percentiles P5–P95 ÷ 12</Formula>
              Outflows in expense categories and uncategorised negative transactions, net of refunds in the same categories. Excludes security purchases and transfers between your own accounts. Uses the last 12 calendar months, including months without spending and the partial current month; caps extreme values before averaging.
            </>
          }
        />
        <KpiCard
          label="Months of runway"
          value={months === null ? "—" : `${months.toFixed(1)} months`}
          positive={tone}
          formula={
            <>
              <Formula>Available liquidity ÷ Average monthly spending</Formula>
              How long you could manage without income. Conventionally, under 3 months is exposed and over 6 months is solid.
            </>
          }
        />
      </div>
      {months !== null && months < 3 && (
        <p className="mt-3 text-xs text-amber-700">
          Less than 3 months of coverage: an unexpected expense could require selling investments at an unfavourable time.
        </p>
      )}
    </div>
  );
}

/** Portfolio growth (specification §9.3, §9.4): TWR measures portfolio
 * performance; MWR measures returns on capital as actually contributed. */
function GrowthMetrics({ performance }: { performance: PortfolioPerformance }) {
  const twr = performance.time_weighted_return;
  const twrAnn = performance.time_weighted_return_annualized;
  const mwr = performance.money_weighted_return;
  const days = performance.investment_period_days;
  const years = days === null ? null : days / 365;
  type PerformanceSortKey = "ticker" | "simple" | "total" | "mwr" | "realized";
  const performanceSort = useTableSort(
    performance.by_security,
    { key: "ticker" as PerformanceSortKey, direction: "asc" },
    (metric, key) => {
      if (key === "ticker") return metric.ticker;
      if (key === "simple") {
        return metric.simple_return === null ? null : Number(metric.simple_return);
      }
      if (key === "total") return metric.total_return === null ? null : Number(metric.total_return);
      if (key === "mwr") {
        return metric.money_weighted_return === null ? null : Number(metric.money_weighted_return);
      }
      return Number(metric.realized_gain_loss);
    }
  );

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-600">Securities portfolio growth</h3>
        {years !== null && (
          <span className="text-xs text-gray-400">
            Period: {years.toFixed(1)} years ({days} days since the first trade)
          </span>
        )}
      </div>

      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-gray-400">Annualised</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <KpiCard
          label="Annual TWR (portfolio return)"
          value={pctOrDash(twrAnn)}
          positive={twrAnn === null ? undefined : Number(twrAnn) >= 0}
          formula={
            <>
              <Formula>(1 + Cumulative TWR)^(365 ÷ days) − 1</Formula>
              Compound annual growth rate (CAGR) of TWR, allowing comparison of periods of different lengths.
            </>
          }
        />
        <KpiCard
          label="Annual MWR / IRR (capital return)"
          value={pctOrDash(mwr)}
          positive={mwr === null ? undefined : Number(mwr) >= 0}
          formula={
            <>
              <Formula>rate r such that Σ CF / (1+r)^(days/365) = 0</Formula>
              XIRR on actual cash flows (negative purchases, positive sales and coupons, final value as the last flow). It is <em>already</em> an annual rate, so it is excluded from cumulative figures.
            </>
          }
        />
        <KpiCard
          label="Annual total return"
          value={pctOrDash(performance.total_return_annualized)}
          positive={
            performance.total_return_annualized === null
              ? undefined
              : Number(performance.total_return_annualized) >= 0
          }
          formula={
            <>
              <Formula>(1 + Cumulative total return)^(365 ÷ days) − 1</Formula>
              The same calculation applied to total return.
            </>
          }
        />
      </div>

      <p className="mb-2 mt-4 text-xs font-medium uppercase tracking-wide text-gray-400">
        Cumulative over the entire period
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <KpiCard
          label="Cumulative TWR"
          value={pctOrDash(twr)}
          positive={twr === null ? undefined : Number(twr) >= 0}
          formula={
            <>
              <Formula>[(1+R₁) × (1+R₂) × … × (1+Rₙ)] − 1</Formula>
              The period starts with the first trade and splits at every contribution or withdrawal. Subperiod returns are linked to remove the effect of investment timing. Unavailable ("—") if a withdrawal exceeds the portfolio value on that date, usually because that day's price is missing.
            </>
          }
        />
        <KpiCard
          label="Cumulative total return"
          value={pctOrDash(performance.total_return)}
          positive={
            performance.total_return === null ? undefined : Number(performance.total_return) >= 0
          }
          formula={
            <>
              <Formula>(Final value − Invested capital + Net income) ÷ Invested capital</Formula>
              Includes coupons and dividends received as well as price appreciation.
            </>
          }
        />
        <KpiCard
          label="Income received"
          value={formatEur(Number(performance.total_income_received))}
          formula={
            <>
              <Formula>Σ net coupon and dividend amounts</Formula>
              After withholding, converted to euros.
            </>
          }
        />
      </div>

      <p className="mt-3 text-xs text-gray-500">
        The <strong>TWR</strong> measures portfolio returns independently of when and how much capital you contributed, allowing comparison with a market index. The{" "}
        <strong>MWR</strong> measures the return on capital as actually invested, so contribution timing matters. It is inherently an annual rate and is excluded from cumulative figures. Annual values are compound rates (CAGR), allowing comparison across different period lengths. Both include coupons and dividends received and require recorded trades and at least one reference price.
      </p>

      {performance.by_security.length > 0 && (
        <div className="mt-4">
          <CollapsibleTable title="Detail by security" count={performance.by_security.length}>
            <div className="overflow-hidden rounded border border-gray-200">
              <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["ticker", "Security", "left"],
                  ["simple", "Simple return", "right"],
                  ["total", "Total return", "right"],
                  ["mwr", "MWR", "right"],
                  ["realized", "Realised", "right"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={performanceSort.sort.key === key}
                    direction={performanceSort.sort.direction}
                    onSort={() => performanceSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
              </tr>
            </thead>
            <tbody>
              {performanceSort.sortedRows.map((m) => (
                <tr key={m.security_id} className="border-t border-gray-100">
                  <td className="px-3 py-2 font-medium">{m.ticker}</td>
                  <td className="px-3 py-2 text-right">{pctOrDash(m.simple_return)}</td>
                  <td className="px-3 py-2 text-right">{pctOrDash(m.total_return)}</td>
                  <td className="px-3 py-2 text-right">{pctOrDash(m.money_weighted_return)}</td>
                  <td
                    className={`px-3 py-2 text-right ${
                      Number(m.realized_gain_loss) >= 0 ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {formatEur(Number(m.realized_gain_loss))}
                  </td>
                </tr>
              ))}
            </tbody>
              </table>
            </div>
          </CollapsibleTable>
        </div>
      )}
    </div>
  );
}

/** Shows the sum producing net worth. Account details use the same
 * point-in-time snapshot as totals, so they cannot diverge from KPIs. */
function NetWorthComposition({ netWorth }: { netWorth: NetWorthReport }) {
  const fallbackWarning = getPortfolioCostFallbackWarning(netWorth.portfolio_valuation);

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
        <div
          role="treeitem"
          aria-expanded="true"
          className="flex items-center justify-between gap-4 rounded-md bg-gray-900 px-4 py-3 text-white"
        >
          <span className="font-semibold">Net worth</span>
          <span className="font-semibold tabular-nums">
            {formatEur(Number(netWorth.net_worth))}
          </span>
        </div>

        <div role="group" className="ml-5 space-y-3 border-l-2 border-gray-200 pb-1 pl-5 pt-3">
          <div role="treeitem" aria-expanded="true">
            <div className="flex items-center justify-between gap-4 rounded-md border border-sky-200 bg-sky-50 px-4 py-2.5">
              <span className="font-medium text-sky-950">Account balances</span>
              <span className="font-semibold tabular-nums text-sky-950">
                {formatEur(Number(netWorth.total_accounts_balance))}
              </span>
            </div>
            <div role="group" className="ml-5 border-l border-sky-200 pl-4 pt-2">
              {netWorth.by_account.length > 0 ? (
                <ul className="space-y-1.5">
                  {netWorth.by_account.map((account) => (
                    <li
                      role="treeitem"
                      key={account.account_id}
                      className="flex items-center justify-between gap-4 rounded border border-gray-100 bg-gray-50 px-3 py-2 text-sm"
                    >
                      <span className="min-w-0 truncate text-gray-700" title={account.name}>
                        {account.name}
                      </span>
                      <span className="shrink-0 tabular-nums text-gray-900">
                        {formatEur(Number(account.balance))}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="rounded bg-gray-50 px-3 py-2 text-xs text-gray-500">
                  No accounts present on the report date.
                </p>
              )}
            </div>
          </div>

          <div
            role="treeitem"
            className="flex items-center justify-between gap-4 rounded-md border border-violet-200 bg-violet-50 px-4 py-2.5"
          >
            <span className="font-medium text-violet-950">Portfolio value</span>
            <span className="font-semibold tabular-nums text-violet-950">
              {formatEur(Number(netWorth.total_portfolio_value))}
            </span>
          </div>
        </div>
      </div>
      {fallbackWarning && (
        <div
          role="status"
          className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
        >
          <strong>Estimated valuation:</strong> for {fallbackWarning.securitiesLabel}{" "}
          no quote exists on or before the report date. The value therefore uses FIFO acquisition cost; enter a historical price to obtain a market valuation.
        </div>
      )}
    </div>
  );
}

export function NetWorthTab() {
  const { data: netWorth, isLoading, error: netWorthError } = useNetWorth();
  const {
    data: aggregateHistory,
    isLoading: historyLoading,
    error: historyError,
  } = useNetWorthHistory();
  const {
    data: performance,
    isLoading: performanceLoading,
    error: performanceError,
  } = usePortfolioPerformance();
  const aggregateChartData =
    aggregateHistory?.map((p) => ({
      date: p.date,
      "Account balances": Number(p.total_balance),
      Portfolio: Number(p.portfolio_value),
      "Net worth": Number(p.net_worth),
    })) ?? [];
  const historyFallbackPoints =
    aggregateHistory?.filter(
      (point) => getPortfolioCostFallbackWarning(point.portfolio_valuation) !== null
    ) ?? [];
  const historyFallbackTickers = Array.from(
    new Set(
      historyFallbackPoints.flatMap((point) =>
        point.portfolio_valuation.cost_fallback_securities.map((item) => item.ticker),
      ),
    ),
  );
  const historyFallbackSecurityLabel =
    historyFallbackTickers.length > 0 ? historyFallbackTickers.join(", ") : "one or more securities";

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportCsvButton endpoint="net-worth" filename="net-worth.csv" />
      </div>
      <QueryStateNotice
        isLoading={isLoading || historyLoading || performanceLoading}
        error={netWorthError ?? historyError ?? performanceError}
      />
      {netWorth && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <KpiCard
              label="Net worth"
              value={formatEur(Number(netWorth.net_worth))}
              formula={
                <>
                  <Formula>Account balances + Portfolio value</Formula>
                  Everything you own: cash held in accounts plus the market value of securities.
                </>
              }
            />
            <KpiCard
              label="Account balances"
              value={formatEur(Number(netWorth.total_accounts_balance))}
              formula={
                <>
                  <Formula>Σ balances of accounts present on the report date</Formula>
                  Includes investment accounts. For legacy data without lifecycle dates, historical presence remains intentionally unknown and the account is retained in the snapshot.
                </>
              }
            />
            <KpiCard
              label="Portfolio value"
              value={formatEur(Number(netWorth.total_portfolio_value))}
              formula={
                <>
                  <Formula>Σ (quantity on date × latest price available on date × exchange rate)</Formula>
                  Only positions open in the snapshot, converted to euros, without using later trades or prices. If a valid quote is missing, the position remains visible at FIFO cost and is explicitly flagged.
                </>
              }
            />
          </div>
          <NetWorthComposition netWorth={netWorth} />
          <LiquidityMetrics netWorth={netWorth} />
        </>
      )}

      <SavingsRateMetrics />

      {performance && <GrowthMetrics performance={performance} />}

      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h3 className="mb-1 text-sm font-medium text-gray-600">Net worth history</h3>
        <p className="mb-3 text-xs text-gray-400">
          The <strong>total account balance</strong> falls when you buy securities as money becomes investments. Your <strong>net worth</strong> also includes portfolio value on that date: use this curve to assess growth.
        </p>
        {historyFallbackPoints.length > 0 && (
          <p className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
            At {historyFallbackPoints.length} historical points the portfolio uses FIFO cost because a quote was not yet available for {historyFallbackSecurityLabel}.
          </p>
        )}
        {/* Use ComposedChart because AreaChart ignores Line children,
            which would prevent the net worth curve from rendering. */}
        {aggregateChartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={aggregateChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatEur(v)} width={80} />
              <Tooltip formatter={(v: number) => formatEur(v)} />
              <Legend />
              <Area
                type="stepAfter"
                dataKey="Account balances"
                stackId="1"
                stroke="#0ea5e9"
                fill="#0ea5e9"
                fillOpacity={0.25}
              />
              <Area
                type="stepAfter"
                dataKey="Portfolio"
                stackId="1"
                stroke="#8b5cf6"
                fill="#8b5cf6"
                fillOpacity={0.25}
              />
              <Line
                type="stepAfter"
                dataKey="Net worth"
                stroke="#111827"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <p className="flex h-[280px] items-center justify-center text-sm text-gray-400">
            No transactions recorded.
          </p>
        )}
      </div>

    </div>
  );
}
