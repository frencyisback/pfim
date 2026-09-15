export interface ForecastForm {
  name: string;
  horizon_years: string;
  startingNetWorthMode: "auto" | "custom";
  startingNetWorthValue: string;
  monthly_income: string;
  monthly_expenses: string;
  income_growth_rate_annual: string;
  expense_growth_rate_annual: string;
  expected_annual_return: string;
  return_optimistic: string;
  return_pessimistic: string;
}

const NUMERIC_FIELDS = [
  ["horizon_years", "the horizon in years"],
  ["monthly_income", "monthly inflows"],
  ["monthly_expenses", "monthly outflows"],
  ["income_growth_rate_annual", "annual inflow growth"],
  ["expense_growth_rate_annual", "annual outflow growth"],
  ["return_pessimistic", "the pessimistic return"],
  ["expected_annual_return", "the base return"],
  ["return_optimistic", "the optimistic return"],
] as const;

/** Empty fields must not implicitly become zero in API requests. */
export function validateForecastForm(form: ForecastForm): string | null {
  if (!form.name.trim()) return "Scenario name is required.";
  for (const [field, label] of NUMERIC_FIELDS) {
    if (!form[field].trim()) return `Enter ${label}. Enter 0 if the value is zero.`;
    if (!Number.isFinite(Number(form[field]))) return `Enter a finite number for ${label}.`;
  }

  const horizon = Number(form.horizon_years);
  if (!Number.isInteger(horizon) || horizon < 1 || horizon > 50) {
    return "The horizon must be an integer from 1 to 50 years.";
  }
  if (form.startingNetWorthMode === "custom" && (
    !form.startingNetWorthValue.trim() || !Number.isFinite(Number(form.startingNetWorthValue))
  )) {
    return "Enter a finite numeric starting net worth or leave Automatic selected.";
  }
  return null;
}
