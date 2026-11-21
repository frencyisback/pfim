import { describe, expect, it } from "vitest";
import { validateForecastForm, type ForecastForm } from "./forecastForm";

const validForm: ForecastForm = {
  name: "Example scenario",
  base_date: "2020-01-01",
  horizon_years: "15",
  startingNetWorthMode: "auto",
  startingNetWorthValue: "",
  monthly_income: "2500.50",
  monthly_expenses: "1800.25",
  income_growth_rate_annual: "2",
  expense_growth_rate_annual: "2.5",
  return_pessimistic: "-3",
  expected_annual_return: "5",
  return_optimistic: "8",
};

describe("forecast scenario creation", () => {
  it("accepts future dates only with explicit opening cash and a representable final year", () => {
    const future = { ...validForm, base_date: "2030-01-01" };
    expect(validateForecastForm(future, "2029-12-31")).toMatch(/future/i);
    const custom = { ...future, startingNetWorthMode: "custom" as const, startingNetWorthValue: "0" };
    expect(validateForecastForm(custom, "2029-12-31")).toBeNull();
    expect(validateForecastForm({ ...custom, base_date: "9999-01-01" })).toMatch(/anniversary/i);
  });

  it("keeps inflows and outflows unsigned and orders the three return assumptions", () => {
    for (const field of ["monthly_income", "monthly_expenses"]) {
      expect(validateForecastForm({ ...validForm, [field]: "-1" })).toMatch(/positive/i);
    }
    for (const field of ["income_growth_rate_annual", "expense_growth_rate_annual", "return_pessimistic"]) {
      expect(validateForecastForm({ ...validForm, [field]: "-101" })).toMatch(/-100%/);
    }
    expect(validateForecastForm({ ...validForm, return_pessimistic: "6" })).toMatch(/between/i);
    expect(validateForecastForm({ ...validForm, return_optimistic: "4" })).toMatch(/between/i);
  });

  it("requires every parameter without converting empty fields to zero", () => {
    expect(validateForecastForm(validForm)).toBeNull();
    for (const field of [
      "name", "horizon_years", "monthly_income", "monthly_expenses",
      "income_growth_rate_annual", "expense_growth_rate_annual",
      "return_pessimistic", "expected_annual_return", "return_optimistic",
    ]) {
      expect(validateForecastForm({ ...validForm, [field]: " " })).not.toBeNull();
    }
  });

  it("accepts explicit zeros and negative percentages", () => {
    expect(validateForecastForm({
      ...validForm,
      monthly_income: "0",
      monthly_expenses: "0",
      income_growth_rate_annual: "0",
      expense_growth_rate_annual: "0",
      return_pessimistic: "-2.5",
      expected_annual_return: "0",
      return_optimistic: "0",
    })).toBeNull();
  });

  it("rejects nonfinite numbers and horizons outside the domain", () => {
    for (const value of ["NaN", "Infinity", "1e999"]) {
      expect(validateForecastForm({ ...validForm, expected_annual_return: value })).not.toBeNull();
    }
    for (const horizon of ["0", "51", "1.5"]) {
      expect(validateForecastForm({ ...validForm, horizon_years: horizon })).not.toBeNull();
    }
    for (const horizon of ["1", "50"]) {
      expect(validateForecastForm({ ...validForm, horizon_years: horizon })).toBeNull();
    }
  });

  it("requires custom starting net worth, accepting zero and debt", () => {
    for (const value of ["", "Infinity"]) {
      expect(validateForecastForm({
        ...validForm, startingNetWorthMode: "custom", startingNetWorthValue: value,
      })).not.toBeNull();
    }
    for (const value of ["0", "-100.50"]) {
      expect(validateForecastForm({
        ...validForm, startingNetWorthMode: "custom", startingNetWorthValue: value,
      })).toBeNull();
    }
  });
});
