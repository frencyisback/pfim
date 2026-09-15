import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useIncomeStatement, type DateRange } from "@/api/reports";
import { currencyYAxisProps } from "@/lib/chartScale";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SortableHeader from "@/components/common/SortableHeader";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { formatEur } from "@/lib/formatters";
import { useTableSort } from "@/lib/useTableSort";

export function IncomeStatementTab() {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useIncomeStatement(range);
  type PeriodSortKey = "period" | "income" | "expense" | "net" | "savings";
  const periodSort = useTableSort(
    data?.periods ?? [],
    { key: "period" as PeriodSortKey, direction: "asc" },
    (period, key) => {
      if (key === "period") return period.period_label;
      if (key === "income") return Number(period.total_income);
      if (key === "expense") return Number(period.total_expense);
      if (key === "net") return Number(period.net);
      return period.savings_rate_pct === null ? null : Number(period.savings_rate_pct);
    }
  );

  const chartData =
    data?.periods.map((p) => ({
      month: p.period_label,
      Inflows: Number(p.total_income),
      Outflows: Math.abs(Number(p.total_expense)),
    })) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="max-w-3xl text-xs text-gray-500">
          Cash inflows and outflows include security sales, purchases, coupons and costs. Transfers between your own accounts are excluded. Trades affect the balance and savings rate for the period.
        </p>
        <div className="flex flex-wrap items-start gap-2">
          <DateRangeFilter range={range} onChange={setRange} />
          <ExportCsvButton
            endpoint="income-statement"
            range={range}
            filename="income-statement.csv"
          />
        </div>
      </div>
      <QueryStateNotice isLoading={isLoading} error={error} />
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <KpiCard
              label="Total inflows"
              value={formatEur(Number(data.total_income))}
              positive
              formula={
                <>
                  <Formula>Σ transactions with positive amounts</Formula>
                  Across all accounts. Includes security sales, coupons and dividends; excludes transfers between your own accounts.
                </>
              }
            />
            <KpiCard
              label="Total outflows"
              value={formatEur(Number(data.total_expense))}
              positive={false}
              formula={
                <>
                  <Formula>Σ transactions with negative amounts</Formula>
                  Includes security purchases, expenses and costs; excludes transfers between your own accounts.
                </>
              }
            />
            <KpiCard
              label="Net balance"
              value={formatEur(Number(data.net))}
              positive={Number(data.net) >= 0}
              formula={
                <>
                  <Formula>Total inflows + Total outflows</Formula>
                  Outflows are already negative, so they are added.
                </>
              }
            />
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-gray-600">Monthly inflows vs outflows</h3>
            </div>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                  <YAxis {...currencyYAxisProps} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(v: number) => formatEur(v)} />
                  <Bar dataKey="Inflows" fill="#22c55e" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="Outflows" fill="#ef4444" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-10 text-center text-sm text-gray-400">No data available.</p>
            )}
          </div>

          <CollapsibleTable title="Monthly detail" count={data.periods.length}>
            <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
              <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-500">
                <tr>
                  {([
                    ["period", "Month", "left"],
                    ["income", "Inflows", "right"],
                    ["expense", "Outflows", "right"],
                    ["net", "Net", "right"],
                    ["savings", "Savings %", "right"],
                  ] as const).map(([key, label, align]) => (
                    <SortableHeader
                      key={key}
                      active={periodSort.sort.key === key}
                      direction={periodSort.sort.direction}
                      onSort={() => periodSort.requestSort(key)}
                      align={align}
                      className="px-3 py-2"
                    >
                      {label}
                    </SortableHeader>
                  ))}
                </tr>
              </thead>
              <tbody>
                {periodSort.sortedRows.map((p) => (
                  <tr key={p.period_label} className="border-t border-gray-100">
                    <td className="px-3 py-2">{p.period_label}</td>
                    <td className="px-3 py-2 text-right text-green-600">{formatEur(Number(p.total_income))}</td>
                    <td className="px-3 py-2 text-right text-red-600">{formatEur(Number(p.total_expense))}</td>
                    <td className="px-3 py-2 text-right font-medium">{formatEur(Number(p.net))}</td>
                    <td className="px-3 py-2 text-right">
                      {p.savings_rate_pct ? `${Number(p.savings_rate_pct).toFixed(1)}%` : "—"}
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
