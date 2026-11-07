import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useCostsAnalysis, type CostsAnalysisReport, type UnrealizedTaxProjection } from "@/api/reports";
import { CostsAnalysisTab } from "./CostsAnalysisTab";

vi.mock("@/api/reports", () => ({ useCostsAnalysis: vi.fn() }));
vi.mock("./TaxEventsSection", () => ({ TaxEventsSection: () => null }));

const projection: UnrealizedTaxProjection = {
  opening: { as_of: "2025-01-31", open_positions: 1, missing_price_tickers: [], net_unrealized_eur: "20", estimated_tax_eur: "5" },
  closing: { as_of: "2025-02-28", open_positions: 2, missing_price_tickers: [], net_unrealized_eur: "60", estimated_tax_eur: "15" },
  tax_change_eur: "10",
  projected_period_costs_eur: "32",
  economic_gross_result_eur: "120",
  projected_cost_impact_pct: "26.6667",
};

const report: CostsAnalysisReport = {
  period_from: "2025-02-01",
  period_to: "2025-02-28",
  realized: { capital_gains: "80", capital_losses: "0", net_realized: "80", income_gross: "0", gross_result: "80" },
  fiscal: {
    capital_gains: "80", capital_losses: "0", net_capital_gain_loss: "80", tax_rate_pct: "25",
    gross_estimated_tax: "20", tax_already_withheld: "0", estimated_tax_due: "20", dividend_withholding: "0",
  },
  unrealized_tax: projection,
  total_costs: "22",
  total_estimated: "20",
  groups: [],
  net_result: "58",
  impact: {
    pct_of_invested: null, pct_of_gross_result: "27.5", annual_incidence_pct: null, average_invested_capital: null,
    average_portfolio_value: null, period_days: 28, twr_gross: "0.1", twr_net: "0.08", twr_drag_pct_points: "2",
  },
  current_stamp_duty_estimate: null,
  disclaimer: "",
};

function reportText(unrealized_tax = projection, period: CostsAnalysisReport = report) {
  vi.mocked(useCostsAnalysis).mockReturnValue({
    data: { ...period, unrealized_tax }, isLoading: false, error: null,
  } as ReturnType<typeof useCostsAnalysis>);
  return renderToStaticMarkup(<CostsAnalysisTab />).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

describe("cost impact on open positions", () => {
  it("shows opening and closing reserves separately from incurred costs, realised tax and TWR", () => {
    const text = reportText();
    expect(text).toContain("Opening 2025-01-31 1 20,00 € 5,00 €");
    expect(text).toContain("Closing 2025-02-28 2 60,00 € 15,00 €");
    expect(text).toContain("25.00% tax");
    expect(text).toContain("Total incurred costs ? 22,00 €");
    expect(text).toContain("Estimated tax still payable -20,00 €");
    expect(text).toContain("Net realised result ? 58,00 €");
    expect(text).toContain("TWR before costs ? 10,00%");
    expect(text).toContain("TWR after costs ? 8,00%");
    expect(text).toContain("Return reduction ? −2,00 p.p.");
    expect(text).toContain("Change in estimated tax ? 10,00 €");
    expect(text).toContain("Costs including tax change ? 32,00 €");
    expect(text).toContain("Gross result including unrealised change ? 120,00 €");
    expect(text).toContain("Estimated share of gross result consumed by costs ? 26.67%");
  });

  it.each(["opening", "closing"] as const)("identifies missing prices in the %s valuation", (key) => {
    const text = reportText({
      ...projection,
      [key]: { ...projection[key], missing_price_tickers: ["ABC", "DEF"], estimated_tax_eur: null, net_unrealized_eur: null },
      projected_period_costs_eur: null, tax_change_eur: null, economic_gross_result_eur: null, projected_cost_impact_pct: null,
    });
    expect(text).toContain(`${projection[key].as_of} Missing EUR valuation for ABC, DEF. ${projection[key].open_positions} — —`);
    expect(text).toContain(key === "opening" ? "Closing 2025-02-28 2 60,00 € 15,00 €" : "Opening 2025-01-31 1 20,00 € 5,00 €");
    expect(text).toContain("Change in estimated tax ? —");
    expect(text).toContain("Costs including tax change ? —");
    expect(text).toContain("Gross result including unrealised change ? —");
    expect(text).toContain("Estimated share of gross result consumed by costs ? —");
    expect(text).toContain("Relative to realised gross result ? 27.5%");
  });

  it("shows the full configured rate for realised and hypothetical tax", () => {
    const text = reportText(projection, { ...report, fiscal: { ...report.fiscal, tax_rate_pct: "25.0012" } });
    expect(text).toContain("Tax at 25.0012%");
    expect(text).toContain("25.0012% tax on any net gain");
  });

  it("displays zero for empty positions without hiding the period's realised costs", () => {
    const empty = { open_positions: 0, missing_price_tickers: [], net_unrealized_eur: "0", estimated_tax_eur: "0" };
    const text = reportText({
      opening: { ...empty, as_of: null }, closing: { ...empty, as_of: "2025-02-28" },
      tax_change_eur: "0", projected_period_costs_eur: "22", economic_gross_result_eur: "80", projected_cost_impact_pct: "27.5",
    });
    expect(text).toContain("Opening Start of records 0 0,00 € 0,00 €");
    expect(text).toContain("Closing 2025-02-28 0 0,00 € 0,00 €");
    expect(text).toContain("Change in estimated tax ? 0,00 €");
    expect(text).toContain("Estimated share of gross result consumed by costs ? 27.50%");
    expect(text).not.toContain("Missing EUR valuation");
  });

  it("distinguishes an unprofitable period from a zero-cost period", () => {
    const text = reportText({
      ...projection, closing: { ...projection.closing, net_unrealized_eur: "-60", estimated_tax_eur: "0" },
      tax_change_eur: "-5", projected_period_costs_eur: "17", economic_gross_result_eur: "0", projected_cost_impact_pct: null,
    });
    expect(text).toContain("Gross result including unrealised change ? 0,00 €");
    expect(text).toContain("Estimated share of gross result consumed by costs ? —");
    const offset = reportText({
      ...projection, opening: { ...projection.opening, net_unrealized_eur: "88", estimated_tax_eur: "22" },
      closing: { ...projection.closing, net_unrealized_eur: "0", estimated_tax_eur: "0" },
      tax_change_eur: "-22", projected_period_costs_eur: "0", economic_gross_result_eur: "4", projected_cost_impact_pct: "0",
    }, { ...report, realized: { ...report.realized, income_gross: "12", gross_result: "92" }, net_result: "70" });
    expect(offset).toContain("Estimated share of gross result consumed by costs ? 0.00%");
  });

  it("preserves negative reserve movements and signed adjusted costs", () => {
    const text = reportText({
      ...projection,
      opening: { ...projection.opening, net_unrealized_eur: "160", estimated_tax_eur: "40" },
      tax_change_eur: "-25", projected_period_costs_eur: "-3", economic_gross_result_eur: "120", projected_cost_impact_pct: "-2.5",
    }, { ...report, realized: { ...report.realized, income_gross: "140", gross_result: "220" }, net_result: "198" });
    expect(text).toContain("Change in estimated tax ? -25,00 €");
    expect(text).toContain("Costs including tax change ? -3,00 €");
    expect(text).toContain("Estimated share of gross result consumed by costs ? -2.50%");
  });
});
