import { useId, useState } from "react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { CategoryAnalysisReport } from "@/api/reports";
import { CATEGORY_COLORS } from "@/components/reports/shared";
import { formatEur } from "@/lib/formatters";
import { clampPageToTotal } from "@/lib/pagination";
import { spendingBreakdown } from "@/lib/spendingBreakdown";

const PAGE_SIZE = 8;
const categoryKey = (id: number | null) => id === null ? "uncategorized" : String(id);

export function SpendingCategoryBreakdown({ data }: { data: CategoryAnalysisReport }) {
  const selectId = useId();
  const [selectedKey, setSelectedKey] = useState("");
  const [requestedPage, setRequestedPage] = useState(1);
  const root = data.by_top_level_category.find(
    (item) => categoryKey(item.category_id) === selectedKey,
  ) ?? data.by_top_level_category[0];
  const breakdown = spendingBreakdown(data.by_category_detail, root?.category_id ?? null);
  const pieData = breakdown.items.filter((item) => item.value > 0);
  const page = clampPageToTotal(requestedPage, breakdown.items.length, PAGE_SIZE);
  const pageCount = Math.max(1, Math.ceil(breakdown.items.length / PAGE_SIZE));
  const pageStart = (page - 1) * PAGE_SIZE;
  const visibleItems = breakdown.items.slice(pageStart, pageStart + PAGE_SIZE);

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4 lg:col-span-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-gray-600">Expenses in category</h3>
          <p className="mt-1 text-xs text-gray-400">
            All subcategories, sorted by highest spending.
          </p>
        </div>
        <label htmlFor={selectId} className="flex flex-col gap-1 text-xs text-gray-500">
          Top-level category
          <select
            id={selectId}
            value={root ? categoryKey(root.category_id) : ""}
            disabled={!root}
            onChange={(event) => {
              setSelectedKey(event.target.value);
              setRequestedPage(1);
            }}
            className="w-full rounded border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 sm:w-64"
          >
            {!root && <option value="">No categories in period</option>}
            {data.by_top_level_category.map((item) => (
              <option key={categoryKey(item.category_id)} value={categoryKey(item.category_id)}>
                {item.category_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {breakdown.items.length > 0 ? (
        <>
          <div className="mt-4 grid grid-cols-1 items-center gap-4 lg:grid-cols-2">
            <div>
              <p className="text-center text-xs text-gray-500">
                Net spending · {root?.category_name}
                <span className="mt-1 block text-xl font-semibold text-gray-800">
                  {formatEur(breakdown.totalExpense)}
                </span>
              </p>
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={112}
                      isAnimationActive={false}
                    >
                      {pieData.map((item, index) => (
                        <Cell
                          key={categoryKey(item.categoryId)}
                          fill={CATEGORY_COLORS[index % CATEGORY_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip formatter={(value: number) => formatEur(value)} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="flex h-[280px] items-center justify-center text-sm text-gray-400">
                  No positive net spending to display.
                </p>
              )}
            </div>

            <div className="min-w-0">
              <ol start={pageStart + 1} className="space-y-1 text-sm">
                {visibleItems.map((item, index) => (
                  <li
                    key={categoryKey(item.categoryId)}
                    className="flex min-h-9 items-center gap-2 border-b border-gray-100 py-1.5"
                  >
                    <span className="w-5 shrink-0 text-right text-xs text-gray-400">
                      {pageStart + index + 1}.
                    </span>
                    <span
                      aria-hidden="true"
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: item.value > 0
                        ? CATEGORY_COLORS[(pageStart + index) % CATEGORY_COLORS.length]
                        : "#d1d5db" }}
                    />
                    <span className="min-w-0 flex-1 break-words text-gray-600">{item.name}</span>
                    <span className="shrink-0 text-right">
                      <span className="font-medium text-gray-800">{formatEur(item.expense)}</span>
                      <span className="ml-2 inline-block w-12 text-xs text-gray-400">
                        {item.percentage === null ? "—" : `${item.percentage.toFixed(1)}%`}
                      </span>
                    </span>
                  </li>
                ))}
              </ol>
              {pageCount > 1 && (
                <nav
                  aria-label="Category expense pages"
                  className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500"
                >
                  <span aria-live="polite">
                    {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, breakdown.items.length)} of {breakdown.items.length}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      disabled={page === 1}
                      onClick={() => setRequestedPage(page - 1)}
                      className="rounded border border-gray-300 px-2 py-1 hover:bg-gray-50 disabled:opacity-40"
                    >
                      Previous
                    </button>
                    <span>{page}/{pageCount}</span>
                    <button
                      type="button"
                      disabled={page === pageCount}
                      onClick={() => setRequestedPage(page + 1)}
                      className="rounded border border-gray-300 px-2 py-1 hover:bg-gray-50 disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                </nav>
              )}
            </div>
          </div>
          {breakdown.hasRefunds && (
            <p className="mt-3 text-xs text-gray-500">
              Categories with net refunds remain in the list as negative amounts. The pie chart and percentages include only categories with positive net spending.
            </p>
          )}
        </>
      ) : (
        <p className="flex h-48 items-center justify-center text-sm text-gray-400">
          No expenses in this category for the selected period.
        </p>
      )}
    </section>
  );
}
