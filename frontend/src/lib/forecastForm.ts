import { calendarDaysSince, todayIso } from "./dates";

export interface ForecastForm {
  name: string;
  base_date: string;
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
export function validateForecastForm(form: ForecastForm, today = todayIso()): string | null {
  if (!form.name.trim()) return "Scenario name is required.";
  for (const [field, label] of NUMERIC_FIELDS) {
    if (!form[field].trim()) return `Enter ${label}. Enter 0 if the value is zero.`;
    if (!Number.isFinite(Number(form[field]))) return `Enter a finite number for ${label}.`;
  }

  const horizon = Number(form.horizon_years);
  if (!Number.isInteger(horizon) || horizon < 1 || horizon > 50) {
    return "The horizon must be an integer from 1 to 50 years.";
  }
  const daysSinceBase = calendarDaysSince(form.base_date, today);
  if (daysSinceBase === null) return "Enter a valid base date.";
  if (Number(form.base_date.slice(0, 4)) + horizon > 9999) {
    return "The final projection anniversary must be within the supported calendar.";
  }
  if (form.startingNetWorthMode === "auto" && daysSinceBase < 0) {
    return "Choose a custom starting net worth for a future base date.";
  }
  if (Number(form.monthly_income) < 0 || Number(form.monthly_expenses) < 0) {
    return "Enter inflows and outflows as positive amounts or zero.";
  }
  const pessimistic = Number(form.return_pessimistic);
  const base = Number(form.expected_annual_return);
  const optimistic = Number(form.return_optimistic);
  const rates = [
    pessimistic, base, optimistic,
    Number(form.income_growth_rate_annual), Number(form.expense_growth_rate_annual),
  ];
  if (rates.some((rate) => rate < -100)) {
    return "Growth rates and returns must be at least -100%.";
  }
  if (pessimistic > base || base > optimistic) {
    return "The base return must lie between the pessimistic and optimistic returns.";
  }
  if (form.startingNetWorthMode === "custom" && (
    !form.startingNetWorthValue.trim() || !Number.isFinite(Number(form.startingNetWorthValue))
  )) {
    return "Enter a finite numeric starting net worth or leave Automatic selected.";
  }
  return null;
}
