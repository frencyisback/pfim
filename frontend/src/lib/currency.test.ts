/** Entry-time conversion in forms (docs/multi-currency.md): when to
 * request exchange rates and what to preview while the user is typing. */
import { describe, expect, it } from "vitest";

import { needsFxRate, needsSeparateQuotePrice, previewEur } from "./currency";

describe("needsFxRate", () => {
  it("does not request a rate for euros because no conversion is needed", () => {
    expect(needsFxRate("EUR")).toBe(false);
    expect(needsFxRate("eur")).toBe(false);
    expect(needsFxRate(" EUR ")).toBe(false);
  });

  it("requests a rate for every other currency", () => {
    expect(needsFxRate("USD")).toBe(true);
  });

  it("does not request a rate until a currency is selected", () => {
    expect(needsFxRate("")).toBe(false);
    expect(needsFxRate(null)).toBe(false);
    expect(needsFxRate(undefined)).toBe(false);
  });
});

describe("previewEur", () => {
  it("euro value equals the original amount without conversion", () => {
    expect(previewEur("100", "EUR", "")).toBe(100);
  });

  it("foreign currency amounts multiply by the declared rate", () => {
    expect(previewEur("100", "USD", "0.92")).toBe(92);
  });

  it("shows nothing until enough data is available rather than 0,00 €", () => {
    // Displaying 0,00 € while typing appears to be a result rather than a
    // pending value, so show nothing instead.
    expect(previewEur("", "EUR", "")).toBeNull();
    expect(previewEur("100", "USD", "")).toBeNull();
    expect(previewEur("abc", "EUR", "")).toBeNull();
  });

  it("rejects nonpositive rates rather than producing zero or an incorrect sign", () => {
    expect(previewEur("100", "USD", "0")).toBeNull();
    expect(previewEur("100", "USD", "-0.9")).toBeNull();
  });

  it("preserves the sign of an outflow", () => {
    expect(previewEur("-100", "USD", "0.9")).toBe(-90);
  });
});

describe("needsSeparateQuotePrice", () => {
  it("requires the native price only when settlement and quote currencies differ", () => {
    expect(needsSeparateQuotePrice("EUR", "USD")).toBe(true);
    expect(needsSeparateQuotePrice("usd", " USD ")).toBe(false);
    expect(needsSeparateQuotePrice("EUR", "EUR")).toBe(false);
  });

  it("waits until both currencies are known", () => {
    expect(needsSeparateQuotePrice("EUR", undefined)).toBe(false);
    expect(needsSeparateQuotePrice(undefined, "USD")).toBe(false);
  });
});
