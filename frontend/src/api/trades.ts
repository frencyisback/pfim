import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { Trade, TradeCost } from "./types";

export function useTrades(params?: { security_id?: number; account_id?: number }) {
  const query = new URLSearchParams();
  if (params?.security_id) query.set("security_id", String(params.security_id));
  if (params?.account_id) query.set("account_id", String(params.account_id));
  const qs = query.toString();
  return useQuery({
    queryKey: ["trades", params ?? {}],
    queryFn: () => apiFetch<Trade[]>(`/trades${qs ? `?${qs}` : ""}`),
  });
}

/** Trades affect cash, positions, returns and reports; invalidate
 * them together so KPI cards remain up to date. */
function invalidateTradeRelated(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["portfolio"] });
  qc.invalidateQueries({ queryKey: ["trades"] });
  qc.invalidateQueries({ queryKey: ["transactions"] });
  qc.invalidateQueries({ queryKey: ["accounts"] });
  qc.invalidateQueries({ queryKey: ["performance"] });
  qc.invalidateQueries({ queryKey: ["reports"] });
  qc.invalidateQueries({ queryKey: ["prices"] });
}

export function useCreateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      security_id: number;
      account_id: number;
      type: string;
      date: string;
      quantity: string;
      /** Price in the settlement currency. */
      price: string;
      currency: string;
      fx_rate?: string | null;
      /** Required if the settlement and security currencies differ. */
      quote_price?: string;
    }) =>
      apiFetch<Trade>("/trades", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => invalidateTradeRelated(qc),
  });
}

export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/trades/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateTradeRelated(qc),
  });
}

export function useTradeCosts(tradeId: number | null) {
  return useQuery({
    queryKey: ["trades", tradeId, "costs"],
    queryFn: () => apiFetch<TradeCost[]>(`/trades/${tradeId}/costs`),
    enabled: tradeId !== null,
  });
}

export function useAddTradeCost(tradeId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      cost_type: string;
      description?: string | null;
      amount?: string;
      percentage?: string;
      currency: string;
      /** Required for a foreign-currency amount; percentage costs inherit
       * the trade exchange rate. */
      fx_rate?: string | null;
      notes?: string | null;
    }) => apiFetch<TradeCost>(`/trades/${tradeId}/costs`, { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trades", tradeId, "costs"] });
      invalidateTradeRelated(qc);
    },
  });
}

export function useDeleteTradeCost(tradeId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (costId: number) =>
      apiFetch<void>(`/trades/${tradeId}/costs/${costId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trades", tradeId, "costs"] });
      invalidateTradeRelated(qc);
    },
  });
}
