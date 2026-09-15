import { useState } from "react";
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
import { type CategoryAnalysisReport, type DateRange } from "@/api/reports";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { SpendingCategoryBreakdown } from "@/components/reports/SpendingCategoryBreakdown";
import { CATEGORY_COLORS } from "@/components/reports/shared";
import { currencyYAxisProps } from "@/lib/chartScale";
import { formatEur, formatMoneyWithEur } from "@/lib/formatters";

/** Expenses, income and transfers share the main statistics.
 * Expenses also include breakdowns and details by root category. */
export function CategoryAnalysisTab({
  useReport,
  endpoint,
  accent,
  barColor,
  emptyLabel,
  showTopLevel = false,
}: {
  useReport: (range: DateRange) => {
    data: CategoryAnalysisReport | undefined;
    isLoading: boolean;
    error: unknown;
  };
  /** Report path for exporting the same displayed period to CSV. */
  endpoint: string;
  accent: string;
  barColor: string;
  emptyLabel: string;
  showTopLevel?: boolean;
}) {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useReport(range);

  const pieData =
    data?.by_category.map((c) => ({
      name: c.category_name,
      value: Math.abs(Number(c.total_amount)),
    })) ?? [];
  const monthData =
    data?.by_month.map((m) => ({
      month: m.period_label,
      Total: Math.abs(Number(m.total_amount)),
    })) ?? [];
  const topLevelPieData =
    data?.by_top_level_category.map((category) => ({
      name: category.category_name,
      value: Math.abs(Number(category.total_amount)),
    })) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <DateRangeFilter range={range} onChange={setRange} />
        <ExportCsvButton endpoint={endpoint} range={range} filename={`${endpoint}.csv`} />
      </div>

      <QueryStateNotice isLoading={isLoading} error={error} />
      {data && (
        <>
          <KpiCard label="Total" value={formatEur(Number(data.total_amount))} />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {showTopLevel && (
              <div className="rounded-lg border border-gray-200 bg-white p-4 lg:col-span-2">
                <h3 className="mb-1 text-sm font-medium text-gray-600">
                  Breakdown by top-level category
                </h3>
                <p className="mb-3 text-xs text-gray-400">
                  Each subcategory contributes to its root category; percentages cover the entire selected period.
                </p>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  {topLevelPieData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={260}>
                      <PieChart>
                        <Pie
                          data={topLevelPieData}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={90}
                          label={(entry) => entry.name}
                          isAnimationActive={false}
                        >
                          {topLevelPieData.map((_, index) => (
                            <Cell
                              key={index}
                              fill={CATEGORY_COLORS[index % CATEGORY_COLORS.length]}
                            />
                          ))}
                        </Pie>
                        <Tooltip formatter={(value: number) => formatEur(value)} />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <p className="flex h-[260px] items-center justify-center text-sm text-gray-400">
                      {emptyLabel}
                    </p>
                  )}
                  <ul className="self-center space-y-1 text-sm">
                    {data.by_top_level_category.map((category) => (
                      <li
                        key={category.category_id ?? "none"}
                        className="flex justify-between border-b border-gray-50 py-1"
                      >
                        <span className="text-gray-600">{category.category_name}</span>
                        <span className="font-medium">
                          {formatEur(Number(category.total_amount))}{" "}
                          <span className="text-xs text-gray-400">
                            ({Number(category.pct_of_total).toFixed(1)}%)
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {showTopLevel && (
              <SpendingCategoryBreakdown
                key={`${range.from ?? ""}:${range.to ?? ""}`}
                data={data}
              />
            )}

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-600">
                Breakdown by leaf category (top 10)
              </h3>
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      label={(e) => e.name}
                      isAnimationActive={false}
                    >
                      {pieData.map((_, i) => (
                        <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number) => formatEur(v)} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="flex h-[260px] items-center justify-center text-sm text-gray-400">
                  {emptyLabel}
                </p>
              )}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-gray-600">Month-by-month trend</h3>
              </div>
              {monthData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={monthData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis {...currencyYAxisProps} tick={{ fontSize: 11 }} />
                    <Tooltip formatter={(v: number) => formatEur(v)} />
                    <Bar dataKey="Total" fill={barColor} radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="flex h-[260px] items-center justify-center text-sm text-gray-400">
                  {emptyLabel}
                </p>
              )}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-600">Top 10 categories</h3>
              <ul className="space-y-1 text-sm">
                {data.by_category.map((c) => (
                  <li
                    key={c.category_id ?? "none"}
                    className="flex justify-between border-b border-gray-50 py-1"
                  >
                    <span className="text-gray-600">{c.category_name}</span>
                    <span className={`font-medium ${accent}`}>
                      {formatEur(Number(c.total_amount))}{" "}
                      <span className="text-xs text-gray-400">
                        ({Number(c.pct_of_total).toFixed(1)}%)
                      </span>
                    </span>
                  </li>
                ))}
                {data.by_category.length === 0 && (
                  <li className="py-4 text-center text-gray-400">{emptyLabel}</li>
                )}
              </ul>
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-600">Top 10 transactions</h3>
              <ul className="space-y-1 text-sm">
                {data.top_transactions.map((t) => (
                  <li key={t.id} className="flex justify-between border-b border-gray-50 py-1">
                    <span className="text-gray-600">
                      {t.date} — {t.description ?? "—"}
                    </span>
                    <span className={`font-medium ${accent}`}>
                      {formatMoneyWithEur(
                        Number(t.amount),
                        t.currency,
                        Number(t.amount_eur)
                      )}
                    </span>
                  </li>
                ))}
                {data.top_transactions.length === 0 && (
                  <li className="py-4 text-center text-gray-400">{emptyLabel}</li>
                )}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
