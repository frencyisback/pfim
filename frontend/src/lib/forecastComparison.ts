import type { ForecastRunResult } from "@/api/forecasts";

export interface ForecastComparisonSeries {
  id: number;
  dataKey: string;
  label: string;
}

/** Names are labels; only IDs identify comparison series. */
export function buildForecastComparison(results: ForecastRunResult[]) {
  const nameCounts = new Map<string, number>();
  for (const result of results) {
    nameCounts.set(result.scenario_name, (nameCounts.get(result.scenario_name) ?? 0) + 1);
  }
  const series: ForecastComparisonSeries[] = results.map((result) => ({
    id: result.scenario_id,
    dataKey: `scenario_${result.scenario_id}`,
    label: (nameCounts.get(result.scenario_name) ?? 0) > 1
      ? `${result.scenario_name} (#${result.scenario_id})`
      : result.scenario_name,
  }));
  const maxYears = Math.max(0, ...results.map((result) => result.scenarios.base.years.length));
  const data = Array.from({ length: maxYears }, (_, index) => {
    const row: Record<string, number | string> = { year: `+${index + 1}` };
    results.forEach((result, seriesIndex) => {
      const year = result.scenarios.base.years[index];
      // Do not create artificial values beyond a scenario's horizon.
      if (year) row[series[seriesIndex].dataKey] = Number(year.net_worth);
    });
    return row;
  });
  return { data, series };
}
