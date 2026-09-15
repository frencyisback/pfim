import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CategoryAnalysisReport } from "@/api/reports";
import { SpendingCategoryBreakdown } from "./SpendingCategoryBreakdown";

const data: CategoryAnalysisReport = {
  period_from: null,
  period_to: null,
  total_amount: "-78",
  by_top_level_category: [{ category_id: 1, category_name: "Example housing", total_amount: "-78", pct_of_total: "100" }],
  by_category: [],
  by_category_detail: Array.from({ length: 12 }, (_, index) => ({
    category_id: index + 10,
    top_level_category_id: 1,
    category_name: `Item ${index + 1}`,
    total_amount: String(-(index + 1)),
    pct_of_total: "0",
  })),
  by_month: [],
  top_transactions: [],
};

describe("category expense list", () => {
  it("shows eight sorted rows and makes subsequent pages available", () => {
    const html = renderToStaticMarkup(<SpendingCategoryBreakdown data={data} />);
    expect(html.match(/<li /g)).toHaveLength(8);
    expect(html.indexOf("Item 12")).toBeLessThan(html.indexOf("Item 11"));
    expect(html).toContain("Item 5");
    expect(html).not.toContain("Item 4");
    expect(html).toContain("1–8 of 12");
    expect(html).toContain("Next");
    expect(html).toContain("78,00");
  });

  it("shows an empty state without a dummy page or pie chart", () => {
    const html = renderToStaticMarkup(<SpendingCategoryBreakdown data={{
      ...data, total_amount: "0", by_top_level_category: [], by_category_detail: [],
    }} />);
    expect(html).toContain("No categories in period");
    expect(html).toContain("No expenses in this category");
    expect(html).not.toContain("Next");
  });
});
