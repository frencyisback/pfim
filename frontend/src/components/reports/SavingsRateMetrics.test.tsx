import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useIncomeStatement, type IncomeStatementReport } from "@/api/reports";
import { SavingsRateMetrics } from "./SavingsRateMetrics";

vi.mock("@/api/reports", () => ({ useIncomeStatement: vi.fn() }));

function render(average: string | null, months: number) {
  const data: IncomeStatementReport = {
    periods: [], total_income: "0", total_expense: "0", net: "0",
    average_savings_rate_pct: average, savings_rate_months: months,
  };
  vi.mocked(useIncomeStatement).mockReturnValue({ data, isLoading: false, error: null } as ReturnType<typeof useIncomeStatement>);
  return renderToStaticMarkup(<SavingsRateMetrics />);
}

describe("average indicator in net worth", () => {
  it("shows the API average, sample and filters without recalculating rates", () => {
    const html = render("-12.5", 3);
    expect(html).toContain("-12,50%");
    expect(html).toContain("3 months with inflows");
    expect(html).toContain("all history");
    expect(html).toContain("percentiles P5–P95 as in average spending");
    expect(html).toContain("1 month");
    expect(html).toContain("3 months");
  });

  it("distinguishes a zero rate from an unavailable rate", () => {
    expect(render("0", 1)).toContain("0,00%");
    const html = render(null, 0);
    expect(html).toContain("—");
    expect(html).toContain("No months with inflows");
    expect(html).not.toContain("0,00%");
  });
});
