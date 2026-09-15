import { describe, expect, it } from "vitest";
import type { CategoryAnalysisDetailItem } from "@/api/reports";
import { spendingBreakdown } from "./spendingBreakdown";

function category(
  id: number | null,
  rootId: number | null,
  amount: number,
): CategoryAnalysisDetailItem {
  return {
    category_id: id,
    top_level_category_id: rootId,
    category_name: `Category ${id ?? "uncategorised"}`,
    total_amount: String(amount),
    pct_of_total: "0",
  };
}

describe("expense detail by top-level category", () => {
  it("includes categories beyond the top 10 and expenses assigned to the root", () => {
    const children = Array.from({ length: 12 }, (_, index) => category(index + 10, 1, -(index + 1)));
    const source = [category(1, 1, -20), ...children, category(2, 2, -100)];
    const result = spendingBreakdown(source, 1);

    expect(result.items).toHaveLength(13);
    expect(result.items.map((item) => item.expense)).toEqual([20, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]);
    expect(result.totalExpense).toBe(98);
    expect(result.items.reduce((sum, item) => sum + (item.percentage ?? 0), 0)).toBeCloseTo(100);
    expect(source[0].total_amount).toBe("-20");
  });

  it("keeps refunds and zero-balance categories without turning them into pie chart expenses", () => {
    const result = spendingBreakdown([
      category(11, 1, -90), category(12, 1, 20), category(13, 1, 0), category(14, 1, -10),
    ], 1);

    expect(result.totalExpense).toBe(80);
    expect(result.hasRefunds).toBe(true);
    expect(result.items.map((item) => [item.expense, item.value, item.percentage])).toEqual([
      [90, 90, 90], [10, 10, 10], [0, 0, null], [-20, 0, null],
    ]);
  });

  it("keeps uncategorised expenses in a separate selection", () => {
    const source = [category(10, 1, -40), category(null, null, -25)];
    const result = spendingBreakdown(source, null);
    expect(result.items.map((item) => item.categoryId)).toEqual([null]);
    expect(result.totalExpense).toBe(25);
    expect(spendingBreakdown(source, 9).items).toEqual([]);
  });
});
