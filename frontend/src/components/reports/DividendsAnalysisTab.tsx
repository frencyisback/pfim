import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useDividendsAnalysis,
  type DateRange,
  type DividendBySecurity,
  type DividendYearPoint,
} from "@/api/reports";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import { currencyYAxisProps } from "@/lib/chartScale";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import SortableHeader from "@/components/common/SortableHeader";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { CATEGORY_COLORS } from "@/components/reports/shared";
import { formatEur } from "@/lib/formatters";
import { securityTypeLabel } from "@/lib/securityTypes";
import { useTableSort } from "@/lib/useTableSort";

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const EVENT_TYPE_LABELS: Record<string, string> = {
  dividend: "Dividend",
  coupon: "Coupon",
  return_of_capital: "Return of capital",
};

/** Coupon and dividend analysis (specification §7.5.1): accumulation,
 * payment frequency, paying securities and seasonal income distribution. */
export function DividendsAnalysisTab() {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useDividendsAnalysis(range);
  type YearSortKey = "year" | "gross" | "tax" | "net" | "cumulative" | "growth";
  const yearSort = useTableSort<DividendYearPoint, YearSortKey>(
    data?.by_year ?? [],
    { key: "year", direction: "asc" },
    (year, key) => {
      if (key === "year") return year.year;
      if (key === "gross") return Number(year.gross);
      if (key === "tax") return Number(year.tax);
      if (key === "net") return Number(year.net);
      if (key === "cumulative") return Number(year.cumulative_net);
      return year.growth_pct === null ? null : Number(year.growth_pct);
    }
  );
  type SecuritySortKey = "ticker" | "type" | "events" | "net" | "share" | "yield";
  const securitySort = useTableSort<DividendBySecurity, SecuritySortKey>(
    data?.by_security.slice(0, 10) ?? [],
    { key: "net", direction: "desc" },
    (security, key) => {
      if (key === "ticker") return `${security.ticker} ${security.name}`;
      if (key === "type") return securityTypeLabel(security.type);
      if (key === "events") return security.events_count;
      if (key === "net") return Number(security.net);
      if (key === "share") return Number(security.pct_of_total);
      return security.yield_on_cost_pct === null ? null : Number(security.yield_on_cost_pct);
    }
  );

  const yearData =
    data?.by_year.map((y) => ({
      year: String(y.year),
      Net: Number(y.net),
      Withholding: Number(y.tax),
      Cumulative: Number(y.cumulative_net),
    })) ?? [];

  const monthData =
    data?.by_month.map((m) => ({
      month: MONTH_LABELS[m.month - 1],
      Received: Number(m.net),
    })) ?? [];

  // Positive values only: a pie chart cannot represent negative net income
  // (possible when withholding exceeds gross income). Without this filter,
  // the chart would be empty without explaining why.
  const typePie =
    data?.by_security_type
      .filter((t) => Number(t.net) > 0)
      .map((t) => ({ name: securityTypeLabel(t.key), value: Number(t.net) })) ?? [];

  const eventPie =
    data?.by_event_type
      .filter((t) => Number(t.net) > 0)
      .map((t) => ({ name: EVENT_TYPE_LABELS[t.key] ?? t.key, value: Number(t.net) })) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <DateRangeFilter range={range} onChange={setRange} />
        <ExportCsvButton
          endpoint="dividends-analysis"
          range={range}
          filename="income-analysis.csv"
        />
      </div>

      <QueryStateNotice isLoading={isLoading} error={error} />

      {data && data.events_count === 0 && (
        <p className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-400">
          No coupons or dividends recorded in this period. Add them on the Income page.
        </p>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <KpiCard
              label="Net income received in period"
              value={formatEur(Number(data.total_net))}
              positive
              formula={
                <>
                  <Formula>Σ (gross amount − withholding) × exchange rate</Formula>
                  The amount actually credited to the account in the selected period.
                </>
              }
            />
            <KpiCard
              label="Tax withheld"
              value={`${formatEur(Number(data.total_tax))}${
                data.tax_incidence_pct === null
                  ? ""
                  : ` (${Number(data.tax_incidence_pct).toFixed(1)}%)`
              }`}
              positive={false}
              formula={
                <>
                  <Formula>Gross − Net (percentage: ÷ Gross)</Formula>
                  The same withholding is included under taxes in the Costs and Taxation tab.
                </>
              }
            />
            <KpiCard
              label="Last 12 months"
              value={formatEur(Number(data.trailing_12m_net))}
              formula={
                <>
                  <Formula>Σ net receipts over the last 365 days</Formula>
                  Unaffected by the selected period: always the year ending today.
                </>
              }
            />
            <KpiCard
              label="Yield on cost over the last 12 months"
              value={
                data.portfolio_yield_on_cost_pct === null
                  ? "—"
                  : `${Number(data.portfolio_yield_on_cost_pct).toFixed(2)}%`
              }
              formula={
                <>
                  <Formula>Receipts over the last 12 months ÷ Acquisition cost</Formula>
                  Coupon yield on capital <em>actually invested</em>, rather than current market value. If the security has risen sharply, the yield stays high because it depends on the price you paid.
                </>
              }
            />
          </div>
        </>
      )}

      {data && data.events_count > 0 && (
        <>
          <p className="text-xs text-gray-500">
            {data.events_count} receipts between {data.first_event_date} and {data.last_event_date}
            {data.average_monthly_net !== null && (
              <> — averaging {formatEur(Number(data.average_monthly_net))} per month</>
            )}
            . The <strong>yield on cost</strong> compares receipts over the last 12 months with the acquisition cost of positions open today. The securities table uses income for the selected period. This measures coupon yield on capital actually invested rather than current market value.
          </p>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-gray-600">
                Yearly accumulation (net receipts and cumulative total)
              </h3>
            </div>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={yearData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="year" tick={{ fontSize: 11 }} />
                <YAxis {...currencyYAxisProps} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => formatEur(v)} />
                <Legend />
                <Bar dataKey="Net" fill="#22c55e" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Withholding" fill="#ef4444" radius={[4, 4, 0, 0]} />
                <Line
                  type="monotone"
                  dataKey="Cumulative"
                  stroke="#0ea5e9"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="mt-3">
              <CollapsibleTable title="Yearly detail" count={data.by_year.length}>
                <div className="overflow-hidden rounded border border-gray-200">
                  <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-gray-500">
                  <tr>
                    {([
                      ["year", "Year", "left"],
                      ["gross", "Gross", "right"],
                      ["tax", "Withholding", "right"],
                      ["net", "Net", "right"],
                      ["cumulative", "Cumulative", "right"],
                      ["growth", "Change from previous year", "right"],
                    ] as const).map(([key, label, align]) => (
                      <SortableHeader
                        key={key}
                        active={yearSort.sort.key === key}
                        direction={yearSort.sort.direction}
                        onSort={() => yearSort.requestSort(key)}
                        align={align}
                        className="px-3 py-2"
                      >
                        {label}
                      </SortableHeader>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {yearSort.sortedRows.map((y) => (
                    <tr key={y.year} className="border-t border-gray-100">
                      <td className="px-3 py-2 font-medium">{y.year}</td>
                      <td className="px-3 py-2 text-right">{formatEur(Number(y.gross))}</td>
                      <td className="px-3 py-2 text-right text-red-600">
                        {formatEur(Number(y.tax))}
                      </td>
                      <td className="px-3 py-2 text-right font-medium text-green-600">
                        {formatEur(Number(y.net))}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-500">
                        {formatEur(Number(y.cumulative_net))}
                      </td>
                      <td
                        className={`px-3 py-2 text-right ${
                          y.growth_pct === null
                            ? "text-gray-400"
                            : Number(y.growth_pct) >= 0
                              ? "text-green-600"
                              : "text-red-600"
                        }`}
                      >
                        {y.growth_pct === null
                          ? "—"
                          : `${Number(y.growth_pct) >= 0 ? "+" : ""}${Number(y.growth_pct).toFixed(1)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
                  </table>
                </div>
              </CollapsibleTable>
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-gray-600">Distribution throughout the year</h3>
            </div>
            <p className="mb-3 text-xs text-gray-400">
              Months in which receipts are concentrated, combining every year in the period. Helps identify regular or seasonal income.
            </p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={monthData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis {...currencyYAxisProps} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(v: number) => formatEur(v)} />
                <Bar dataKey="Received" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <DividendPie title="By instrument type" data={typePie} />
            <DividendPie title="By event type" data={eventPie} />
          </div>

          <CollapsibleTable
            title="Securities by income received"
            count={Math.min(data.by_security.length, 10)}
          >
            <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-gray-500">
                  <tr>
                    {([
                      ["ticker", "Security", "left"],
                      ["type", "Type", "left"],
                      ["events", "Receipts", "right"],
                      ["net", "Net", "right"],
                      ["share", "Share", "right"],
                      ["yield", "Yield on cost for period", "right"],
                    ] as const).map(([key, label, align]) => (
                      <SortableHeader
                        key={key}
                        active={securitySort.sort.key === key}
                        direction={securitySort.sort.direction}
                        onSort={() => securitySort.requestSort(key)}
                        align={align}
                        className="px-3 py-2"
                      >
                        {label}
                      </SortableHeader>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {securitySort.sortedRows.map((s) => (
                    <tr key={s.security_id} className="border-t border-gray-100">
                      <td className="px-3 py-2">
                        <div className="font-medium">{s.ticker}</div>
                        <div className="text-xs text-gray-400">{s.name}</div>
                      </td>
                      <td className="px-3 py-2 text-xs text-gray-500">
                        {securityTypeLabel(s.type)}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-500">{s.events_count}</td>
                      <td className="px-3 py-2 text-right font-medium text-green-600">
                        {formatEur(Number(s.net))}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-500">
                        {Number(s.pct_of_total).toFixed(1)}%
                      </td>
                      <td className="px-3 py-2 text-right">
                        {s.yield_on_cost_pct === null
                          ? "—"
                          : `${Number(s.yield_on_cost_pct).toFixed(2)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CollapsibleTable>
        </>
      )}
    </div>
  );
}

function DividendPie({ title, data }: { title: string; data: { name: string; value: number }[] }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-medium text-gray-600">{title}</h3>
      {data.length > 0 ? (
        <ResponsiveContainer width="100%" height={240}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={85}
              label={(e) => e.name}
              isAnimationActive={false}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v: number) => formatEur(v)} />
          </PieChart>
        </ResponsiveContainer>
      ) : (
        <p className="flex h-[240px] items-center justify-center px-6 text-center text-sm text-gray-400">
          No positive net receipts in this period.
        </p>
      )}
    </div>
  );
}
