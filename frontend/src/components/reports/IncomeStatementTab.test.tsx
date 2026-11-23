import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useIncomeStatement, type IncomeStatementReport } from "@/api/reports";
import { IncomeStatementTab } from "./IncomeStatementTab";

vi.mock("@/api/reports", () => ({ useIncomeStatement: vi.fn() }));

const report: IncomeStatementReport = {
  periods: [],
  total_income: "250",
  total_expense: "-125",
  net: "125",
  average_savings_rate_pct: "50",
  savings_rate_months: 1,
  economic_income: "250",
  economic_spending: "125",
  economic_savings: "125",
  economic_savings_rate_pct: "50",
};

function tooltip(label: string, nextLabel: string) {
  vi.mocked(useIncomeStatement).mockReturnValue({
    data: report, isLoading: false, error: null,
  } as ReturnType<typeof useIncomeStatement>);
  const html = renderToStaticMarkup(<IncomeStatementTab />);
  const card = html.split(`>${label}<`)[1]?.split(`>${nextLabel}<`)[0] ?? "";
  const content = card.split('role="tooltip"')[1];
  expect(content, `Calculation tooltip for ${label}`).toBeDefined();
  return content?.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

describe("income statement calculation tooltips", () => {
  it("explains net investment income and excludes security proceeds and transfers", () => {
    const text = tooltip("Economic income", "Economic spending");
    expect(text).toContain("Ordinary income + net dividends + net coupons");
    expect(text).toContain("after withholding");
    expect(text).toContain("Security sales, repayments of principal and transfers between your own accounts are excluded");
  });

  it("includes trade fees, recurring costs and withholding on returned principal in spending", () => {
    const text = tooltip("Economic spending", "Economic savings");
    expect(text).toContain("Ordinary expenses + trade costs + recurring portfolio costs + tax withheld on returned principal");
    expect(text).toContain("recorded commissions, spreads and transaction taxes");
    expect(text).toContain("Trade principal and transfers between your own accounts are excluded");
  });
});
