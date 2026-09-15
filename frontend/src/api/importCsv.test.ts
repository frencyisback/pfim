import { describe, expect, it } from "vitest";

import type { CsvImportProfile } from "./types";
import { csvProfileFromSaved, previewCsvImport } from "./importCsv";
import {
  CATEGORY_COLUMN_REQUIRED_MESSAGE,
  validateCategoryColumn,
} from "@/lib/csvImportRules";

const legacyProfile: CsvImportProfile = {
  id: 1,
  name: "Legacy format",
  delimiter: ";",
  skip_rows: 0,
  date_format: "%d/%m/%Y",
  date_column: "Date",
  description_column: "Description",
  amount_column: "Amount",
  category_column: null,
  decimal_separator: ",",
  default_currency: "EUR",
  created_at: "2026-01-01T00:00:00",
  updated_at: null,
};

describe("legacy CSV profiles", () => {
  it("remain readable without inventing a category mapping", () => {
    const editable = csvProfileFromSaved(legacyProfile);

    expect(editable.category_column).toBe("");
    expect(validateCategoryColumn(editable.category_column)).toBe(
      CATEGORY_COLUMN_REQUIRED_MESSAGE
    );
  });

  it("block preview before any network request", async () => {
    const editable = csvProfileFromSaved(legacyProfile);
    const file = new File(["Date;Description;Amount"], "transactions.csv", {
      type: "text/csv",
    });

    await expect(previewCsvImport(file, editable, 10)).rejects.toThrow(
      CATEGORY_COLUMN_REQUIRED_MESSAGE
    );
  });

  it("treats a whitespace-only mapping as missing", () => {
    expect(validateCategoryColumn("   ")).toBe(CATEGORY_COLUMN_REQUIRED_MESSAGE);
    expect(validateCategoryColumn("Category")).toBeNull();
  });
});
