/** Formatters distinguish native amounts from euros, fractions from
 * percentages and signed percentage points. Mixing these units produces
 * plausible but incorrect values without throwing an error. */
import { describe, expect, it } from "vitest";

import { formatEur, formatMoney, formatMoneyWithEur, formatPercent, formatReturnDrag } from "./formatters";

/** Intl separates amounts and symbols with nonbreaking spaces (U+00A0
 * or U+202F depending on ICU). Normalise with \s, covering both without
 * invisible source characters rejected by eslint. */
const normalizza = (s: string) => s.replace(/\s/g, " ");

describe("formatEur", () => {
  it("preserves decimal commas and trailing currency symbols", () => {
    expect(normalizza(formatEur(42.5))).toBe("42,50 €");
  });

  it("groups thousands from five digits according to the numeric locale", () => {
    // The numeric locale's CLDR minimumGroupingDigits = 2 leaves 1234
    // ungrouped and starts separators at 10.000.
    // This assertion preserves the existing formatting convention and
    // prevents manual changes to otherwise correct Intl output.
    expect(normalizza(formatEur(1234.5))).toBe("1234,50 €");
    expect(normalizza(formatEur(12345.5))).toBe("12.345,50 €");
  });

  it("preserves the sign of negative values", () => {
    expect(normalizza(formatEur(-42))).toBe("-42,00 €");
  });
});

describe("formatMoney", () => {
  it("uses the declared currency symbol rather than the euro", () => {
    expect(normalizza(formatMoney(210, "USD"))).toContain("210,00");
    expect(normalizza(formatMoney(210, "USD"))).not.toContain("€");
  });

  it("keeps the table visible when Intl does not recognise the currency", () => {
    expect(normalizza(formatMoney(12345.5, "XYZ"))).toBe("12.345,50 XYZ");
  });

  it("treats an absent currency as euros", () => {
    expect(normalizza(formatMoney(10, ""))).toBe("10,00 €");
  });
});

describe("formatMoneyWithEur", () => {
  it("shows euro value alongside a foreign-currency amount", () => {
    expect(normalizza(formatMoneyWithEur(210, "USD", 193.2))).toContain("(193,20 €)");
  });

  it("does not repeat a value already in euros", () => {
    expect(normalizza(formatMoneyWithEur(210, "EUR", 210))).toBe("210,00 €");
  });

  it("shows only the native amount if euro value is unavailable", () => {
    expect(normalizza(formatMoneyWithEur(210, "USD", null))).not.toContain("(");
  });
});

describe("formatPercent", () => {
  it("accepts a fraction rather than a percentage", () => {
    expect(normalizza(formatPercent(0.1667))).toBe("16,67%");
  });
});

describe("formatReturnDrag", () => {
  it("shows positive cost drag as a reduction", () => {
    expect(normalizza(formatReturnDrag(0.5))).toBe("−0,50 p.p.");
  });

  it("does not prepend a second sign when the difference is negative", () => {
    // Net TWR above gross TWR must not produce a double minus sign.
    expect(normalizza(formatReturnDrag(-0.5))).toBe("+0,50 p.p.");
  });

  it("remains unsigned when there is no cost drag", () => {
    expect(normalizza(formatReturnDrag(0))).toBe("0,00 p.p.");
  });
});
