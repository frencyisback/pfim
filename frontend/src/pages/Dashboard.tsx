import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useNetWorth, useIncomeStatement } from "@/api/reports";
import { usePortfolioSummary } from "@/api/portfolio";
import { formatEur } from "@/lib/formatters";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";
import { securityTypeLabel } from "@/lib/securityTypes";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { currencyYAxisProps } from "@/lib/chartScale";

/** Dashboard page: main KPIs and summary charts. Specification §7.2. */
const ALLOCATION_COLORS = ["#0ea5e9", "#8b5cf6", "#f97316", "#22c55e", "#ec4899", "#64748b"];

/** Context panel explaining PFIM and how its sections connect, helping
 * new and returning users identify where to start. */
function IntroPanel() {
  const sections: { icon: string; title: string; text: string }[] = [
    {
      icon: "💸",
      title: "Cash flow",
      text: "Categorised account inflows and outflows form the basis of balances and the income statement.",
    },
    {
      icon: "🎯",
      title: "Securities and portfolio",
      text: "Purchases, sales, coupons and prices. Each trade automatically generates its corresponding cash transaction.",
    },
    {
      icon: "📊",
      title: "Reports and forecasts",
      text: "Net worth, returns, incurred costs and long-term projections based on your records.",
    },
  ];

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <h3 className="text-base font-semibold text-gray-800">
        PFIM — Personal Finance and Investment Management
      </h3>
      <p className="mt-1 max-w-3xl text-sm text-gray-600">
        One place to understand <strong>what you own</strong>, <strong>where it goes</strong> and{" "}
        <strong>how it performs</strong>. Daily account management and investment performance come together in a single net worth figure. All data stays on your computer.
      </p>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        {sections.map((s) => (
          <div key={s.title} className="rounded border border-gray-100 bg-gray-50 p-3">
            <div className="text-sm font-medium text-gray-700">
              {s.icon} {s.title}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-gray-500">{s.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const { data: netWorth, isLoading: nwLoading, error: netWorthError } = useNetWorth();
  const {
    data: incomeStatement,
    isLoading: incomeLoading,
    error: incomeError,
  } = useIncomeStatement();
  const {
    data: portfolioSummary,
    isLoading: portfolioLoading,
    error: portfolioError,
  } = usePortfolioSummary();
  const fallbackWarning = netWorth
    ? getPortfolioCostFallbackWarning(netWorth.portfolio_valuation)
    : null;

  const monthlyData =
    incomeStatement?.periods.slice(-6).map((p) => ({
      month: p.period_label,
      Inflows: Number(p.total_income),
      Outflows: Math.abs(Number(p.total_expense)),
    })) ?? [];

  const allocationData = portfolioSummary
    ? Object.entries(portfolioSummary.allocation_by_type).map(([type, value]) => ({
        name: securityTypeLabel(type),
        value: Number(value),
      }))
    : [];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Dashboard</h2>

      <IntroPanel />

      <QueryStateNotice
        isLoading={nwLoading || incomeLoading || portfolioLoading}
        error={netWorthError ?? incomeError ?? portfolioError}
      />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label="Net worth"
          value={nwLoading ? "..." : formatEur(Number(netWorth?.net_worth ?? 0))}
          formula={
            <>
              <Formula>Account balances + Portfolio value</Formula>
              Everything you own: account cash plus the market value of securities.
            </>
          }
        />
        <KpiCard
          label="Account balances"
          value={nwLoading ? "..." : formatEur(Number(netWorth?.total_accounts_balance ?? 0))}
          formula={
            <>
              <Formula>Σ balances of accounts present on the report date</Formula>
              Includes investment accounts. Reports → Net worth shows available liquidity calculated from checking accounts only.
            </>
          }
        />
        <KpiCard
          label="Portfolio value"
          value={nwLoading ? "..." : formatEur(Number(netWorth?.total_portfolio_value ?? 0))}
          formula={
            <>
              <Formula>Σ (quantity × latest price × exchange rate)</Formula>
              Open positions only, converted to euros. If a valid quote is missing, net worth uses FIFO cost and displays a warning below the KPIs.
            </>
          }
        />
        <KpiCard
          label="Unrealised gain/loss"
          value={formatEur(Number(portfolioSummary?.total_unrealized_gain_loss ?? 0))}
          positive={Number(portfolioSummary?.total_unrealized_gain_loss ?? 0) >= 0}
          formula={
            <>
              <Formula>Current value − Acquisition cost</Formula>
              Paper gains or losses become realised only when you sell.
            </>
          }
        />
      </div>

      {fallbackWarning && (
        <div
          role="status"
          className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
          >
            Net worth includes a FIFO cost estimate for{" "}
          {fallbackWarning.securitiesLabel}
          : a valid quote is missing for today. Details are available in Reports → Net worth.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div>
              <h3 className="text-sm font-medium text-gray-600">
                Aggregate inflows vs outflows (recent months)
              </h3>
              <p className="mt-1 text-xs text-gray-400">
                Transactions across all accounts, including security purchases and sales. Transfers between accounts are excluded.
              </p>
            </div>
          </div>
          {monthlyData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={monthlyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis {...currencyYAxisProps} tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: number) => formatEur(v)} />
                <Bar dataKey="Inflows" fill="#22c55e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Outflows" fill="#ef4444" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>

        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-medium text-gray-600">Portfolio asset allocation</h3>
          {allocationData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={allocationData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={90}
                  label={(entry) => entry.name}
                  isAnimationActive={false}
                >
                  {allocationData.map((_, i) => (
                    <Cell key={i} fill={ALLOCATION_COLORS[i % ALLOCATION_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => formatEur(v)} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <EmptyChart />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyChart() {
  return (
    <div className="flex h-[260px] items-center justify-center text-sm text-gray-400">
      No data available yet.
    </div>
  );
}
