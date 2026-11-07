import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { Security } from "@/api/types";
import SecurityDetailsTable from "./SecurityDetailsTable";

const security: Security = {
  id: 7, ticker: "TEST", name: "Sample security", type: "stock", market: "HIDDEN-MARKET",
  currency: "USD", isin: "US1234567890", sector: "Technology", industry: "Software",
  country: "United States", is_active: true,
};

describe("security catalogue detail table", () => {
  it("displays exactly the nine fields exposed by the existing catalogue", () => {
    const html = renderToStaticMarkup(<SecurityDetailsTable security={security} />);
    const labels = [...html.matchAll(/<th[^>]*>([^<]+)<\/th>/g)].map((match) => match[1]);
    expect(labels).toEqual([
      "Ticker", "Name", "ISIN", "Type", "Currency", "Sector", "Industry", "Country", "Status",
    ]);
    for (const value of ["TEST", "Sample security", "US1234567890", "USD", "Technology", "Software", "United States", "Active"]) {
      expect(html).toContain(value);
    }
    expect(html).not.toContain("HIDDEN-MARKET");
  });

  it("does not expose backend-only fields even when present in the response", () => {
    const response = {
      ...security, coupon_rate: "9.8765", coupon_freq: "monthly", maturity_date: "2099-12-31",
      face_value: "12345.678901", notes: "HIDDEN-NOTES",
    };
    const html = renderToStaticMarkup(<SecurityDetailsTable security={response} />);
    for (const hidden of ["HIDDEN-MARKET", "9.8765", "monthly", "2099-12-31", "12345.678901", "HIDDEN-NOTES"]) {
      expect(html).not.toContain(hidden);
    }
  });

  it("uses placeholders for absent or blank optional fields", () => {
    const html = renderToStaticMarkup(<SecurityDetailsTable security={{
      ...security, isin: null, sector: "", industry: "   ", country: null,
    }} />);
    expect(html.match(/>—<\/td>/g)).toHaveLength(4);
    expect(html).not.toContain("undefined");
    expect(html).not.toContain(">null<");
  });

  it("keeps inactive and legacy ETF records readable", () => {
    const html = renderToStaticMarkup(<SecurityDetailsTable security={{ ...security, is_active: false, type: "etf" }} />);
    expect(html).toContain("Inactive");
    expect(html).toContain("ETF");
  });

  it("escapes user-entered names as text", () => {
    const html = renderToStaticMarkup(<SecurityDetailsTable security={{ ...security, name: "<script>alert(1)</script>" }} />);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
});
