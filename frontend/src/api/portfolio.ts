import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { PortfolioSummary, Position } from "./types";

export function usePositions() {
  return useQuery({
    queryKey: ["portfolio", "positions"],
    queryFn: () => apiFetch<Position[]>("/portfolio"),
  });
}

export function usePortfolioSummary() {
  return useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => apiFetch<PortfolioSummary>("/portfolio/summary"),
  });
}
