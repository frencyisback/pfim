import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import IncomeAmountFields from "./IncomeAmountFields";

const props = {
  gross: "100", withheld: "26", currency: "USD", fxRate: "0.92",
  onGrossChange: () => {}, onWithheldChange: () => {},
};

describe("income fields and preview", () => {
  it("shows USD in both fields and distinguishes native net income from its EUR value", () => {
    const html = renderToStaticMarkup(<IncomeAmountFields {...props} />);
    expect(html).toContain("Gross amount (USD)");
    expect(html).toContain("Withholding (USD)");
    expect(html).toContain("Net amount to credit (gross − withholding)");
    expect(html).toContain("74,00");
    expect(html).toContain("68,08");
    expect(html).not.toContain("Gross amount €");
  });

  it("updates labels to EUR without suggesting another exchange rate", () => {
    const html = renderToStaticMarkup(<IncomeAmountFields {...props} currency="EUR" fxRate="" />);
    expect(html).toContain("Gross amount (EUR)");
    expect(html).toContain("Withholding (EUR)");
    expect(html).toContain("74,00");
    expect(html).not.toContain("EUR value");
  });

  it("shows 90 USD net and 81 EUR for 100 USD gross, 10 USD withholding and a 0.9 rate", () => {
    const html = renderToStaticMarkup(<IncomeAmountFields {...props} withheld="10" fxRate="0.9" />);
    expect(html).toContain("Gross amount (USD)");
    expect(html).toContain("Withholding (USD)");
    expect(html).toContain("90,00");
    expect(html).toContain("81,00");
    expect(html).toContain("EUR value");
  });

  it("shows only native net income and requests a rate when the rate is incomplete", () => {
    const html = renderToStaticMarkup(<IncomeAmountFields {...props} fxRate="0" />);
    expect(html).toContain("74,00");
    expect(html).toContain("enter a valid positive exchange rate");
    expect(html).not.toContain("0,00");
  });

  it("does not confuse an empty field with full withholding", () => {
    const incomplete = renderToStaticMarkup(<IncomeAmountFields {...props} gross="" />);
    expect(incomplete).toContain("enter valid gross and withholding amounts");
    expect(incomplete).not.toContain("0,00");
    const fullyWithheld = renderToStaticMarkup(<IncomeAmountFields {...props} withheld="100" />);
    expect(fullyWithheld).toContain("Net amount to credit");
    expect(fullyWithheld).toContain("0,00");
  });
});
