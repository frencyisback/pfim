import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { IncomeEvent, IncomeEventsSummary } from "./types";

export function useIncomeEvents(securityId?: number) {
  const qs = securityId ? `?security_id=${securityId}` : "";
  return useQuery({
    queryKey: ["income-events", { securityId }],
    queryFn: () => apiFetch<IncomeEvent[]>(`/income-events${qs}`),
  });
}

export function useIncomeEventsSummary() {
  return useQuery({
    queryKey: ["income-events", "summary"],
    queryFn: () => apiFetch<IncomeEventsSummary>("/income-events/summary"),
  });
}

/** Received income changes cash and returns. Invalidate balances,
 * net worth and performance as well as the income list. */
function invalidateIncomeRelated(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["income-events"] });
  qc.invalidateQueries({ queryKey: ["transactions"] });
  qc.invalidateQueries({ queryKey: ["accounts"] });
  qc.invalidateQueries({ queryKey: ["performance"] });
  qc.invalidateQueries({ queryKey: ["reports"] });
}

export function useCreateIncomeEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      apiFetch<IncomeEvent>("/income-events", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => invalidateIncomeRelated(qc),
  });
}

export function useDeleteIncomeEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/income-events/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateIncomeRelated(qc),
  });
}
