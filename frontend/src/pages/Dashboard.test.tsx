import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useIncomeStatement } from "@/api/reports";
import Dashboard from "./Dashboard";
import Portfolio from "./Portfolio";

const { portfolio } = vi.hoisted(() => ({ portfolio: vi.fn() }));
vi.mock("@/api/portfolio", () => ({
  usePositions: () => ({ data: [], isLoading: false, error: null }),
  usePortfolioSummary: portfolio,
}));
vi.mock("@/api/reports", () => ({
  useNetWorth: () => ({ error: new Error("Offline"), isLoading: false }),
  useIncomeStatement: vi.fn(() => ({ data: { periods: [] }, isLoading: false })),
}));
vi.mock("@/lib/useTodayIso", () => ({ useTodayIso: () => "2026-02-12" }));

describe("financial overview", () => {
  it("shows unavailable amounts after a failed read and requests six calendar months", () => {
    portfolio.mockReturnValue({ error: new Error("Offline"), isLoading: false });
    const html = renderToStaticMarkup(<Dashboard />);
    expect(html).toContain("Offline");
    expect(html.match(/>—<\/div>/g)).toHaveLength(4);
    expect(useIncomeStatement).toHaveBeenCalledWith({ from: "2025-09-01", to: "2026-02-12" });
  });

  it("keeps realised earnings visible when every security has been sold", () => {
    portfolio.mockReturnValue({ data: {
      positions_count: 0, total_invested: "0", total_current_value: "0",
      total_unrealized_gain_loss: "0", total_realized_gain_loss: "20",
      portfolio_valuation: { cost_fallback_used: false, cost_fallback_securities: [] },
    } });
    const html = renderToStaticMarkup(<Portfolio />);
    expect(html).toContain("Realised gain/loss");
    expect(html).toContain("20,00");
  });
});
