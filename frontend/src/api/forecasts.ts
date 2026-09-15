import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

export interface ForecastScenario {
  id: number;
  name: string;
  description: string | null;
  base_date: string;
  horizon_years: number;
  parameters: Record<string, unknown>;
}

export interface YearProjection {
  year_index: number;
  date: string;
  portfolio_value: string;
  cash_balance: string;
  net_worth: string;
}

export interface ScenarioProjection {
  scenario: string;
  years: YearProjection[];
  milestones_reached: Record<string, number>;
}

export interface ForecastRunResult {
  scenario_id: number;
  scenario_name: string;
  scenarios: {
    pessimistic: ScenarioProjection;
    base: ScenarioProjection;
    optimistic: ScenarioProjection;
  };
}

export function useForecastScenarios() {
  return useQuery({
    queryKey: ["forecast-scenarios"],
    queryFn: () => apiFetch<ForecastScenario[]>("/forecasts/scenarios"),
  });
}

export function useCreateForecastScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiFetch<ForecastScenario>("/forecasts/scenarios", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["forecast-scenarios"] }),
  });
}

export function useDeleteForecastScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/forecasts/scenarios/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["forecast-scenarios"] }),
  });
}

export function useRunForecast() {
  return useMutation({
    mutationFn: (id: number) => apiFetch<ForecastRunResult>(`/forecasts/run/${id}`, { method: "POST" }),
  });
}

export interface ForecastCompareResult {
  results: ForecastRunResult[];
}

/** Compare saved scenarios (specification §6.9).
 * Each scenario has three curves. Comparison overlays each base curve
 * to keep the chart readable when multiple scenarios are selected. */
export function useCompareForecasts() {
  return useMutation({
    mutationFn: (scenarioIds: number[]) =>
      apiFetch<ForecastCompareResult>("/forecasts/compare", {
        method: "POST",
        body: JSON.stringify({ scenario_ids: scenarioIds }),
      }),
  });
}
