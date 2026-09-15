import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "./client";
import type { CsvImportProfile } from "./types";

export function useCsvImportProfiles() {
  return useQuery({
    queryKey: ["csv-import-profiles"],
    queryFn: () => apiFetch<CsvImportProfile[]>("/csv-import-profiles"),
  });
}

/** Creation fields; id and timestamps are read-only. */
export interface CreateCsvImportProfilePayload {
  name: string;
  category_column: string;
  delimiter?: string;
  skip_rows?: number;
  date_format?: string;
  date_column?: string;
  description_column?: string;
  amount_column?: string;
  decimal_separator?: string;
  default_currency?: string;
}

export function useCreateCsvImportProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateCsvImportProfilePayload) =>
      apiFetch<CsvImportProfile>("/csv-import-profiles", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["csv-import-profiles"] }),
  });
}

export function useDeleteCsvImportProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => apiFetch<void>(`/csv-import-profiles/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["csv-import-profiles"] }),
  });
}
