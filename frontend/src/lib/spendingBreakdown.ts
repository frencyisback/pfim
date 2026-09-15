import type { CategoryAnalysisDetailItem } from "@/api/reports";

export interface SpendingBreakdownItem {
  categoryId: number | null;
  name: string;
  expense: number;
  value: number;
  percentage: number | null;
}

/** The report provides signed amounts and one row per assigned category. */
export function spendingBreakdown(
  items: CategoryAnalysisDetailItem[],
  rootId: number | null,
): {
  items: SpendingBreakdownItem[];
  totalExpense: number;
  hasRefunds: boolean;
} {
  const rows = items
    .filter((item) => item.top_level_category_id === rootId)
    .map((item) => {
      const expense = -Number(item.total_amount);
      return {
        categoryId: item.category_id,
        name: item.category_name,
        expense: expense === 0 ? 0 : expense,
        value: Math.max(0, expense),
        percentage: null as number | null,
      };
    })
    .sort((left, right) =>
      right.expense - left.expense || left.name.localeCompare(right.name, "it"),
    );
  const totalSlices = rows.reduce((sum, row) => sum + row.value, 0);

  return {
    items: rows.map((row) => ({
      ...row,
      percentage: row.value > 0 && totalSlices > 0 ? row.value / totalSlices * 100 : null,
    })),
    totalExpense: rows.reduce((sum, row) => sum + row.expense, 0),
    hasRefunds: rows.some((row) => row.expense < 0),
  };
}
