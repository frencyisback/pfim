import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FxImportResultNotice } from "./FxImportResultNotice";

describe("FX import result", () => {
  it("preserves counters and identifies every invalid cell", () => {
    const html = renderToStaticMarkup(<FxImportResultNotice result={{ imported: 1, reciprocal_calculated: 1, errors: 1, row_errors: [
      { row_number: 3, column: "rate", message: "Missing column" },
      { row_number: 3, column: "to", message: "Missing currency" },
    ] }} />);
    expect(html).toContain("1 rates imported");
    expect(html).toContain("1 errors");
    expect(html).toContain("Row 3, column rate: Missing column");
    expect(html).toContain("Row 3, column to: Missing currency");
  });
  it("shows a successful result without an empty error list", () => {
    const html = renderToStaticMarkup(<FxImportResultNotice result={{ imported: 2, reciprocal_calculated: 0, errors: 0, row_errors: [] }} />);
    expect(html).not.toContain("<ul");
    expect(html).toContain("0 errors");
  });
});
