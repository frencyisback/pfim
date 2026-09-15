import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { PaginatedResponse, Transaction } from "./types";

export type TransactionSortBy =
  | "date"
  | "account_id"
  | "category_id"
  | "description"
  | "amount";
export type SortDir = "asc" | "desc";

export interface TransactionFilters {
  account_id?: number;
  category_id?: number;
  date_from?: string;
  date_to?: string;
  page?: number;
  page_size?: number;
  sort_by?: TransactionSortBy;
  sort_dir?: SortDir;
}

function buildQuery(filters: TransactionFilters): string {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  });
  return params.toString();
}

export function useTransactions(filters: TransactionFilters) {
  return useQuery({
    queryKey: ["transactions", filters],
    queryFn: () =>
      apiFetch<PaginatedResponse<Transaction>>(`/transactions?${buildQuery(filters)}`),
  });
}

/** Transactions change account balances, net worth, income statements
 * and analyses. Invalidate them together so dashboard and report KPI
 * cards show the latest values, including newly converted amounts. */
function invalidateTransactionRelated(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["transactions"] });
  qc.invalidateQueries({ queryKey: ["accounts"] });
  qc.invalidateQueries({ queryKey: ["reports"] });
}

/** Transaction creation payload. Backend-calculated fields
 * (amount_eur, applied fx_rate and linked ids) are excluded:
 * the exchange rate is declared and the server calculates the EUR value. */
export interface TransactionPayload {
  account_id: number;
  category_id: number;
  date: string;
  amount: string;
  currency?: string;
  /** Required when currency is not EUR. */
  fx_rate?: string | null;
  description?: string | null;
  notes?: string | null;
  tags?: string[];
}

export function useCreateTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TransactionPayload) =>
      apiFetch<Transaction>("/transactions", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => invalidateTransactionRelated(qc),
  });
}

export function useDeleteTransaction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/transactions/${id}`, { method: "DELETE" }),
    onSuccess: () => invalidateTransactionRelated(qc),
  });
}

export interface TransferPayload {
  from_account_id: number;
  to_account_id: number;
  date: string;
  amount: string;
  currency: string;
  /** Required when currency is not EUR; applies to both sides. */
  fx_rate?: string | null;
  description?: string | null;
}

export interface TransferResult {
  from_transaction: Transaction;
  to_transaction: Transaction;
}

export function useCreateTransfer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: TransferPayload) =>
      apiFetch<TransferResult>("/transactions/transfer", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => invalidateTransactionRelated(qc),
  });
}
