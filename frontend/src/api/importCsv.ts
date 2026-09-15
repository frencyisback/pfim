import { apiFetchFormData } from "./client";
import type { CsvImportProfile } from "./types";
import { validateCategoryColumn } from "@/lib/csvImportRules";

export interface CsvProfile {
  delimiter: string;
  skip_rows: number;
  date_format: string;
  date_column: string;
  description_column: string;
  amount_column: string;
  category_column: string;
  decimal_separator: string;
  default_currency: string;
}

// The custom profile is a starting point for ad hoc mappings and is not
// persisted. Reusable profiles are managed in Settings
// (see @/api/csvProfiles) and loaded from the backend in the wizard.
export const DEFAULT_PROFILE: CsvProfile = {
  delimiter: ",",
  skip_rows: 0,
  date_format: "%Y-%m-%d",
  date_column: "date",
  description_column: "description",
  amount_column: "amount",
  category_column: "",
  decimal_separator: ".",
  default_currency: "EUR",
};

export function csvProfileFromSaved(saved: CsvImportProfile): CsvProfile {
  return {
    delimiter: saved.delimiter,
    skip_rows: saved.skip_rows,
    date_format: saved.date_format,
    date_column: saved.date_column,
    description_column: saved.description_column,
    amount_column: saved.amount_column,
    category_column: saved.category_column ?? "",
    decimal_separator: saved.decimal_separator,
    default_currency: saved.default_currency,
  };
}

export interface ImportPreviewRow {
  row_number: number;
  date: string | null;
  description: string | null;
  amount: string | null;
  category: string | null;
  is_duplicate: boolean;
  errors: string[];
}

export interface ImportPreviewResult {
  rows: ImportPreviewRow[];
  total_rows: number;
  duplicate_rows: number;
  error_rows: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ImportResult {
  imported: number;
  skipped_duplicates: number;
  errors: number;
}

function buildFormData(
  file: File,
  profile: CsvProfile,
  fxRate: string,
  extra?: Record<string, string>
): FormData {
  const categoryColumnError = validateCategoryColumn(profile.category_column);
  if (categoryColumnError) throw new Error(categoryColumnError);

  const fd = new FormData();
  fd.append("file", file);
  fd.append("delimiter", profile.delimiter);
  fd.append("skip_rows", String(profile.skip_rows));
  fd.append("date_format", profile.date_format);
  fd.append("date_column", profile.date_column);
  fd.append("description_column", profile.description_column);
  fd.append("amount_column", profile.amount_column);
  fd.append("category_column", profile.category_column.trim());
  fd.append("decimal_separator", profile.decimal_separator);
  fd.append("default_currency", profile.default_currency);
  // One exchange rate applies to the entire file: bank statements use
  // a single currency. Send it only when supplied,
  // keeping euro files unchanged.
  if (fxRate) {
    fd.append("fx_rate", fxRate);
  }
  if (extra) {
    Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  }
  return fd;
}

/** Import preview writes nothing but requires the destination account.
 * Duplicate status is account-specific: a row can already exist in one
 * account and be new in another (docs/csv-formats.md). The preview must
 * assess duplicates where the user is about to import them. */
export async function previewCsvImport(
  file: File,
  profile: CsvProfile,
  accountId: number,
  fxRate = "",
  page = 1,
  pageSize = 200
): Promise<ImportPreviewResult> {
  return apiFetchFormData<ImportPreviewResult>(
    `/transactions/import/preview?page=${page}&page_size=${pageSize}`,
    buildFormData(file, profile, fxRate, { account_id: String(accountId) })
  );
}

export async function confirmCsvImport(
  file: File,
  profile: CsvProfile,
  accountId: number,
  fxRate = ""
): Promise<ImportResult> {
  return apiFetchFormData<ImportResult>(
    "/transactions/import",
    buildFormData(file, profile, fxRate, { account_id: String(accountId) })
  );
}
