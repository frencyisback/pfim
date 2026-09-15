import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { PortfolioValuationMetadata } from "./reports";

export interface PerformanceMetrics {
  security_id: number;
  ticker: string;
  simple_return: string | null;
  total_return: string | null;
  money_weighted_return: string | null;
  yield_on_cost: string | null;
  current_yield: string | null;
  realized_gain_loss: string;
  total_income_received: string;
}

export interface PortfolioPerformance {
  total_invested: string;
  total_current_value: string;
  total_return: string | null;
  total_return_annualized: string | null;
  time_weighted_return: string | null;
  time_weighted_return_annualized: string | null;
  /** MWR/XIRR is already an annual rate; do not annualise it again. */
  money_weighted_return: string | null;
  investment_period_days: number | null;
  total_realized_gain_loss: string;
  total_income_received: string;
  by_security: PerformanceMetrics[];
  portfolio_valuation: PortfolioValuationMetadata;
}

export function usePortfolioPerformance() {
  return useQuery({
    queryKey: ["performance", "portfolio"],
    queryFn: () => apiFetch<PortfolioPerformance>("/performance/portfolio"),
  });
}
