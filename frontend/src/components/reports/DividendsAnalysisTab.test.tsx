import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DividendsAnalysisReport } from "@/api/reports";
import { useDividendsAnalysis } from "@/api/reports";
import { DividendsAnalysisTab } from "./DividendsAnalysisTab";

vi.mock("@/api/reports", () => ({ useDividendsAnalysis: vi.fn() }));

const empty: DividendsAnalysisReport = {
  period_from: "2026-01-01", period_to: "2026-01-01", total_gross: "0", total_net: "0",
  total_tax: "0", tax_incidence_pct: null, events_count: 0, first_event_date: null,
  last_event_date: null, trailing_12m_net: "23", portfolio_yield_on_cost_pct: "23",
  average_monthly_net: null, by_year: [], by_month: [], by_security: [], by_security_type: [], by_event_type: [],
};

function query(data: DividendsAnalysisReport) {
  vi.mocked(useDividendsAnalysis).mockReturnValue({ data, isLoading: false, error: null } as ReturnType<typeof useDividendsAnalysis>);
}

describe("income KPIs independent of the table", () => {
  beforeEach(() => vi.clearAllMocks());

  it("preserves trailing income and yield when the selected period has no receipts", () => {
    query(empty);
    const html = renderToStaticMarkup(<DividendsAnalysisTab />);
    expect(html).toContain("No coupons or dividends recorded in this period");
    expect(html).toContain("Last 12 months");
    expect(html).toContain("Yield on cost over the last 12 months");
    expect(html).toContain("23,00");
    expect(html).toContain("23.00%");
    expect(html).not.toContain("Yearly accumulation");
  });

  it("distinguishes zero yield from an unavailable yield", () => {
    query({ ...empty, trailing_12m_net: "0", portfolio_yield_on_cost_pct: "0" });
    expect(renderToStaticMarkup(<DividendsAnalysisTab />)).toContain("0.00%");
    query({ ...empty, trailing_12m_net: "0", portfolio_yield_on_cost_pct: null });
    const html = renderToStaticMarkup(<DividendsAnalysisTab />);
    expect(html).not.toContain("0.00%");
    expect(html).toContain("—");
  });
});
