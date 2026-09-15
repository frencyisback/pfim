import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";

/** Recurring portfolio costs (stamp duty, custody, account fees),
 * specification §11.5. These are not tied to an individual trade. */
export const PORTFOLIO_COST_TYPES = [
  { value: "stamp_duty", label: "Stamp duty" },
  { value: "custody_fee", label: "Custody fee" },
  { value: "account_fee", label: "Securities account fee" },
  { value: "other", label: "Other cost" },
] as const;

export function portfolioCostTypeLabel(type: string): string {
  return PORTFOLIO_COST_TYPES.find((t) => t.value === type)?.label ?? type;
}

export interface PortfolioCost {
  id: number;
  date: string;
  cost_type: string;
  account_id: number;
  description: string | null;
  amount: string;
  currency: string;
  /** Never null: conversion occurs at entry time. */
  fx_rate: string;
  amount_eur: string;
  notes: string | null;
}

export interface PortfolioCostPayload {
  date: string;
  cost_type: string;
  account_id: number;
  description?: string | null;
  amount: string;
  currency?: string;
  /** Required when currency is not EUR. */
  fx_rate?: string | null;
}

/** Costs affect cash: also invalidate balances, transactions and reports. */
function useCostMutation<TArgs>(fn: (args: TArgs) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["portfolio-costs"] });
      qc.invalidateQueries({ queryKey: ["transactions"] });
      qc.invalidateQueries({ queryKey: ["accounts"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function usePortfolioCosts() {
  return useQuery({
    queryKey: ["portfolio-costs"],
    queryFn: () => apiFetch<PortfolioCost[]>("/portfolio-costs"),
  });
}

export function useCreatePortfolioCost() {
  return useCostMutation((data: PortfolioCostPayload) =>
    apiFetch<PortfolioCost>("/portfolio-costs", {
      method: "POST",
      body: JSON.stringify(data),
    })
  );
}

export function useDeletePortfolioCost() {
  return useCostMutation((id: number) =>
    apiFetch<void>(`/portfolio-costs/${id}`, { method: "DELETE" })
  );
}
