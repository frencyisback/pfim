import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { PriceImportPreviewRow } from "@/api/prices";
import { PricePreviewStatus } from "./PricePreviewStatus";

const row: PriceImportPreviewRow = {
  row_number: 1, date: "2026-01-01", ticker: "AAA", security_id: 1, security_label: "AAA",
  close: "10", currency: "USD", fx_rate: "0.8", close_eur: "8", is_update: false, errors: [],
  superseded_by_row: 201, final_row_number: 201, final_close: "20", final_fx_rate: "0.9", final_close_eur: "18",
};

describe("price sequence status", () => {
  it("shows an off-page replacement row and final value with exchange rate", () => {
    const html = renderToStaticMarkup(<PricePreviewStatus row={row} />);
    expect(html).toContain("New");
    expect(html).toContain("Replaced by row 201");
    expect(html).toContain("Final value: 20 USD");
    expect(html).toContain("exchange rate 0.9; 18 EUR");
  });
  it("identifies the last valid row without marking it as replaced", () => {
    const html = renderToStaticMarkup(<PricePreviewStatus row={{ ...row, row_number: 201, is_update: true, superseded_by_row: null }} />);
    expect(html).toContain("Update");
    expect(html).toContain("Last valid row");
    expect(html).not.toContain("Replaced");
  });
  it("prioritises errors over ignored tickers and duplicates", () => {
    const html = renderToStaticMarkup(<PricePreviewStatus row={{ ...row, security_id: null, errors: ["Invalid price"] }} />);
    expect(html).toBe("Invalid price");
  });
});
