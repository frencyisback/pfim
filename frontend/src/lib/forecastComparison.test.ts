import { describe, expect, it } from "vitest";
import type { ForecastRunResult, ScenarioProjection } from "@/api/forecasts";
import { buildForecastComparison } from "./forecastComparison";

function result(id: number, name: string, amounts: string[]): ForecastRunResult {
  const base: ScenarioProjection = {
    scenario: "base",
    milestones_reached: {},
    years: amounts.map((amount, index) => ({
      year_index: index + 1,
      date: `${2027 + index}-06-01`,
      net_worth: amount,
      cash_balance: "0",
      portfolio_value: amount,
    })),
  };
  return {
    scenario_id: id,
    scenario_name: name,
    scenarios: { base, optimistic: base, pessimistic: base },
  };
}

describe("forecast comparison", () => {
  it("keeps values with matching names distinct and clarifies legends and tooltips", () => {
    const comparison = buildForecastComparison([
      result(12, "Example retirement", ["100", "120"]),
      result(45, "Example retirement", ["500", "650"]),
    ]);
    expect(comparison.data).toEqual([
      { year: "+1", scenario_12: 100, scenario_45: 500 },
      { year: "+2", scenario_12: 120, scenario_45: 650 },
    ]);
    expect(comparison.series).toEqual([
      { id: 12, dataKey: "scenario_12", label: "Example retirement (#12)" },
      { id: 45, dataKey: "scenario_45", label: "Example retirement (#45)" },
    ]);
  });

  it("treats year and __proto__ as ordinary labels without collisions", () => {
    const comparison = buildForecastComparison([
      result(3, "year", ["80"]), result(4, "__proto__", ["90"]),
    ]);
    expect(comparison.data).toEqual([{ year: "+1", scenario_3: 80, scenario_4: 90 }]);
    expect(comparison.series.map((series) => series.label)).toEqual(["year", "__proto__"]);
    expect(Object.getPrototypeOf(comparison.data[0])).toBe(Object.prototype);
  });

  it("preserves ID and value correspondence when scenario order changes", () => {
    const results = [result(2, "Same name", ["-20"]), result(1, "Same name", ["0"])];
    const original = buildForecastComparison(results);
    const reversed = buildForecastComparison([...results].reverse());
    expect(original.data).toEqual(reversed.data);
    expect(original.series).toEqual([...reversed.series].reverse());
  });

  it("ends the shorter series without zeros or truncating the other", () => {
    const comparison = buildForecastComparison([
      result(1, "Short", ["0"]), result(2, "Long", ["10", "20", "30"]),
    ]);
    expect(comparison.data).toEqual([
      { year: "+1", scenario_1: 0, scenario_2: 10 },
      { year: "+2", scenario_2: 20 },
      { year: "+3", scenario_2: 30 },
    ]);
    expect(comparison.data[1]).not.toHaveProperty("scenario_1");
  });

  it("produces an empty chart without results", () => {
    expect(buildForecastComparison([])).toEqual({ data: [], series: [] });
  });
});
