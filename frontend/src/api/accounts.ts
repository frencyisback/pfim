import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { Account } from "./types";

export function useAccounts(onlyActive = false) {
  return useQuery({
    queryKey: ["accounts", { onlyActive }],
    queryFn: () => apiFetch<Account[]>(`/accounts?only_active=${onlyActive}`),
  });
}

export function useCreateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Account>) =>
      apiFetch<Account>("/accounts", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useUpdateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Account> }) =>
      apiFetch<Account>(`/accounts/${id}`, { method: "PUT", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useDeactivateAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) =>
      apiFetch<Account>(`/accounts/${id}/deactivate`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/accounts/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["accounts"] }),
  });
}

export interface AccountBalanceHistoryPoint {
  date: string;
  balance: string;
}

export function useAccountHistory(accountId: number | null) {
  return useQuery({
    queryKey: ["accounts", accountId, "history"],
    queryFn: () => apiFetch<AccountBalanceHistoryPoint[]>(`/accounts/${accountId}/history`),
    enabled: accountId !== null,
  });
}
