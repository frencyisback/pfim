import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { Security } from "./types";

export function useSecurities(options: { onlyActive?: boolean } = {}) {
  const onlyActive = options.onlyActive ?? false;
  return useQuery({
    queryKey: ["securities", { onlyActive }],
    queryFn: () =>
      apiFetch<Security[]>(`/securities${onlyActive ? "?only_active=true" : ""}`),
  });
}

export function useCreateSecurity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Partial<Security>) =>
      apiFetch<Security>("/securities", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["securities"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function useUpdateSecurity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Security> }) =>
      apiFetch<Security>(`/securities/${id}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["securities"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export function useDeleteSecurity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/securities/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["securities"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}
