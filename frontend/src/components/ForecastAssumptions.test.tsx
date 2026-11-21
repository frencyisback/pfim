import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { ForecastRunResult, ForecastScenario } from "@/api/forecasts";
import ForecastAssumptions from "./ForecastAssumptions";

const cashFlow = {
  monthly_income: "2567.80",
  monthly_expenses: "1954.30",
  income_growth_rate_annual: "0.015",
  expense_growth_rate_annual: "0.025",
  monthly_savings_to_invest: null,
};

function scenario(parameters: ForecastScenario["parameters"] = {}): ForecastScenario {
  return {
    id: 17,
    name: "Household plan",
    description: null,
    base_date: "2024-01-31",
    horizon_years: 9,
    parameters: {
      starting_net_worth: "auto",
      cash_flow: cashFlow,
      portfolio: {
        expected_annual_return: "0.05",
        return_optimistic: "0.08",
        return_pessimistic: "-0.02",
      },
      contributions: [],
      ...parameters,
    },
  };
}

function visibleText(saved: ForecastScenario, result?: ForecastRunResult) {
  const html = renderToStaticMarkup(<ForecastAssumptions scenario={saved} result={result} />);
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

describe("saved forecast assumptions", () => {
  it("shows the manual opening amount and the saved cash-flow and return assumptions before running", () => {
    const text = visibleText(scenario({ starting_net_worth: "-12345.67" }));
    expect(text).toContain("Base date 2024-01-31");
    expect(text).toContain("Horizon 9 years");
    expect(text).toContain("Starting net worth Custom · -12.345,67 €");
    expect(text).toMatch(/Monthly income 2\.?567,80 €/);
    expect(text).toMatch(/Monthly expenses 1\.?954,30 €/);
    expect(text).toContain("Annual income growth 1,50%");
    expect(text).toContain("Annual expense growth 2,50%");
    expect(text).toContain("Pessimistic annual return -2,00%");
    expect(text).toContain("Base annual return 5,00%");
    expect(text).toContain("Optimistic annual return 8,00%");
  });

  it("discloses automatic mode before running and displays the resolved opening cash and holdings afterwards", () => {
    const saved = scenario();
    const before = visibleText(saved);
    expect(before).toContain("Starting net worth Automatic");
    expect(before).not.toContain("Opening cash");
    expect(before).not.toContain("Opening portfolio value");
    const projection = { scenario: "base", years: [], milestones_reached: {} };
    const result = {
      scenario: saved,
      scenario_id: saved.id,
      scenario_name: saved.name,
      opening_cash: "3210.45",
      opening_portfolio_value: "8765.43",
      opening_net_worth: "11975.88",
      scenarios: { pessimistic: projection, base: projection, optimistic: projection },
    };
    const after = visibleText(saved, result);
    expect(after).toMatch(/Opening cash 3\.?210,45 €/);
    expect(after).toMatch(/Opening portfolio value 8\.?765,43 €/);
    expect(after).toContain("Starting net worth Automatic · 11.975,88 €");
  });

  it("displays a custom monthly investment alongside dated contributions and withdrawals", () => {
    const text = visibleText(scenario({
      cash_flow: { ...cashFlow, monthly_savings_to_invest: "321.50" },
      contributions: [
        { date: "2026-06-01", amount: "1200.75", label: "Bonus" },
        { date: "2027-03-10", amount: "-580.25", label: "Car repair" },
      ],
    }));
    expect(text).toContain("Monthly savings to invest 321,50 €");
    expect(text).toMatch(/2026-06-01 · Bonus 1\.?200,75 €/);
    expect(text).toContain("2027-03-10 · Car repair -580,25 €");
  });

  it("keeps a legacy record readable when numeric or nested fields are missing", () => {
    const saved = scenario({
      starting_net_worth: "unknown",
      cash_flow: null,
      portfolio: { expected_annual_return: "unavailable" },
      contributions: [null],
    });
    const text = visibleText(saved);
    expect(text).not.toMatch(/NaN|Infinity|\[object Object\]/);
    expect(text).toContain("Starting net worth Custom · Unavailable");
    expect(text).toContain("Monthly income Unavailable");
    expect(text).toContain("Base annual return Unavailable");
  });

  it("uses the engine defaults for omitted optional fields on older saved scenarios", () => {
    const saved = scenario();
    saved.parameters = {
      cash_flow: { monthly_income: 2000, monthly_expenses: 1500 },
      portfolio: saved.parameters.portfolio,
    };
    const text = visibleText(saved);
    expect(text).toContain("Starting net worth Automatic");
    expect(text).toContain("Monthly savings to invest Automatic");
    expect(text).toContain("Annual income growth 0,00%");
    expect(text).toContain("Annual expense growth 0,00%");
    expect(text).toMatch(/Monthly income 2\.?000,00 €/);
    expect(text).toContain("Scheduled contributions and withdrawals None");
  });

  it("preserves explicit zero amounts for manual starting wealth and fixed monthly investment", () => {
    const text = visibleText(scenario({
      starting_net_worth: 0,
      cash_flow: { ...cashFlow, monthly_savings_to_invest: 0 },
    }));
    expect(text).toContain("Starting net worth Custom · 0,00 €");
    expect(text).toContain("Monthly savings to invest 0,00 €");
  });
});
