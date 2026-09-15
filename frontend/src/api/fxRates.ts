import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch, apiFetchFormData } from "./client";

/** Exchange-rate archive.
 * Calculations use the rate declared on each record at entry time.
 * This archive only suggests a plausible value in forms so users do not
 * need to look it up elsewhere each time. */
export interface FxRate {
  id: number;
  date: string;
  from_currency: string;
  to_currency: string;
  rate: string;
  source: string;
}

export interface FxRateSuggestion {
  currency: string;
  date: string;
  /** Null when the archive has no usable rate: enter it manually. */
  rate: string | null;
  /** Suggested rate date; it may precede the requested date. */
  rate_date: string | null;
  source: string | null;
}

export interface FxRateImportResult {
  imported: number;
  reciprocal_calculated: number;
  errors: number;
  row_errors: { row_number: number; column: string | null; message: string }[];
}

export function useFxRates() {
  return useQuery({
    queryKey: ["fx-rates"],
    queryFn: () => apiFetch<FxRate[]>("/fx-rates"),
  });
}

export function useImportFxRates() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return apiFetchFormData<FxRateImportResult>("/fx-rates/import", fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fx-rates"] }),
  });
}

/** Suggest an exchange rate for a form. Query the backend only for
 * foreign currency with a date, avoiding requests for euro forms. */
export function useSuggestedFxRate(currency: string | null, date: string | null) {
  const enabled = !!currency && currency.toUpperCase() !== "EUR" && !!date;
  return useQuery({
    queryKey: ["fx-rates", "suggest", currency, date],
    queryFn: () =>
      apiFetch<FxRateSuggestion>(
        `/fx-rates/suggest?currency=${encodeURIComponent(currency!)}&date=${date}`
      ),
    enabled,
    // Archived rates do not change, so there is no need to fetch them again.
    staleTime: Infinity,
  });
}
