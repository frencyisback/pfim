import { describe, expect, it } from "vitest";
import { previewIncomeNet } from "./incomePreview";

const usd = { gross: "100", withheld: "26", currency: "USD", fxRate: "0.92" };

describe("net coupon preview", () => {
  it("subtracts withholding in the declared currency and converts only the net amount", () => {
    expect(previewIncomeNet(usd)).toEqual({ native: 74, eur: 68.08 });
    expect(previewIncomeNet({ ...usd, withheld: "10", fxRate: "0.9" })).toEqual({ native: 90, eur: 81 });
    expect(previewIncomeNet({ ...usd, currency: "EUR", fxRate: "" })).toEqual({ native: 74, eur: 74 });
  });

  it("preserves valid zero for full withholding or zero income", () => {
    expect(previewIncomeNet({ ...usd, withheld: "100" })).toEqual({ native: 0, eur: 0 });
    expect(previewIncomeNet({ ...usd, gross: "0", withheld: "0" })).toEqual({ native: 0, eur: 0 });
    expect(previewIncomeNet({ ...usd, withheld: "0" })).toEqual({ native: 100, eur: 92 });
  });

  it.each(["", " ", "0", "-1", "NaN", "Infinity"])("does not invent a EUR value with exchange rate '%s'", (fxRate) => {
    expect(previewIncomeNet({ ...usd, fxRate })).toEqual({ native: 74, eur: null });
    expect(previewIncomeNet({ ...usd, withheld: "100", fxRate })).toEqual({ native: 0, eur: null });
  });

  it.each([
    { gross: "" }, { withheld: "" }, { gross: " " }, { gross: "1e309" },
    { withheld: "Infinity" }, { gross: "-1" }, { withheld: "-1" }, { withheld: "101" },
  ])("does not display net income for incomplete or inconsistent inputs: %j", (patch) => {
    expect(previewIncomeNet({ ...usd, ...patch })).toBeNull();
  });
});
