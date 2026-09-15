import { describe, expect, it } from "vitest";
import { validateForecastForm, type ForecastForm } from "./forecastForm";

const validForm: ForecastForm = {
  name: "Example scenario",
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
