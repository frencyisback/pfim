import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch, apiFetchFormData } from "./client";

export interface Price {
  id: number;
  security_id: number;
  date: string;
  /** Quote in the security currency. */
  price_close: string;
  /** Declared exchange rate and frozen converted value. */
  fx_rate: string;
  price_close_eur: string;
  source: string;
  origin_trade_id: number | null;
}

export interface PriceImportPreviewRow {
  row_number: number;
  date: string | null;
  ticker: string | null;
  security_id: number | null;
  security_label: string | null;
  close: string | null;
  /** Recognised security currency; identifies rows requiring an exchange rate. */
  currency: string | null;
  fx_rate: string | null;
  close_eur: string | null;
  is_update: boolean;
  errors: string[];
  superseded_by_row: number | null;
  final_row_number: number | null;
  final_close: string | null;
  final_fx_rate: string | null;
  final_close_eur: string | null;
}

export interface PriceImportPreviewResult {
  rows: PriceImportPreviewRow[];
  total_rows: number;
  new_rows: number;
  update_rows: number;
  skipped_unrecognized_ticker: number;
  error_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface PriceImportResult {
  imported: number;
  updated: number;
  skipped_unrecognized_ticker: number;
  errors: number;
}

export const PRICE_RELATED_QUERY_KEYS = [
  "prices",
  "portfolio",
  "performance",
  "reports",
] as const;

/** Single prices and batch imports invalidate the same consumers. */
export function invalidatePriceRelated(qc: Pick<QueryClient, "invalidateQueries">): void {
  for (const key of PRICE_RELATED_QUERY_KEYS) {
    qc.invalidateQueries({ queryKey: [key] });
  }
}

export async function previewPriceImport(
  file: File,
  page = 1,
  pageSize = 200
): Promise<PriceImportPreviewResult> {
  const fd = new FormData();
  fd.append("file", file);
  return apiFetchFormData<PriceImportPreviewResult>(
    `/prices/import/preview?page=${page}&page_size=${pageSize}`,
    fd
  );
}

export async function confirmPriceImport(file: File): Promise<PriceImportResult> {
  const fd = new FormData();
  fd.append("file", file);
  return apiFetchFormData<PriceImportResult>("/prices/import", fd);
}

export function useLatestPrice(securityId: number | null) {
  return useQuery({
    queryKey: ["prices", securityId, "latest"],
    queryFn: () => apiFetch<Price>(`/prices/${securityId}/latest`),
    enabled: securityId !== null,
    retry: false,
  });
}

/** Latest available quote for each priced security. Securities without
 * prices are absent from the response and shown as undefined in the UI,
 * avoiding a separate HTTP request for each security. */
export function useLatestPrices() {
  return useQuery({
    queryKey: ["prices", "latest"],
    queryFn: () => apiFetch<Price[]>("/prices/latest"),
    retry: false,
  });
}

export function useAddPrice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      security_id: number;
      date: string;
      price_close: string;
      /** Required for securities quoted outside the euro. */
      fx_rate?: string | null;
    }) => apiFetch<Price>("/prices", { method: "POST", body: JSON.stringify(data) }),
    // A new price changes valuation, returns and reports.
    onSuccess: () => invalidatePriceRelated(qc),
  });
}
