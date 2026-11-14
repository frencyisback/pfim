import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { useCostsAnalysis, type CostsAnalysisReport } from "@/api/reports";
import { formatEur } from "@/lib/formatters";
import { CostsAnalysisTab } from "./CostsAnalysisTab";

vi.mock("@/api/reports", () => ({ useCostsAnalysis: vi.fn() }));
vi.mock("./TaxEventsSection", () => ({ TaxEventsSection: () => null }));

const report: CostsAnalysisReport = {
  period_from: "2025-02-01",
  period_to: "2025-02-28",
  realized: { capital_gains: "80", capital_losses: "0", net_realized: "80", income_gross: "0", gross_result: "80" },
  fiscal: {
    capital_gains: "80", capital_losses: "0", net_capital_gain_loss: "80", tax_rate_pct: "25",
    gross_estimated_tax: "20", tax_already_withheld: "0", estimated_tax_due: "20", dividend_withholding: "0",
  },
  unrealized_tax: {
    opening: { as_of: "2025-01-31", open_positions: 1, missing_price_tickers: [], net_unrealized_eur: "20", estimated_tax_eur: "5" },
    closing: { as_of: "2025-02-28", open_positions: 2, missing_price_tickers: [], net_unrealized_eur: "60", estimated_tax_eur: "15" },
    unrealized_change_eur: "40", tax_change_eur: "10", projected_period_costs_eur: "32",
    economic_gross_result_eur: "120", projected_cost_impact_pct: "26.6667",
  },
  total_costs: "22",
  total_estimated: "20",
  groups: [],
  net_result: "58",
  impact: {
    period_days: 28, average_invested_capital: "1000", average_portfolio_value: "1100",
    average_quoted_portfolio_value: "1100", pct_of_invested: "2.2", pct_of_gross_result: "27.5",
    annual_incidence_pct: "26.0714", twr_gross: "0.1", twr_net: "0.08", twr_drag_pct_points: "2",
    projected_pct_of_invested: "3.2", projected_annual_incidence_pct: "37.9221",
    estimated_twr_net: "0.065", estimated_twr_drag_pct_points: "3.5",
  },
  current_stamp_duty_estimate: null,
  disclaimer: "",
};

function renderReport(changes: Partial<CostsAnalysisReport> = {}) {
  vi.mocked(useCostsAnalysis).mockReturnValue({
    data: { ...report, ...changes }, isLoading: false, error: null,
  } as ReturnType<typeof useCostsAnalysis>);
  return renderToStaticMarkup(<CostsAnalysisTab />);
}

function text(markup: string) {
  return markup.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

const projection = report.unrealized_tax;

describe("Costs and Taxation", () => {
  it("puts the change in open gains beside capital gains and includes it only in gross result", () => {
    const result = text(renderReport());
    expect(result).toContain("Investment result (gross)");
    expect(result).toMatch(/Capital gains \? 80,00 € .* Unrealised gain\/loss \? 40,00 € .* Capital losses \? 0,00 €/);
    expect(result).toContain("Gross result ? 120,00 €");
    expect(result).toContain("Total incurred costs ? 22,00 €");
    expect(result).toContain("Net realised result ? 58,00 €");
    expect(result).toContain("Estimated tax still payable -20,00 €");
  });

  it("shows a single closing balance, including all decimals in the configured tax rate", () => {
    const markup = renderReport({ fiscal: { ...report.fiscal, tax_rate_pct: "25.0012" } });
    const table = markup.split("Estimated tax on open positions")[1].split("</table>")[0];
    expect(table.match(/<tr[\s>]/g)).toHaveLength(2); // Header and closing row.
    expect(text(table)).toContain("2025-02-28 2 60,00 € 15,00 €");
    expect(table).not.toContain("Opening");
    expect(table).not.toContain("2025-01-31");
    expect(text(markup)).toContain("Tax at 25.0012%");
    expect(text(table)).toContain("configured 25.0012% rate");
  });

  it("combines the six KPIs and displays the adjusted numerators, denominators and dates", () => {
    const page = renderReport();
    const markup = page.split(">Impact on performance</h3>")[1].split("</section>")[0];
    const impact = text(markup);
    expect(impact).toContain("Days included 28 2025-02-01 – 2025-02-28");
    expect(impact).toContain(text(`Average invested capital (FIFO) ${formatEur(1000)}`));
    expect(impact).toContain(text(`Average portfolio value ${formatEur(1100)}`));
    expect(impact).toContain("Realised gross result 80,00 €");
    expect(impact).toContain("Unrealised gain/loss for the period 40,00 €");
    expect(impact).toContain("Gross result 120,00 €");
    expect(impact).toContain("Incurred costs 22,00 €");
    expect(impact).toContain("Change in estimated tax 10,00 € Capital gains tax rate 25.00%");
    expect(impact).toContain("Costs including tax change 32,00 €");
    expect(impact).toContain("Relative to invested capital ? 3.20%");
    expect(impact).toContain("Relative to gross result ? 26.67%");
    expect(impact).toContain("Annual cost ratio (TER-like) ? 37.92%");
    expect(impact).toContain("TWR before costs ? 10,00%");
    expect(impact).toContain("TWR after costs (estimated) ? 6,50%");
    expect(impact).toContain("Return reduction ? 3,50 p.p.");
    expect(markup).not.toMatch(/<details|<button|aria-expanded/);
    expect(page).not.toContain("Cost impact including unrealised gains and losses");
    expect(page).not.toContain("Relative to realised gross result");
  });

  it.each(["opening", "closing"] as const)("identifies missing %s quotes and keeps the realised net independent", (boundary) => {
    const result = text(renderReport({
      unrealized_tax: {
        ...projection,
        [boundary]: { ...projection[boundary], missing_price_tickers: ["ABC", "DEF"], estimated_tax_eur: null, net_unrealized_eur: null },
        unrealized_change_eur: null, projected_period_costs_eur: null, tax_change_eur: null,
        economic_gross_result_eur: null, projected_cost_impact_pct: null,
      },
      impact: {
        ...report.impact, projected_pct_of_invested: null, projected_annual_incidence_pct: null,
        estimated_twr_net: null, estimated_twr_drag_pct_points: null,
      },
    }));
    const warning = boundary === "opening" ? "Opening valuation unavailable at 2025-01-31." : "Closing valuation unavailable.";
    expect(result).toContain(`${warning} Missing EUR prices for ABC, DEF.`);
    expect(result).toContain(boundary === "opening" ? "2025-02-28 2 60,00 € 15,00 €" : "2025-02-28 2 — —");
    expect(result).toContain("Unrealised gain/loss ? —");
    expect(result).toContain("Gross result ? —");
    expect(result).toContain("Net realised result ? 58,00 €");
    expect(result).toContain("Relative to invested capital ? —");
    expect(result).toContain("Relative to gross result ? —");
    expect(result).toContain("Annual cost ratio (TER-like) ? —");
    expect(result).toContain("TWR after costs (estimated) ? —");
    expect(result).toContain("Return reduction ? —");
  });

  it("shows the closing tax balance even when the period has no change and a zero gross result", () => {
    const result = text(renderReport({
      realized: { capital_gains: "0", capital_losses: "0", net_realized: "0", income_gross: "0", gross_result: "0" },
      total_costs: "0", net_result: "0",
      unrealized_tax: {
        ...projection, opening: { ...projection.closing, as_of: projection.opening.as_of },
        unrealized_change_eur: "0", tax_change_eur: "0", projected_period_costs_eur: "0",
        economic_gross_result_eur: "0", projected_cost_impact_pct: null,
      },
      impact: { ...report.impact, projected_pct_of_invested: "0", projected_annual_incidence_pct: "0",
        twr_gross: "0", estimated_twr_net: "0", estimated_twr_drag_pct_points: "0" },
    }));
    expect(result).toContain("2025-02-28 2 60,00 € 15,00 €");
    expect(result).toContain("Unrealised gain/loss ? 0,00 €");
    expect(result).toContain("Gross result ? 0,00 €");
    expect(result).toContain("Relative to invested capital ? 0.00%");
    expect(result).toContain("Relative to gross result ? —");
    expect(result).toContain("Return reduction ? 0,00 p.p.");
  });

  it("shows unavailable market-value and TWR metrics even with complete period-end balances", () => {
    const result = text(renderReport({
      impact: { ...report.impact, average_quoted_portfolio_value: null, projected_annual_incidence_pct: null,
        estimated_twr_net: null, estimated_twr_drag_pct_points: null },
    }));
    expect(result).toContain("Average portfolio value —");
    expect(result).toContain("Annual cost ratio (TER-like) ? —");
    expect(result).toContain("Relative to gross result ? 26.67%");
    expect(result).toContain("TWR before costs ? 10,00%");
    expect(result).toContain("TWR after costs (estimated) ? —");
  });

  it("displays a release of estimated tax and a negative difference between TWRs", () => {
    const result = text(renderReport({
      unrealized_tax: {
        ...projection, opening: { ...projection.opening, net_unrealized_eur: "160", estimated_tax_eur: "40" },
        unrealized_change_eur: "-100", tax_change_eur: "-25", projected_period_costs_eur: "-3",
        economic_gross_result_eur: "120", projected_cost_impact_pct: "-2.5",
      },
      realized: { ...report.realized, income_gross: "140", gross_result: "220" }, net_result: "198",
      impact: { ...report.impact, projected_pct_of_invested: "-0.3", estimated_twr_net: "0.105", estimated_twr_drag_pct_points: "-0.5" },
    }));
    expect(result).toContain("Unrealised gain/loss ? -100,00 €");
    expect(result).toContain("Change in estimated tax -25,00 €");
    expect(result).toContain("Costs including tax change -3,00 €");
    expect(result).toContain("Relative to gross result ? -2.50%");
    expect(result).toContain("Relative to invested capital ? -0.30%");
    expect(result).toContain("Return reduction ? -0,50 p.p.");
  });
});
