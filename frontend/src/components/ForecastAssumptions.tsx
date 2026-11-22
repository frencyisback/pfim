import type { ForecastRunResult, ForecastScenario } from "@/api/forecasts";
import { formatEur } from "@/lib/formatters";

const unavailable = "Unavailable";
const rateFormat = new Intl.NumberFormat("it-IT", {
  style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 12,
});

function fields(value: unknown): Record<string, unknown> | undefined {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
}

/** Saved JSON can contain numeric strings, while older backups can omit fields. */
function formatted(value: unknown, format: (amount: number) => string): string {
  if (typeof value !== "number") {
    if (typeof value !== "string" || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) {
      return unavailable;
    }
  }
  const number = Number(value);
  return Number.isFinite(number) ? format(number) : unavailable;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-gray-500">{label}</dt>
      <dd className="text-sm font-medium text-gray-800">{value}</dd>
    </div>
  );
}

export default function ForecastAssumptions({ scenario, result }: {
  scenario: ForecastScenario;
  result?: ForecastRunResult;
}) {
  const parameters = scenario.parameters;
  const cash = fields(parameters.cash_flow);
  const portfolio = fields(parameters.portfolio);
  const start = parameters.starting_net_worth;
  const automatic = start === undefined || start === "auto";
  const capital = result ? formatted(result.opening_net_worth, formatEur) : formatted(start, formatEur);
  const investment = cash?.monthly_savings_to_invest;
  const investmentRule = cash && investment == null
    ? "Automatic · invest positive cash flow at each anniversary"
    : formatted(investment, formatEur);
  const contributions = parameters.contributions === undefined ? [] : parameters.contributions;
  const growth = (value: unknown) => formatted(cash && value === undefined ? 0 : value, rateFormat.format);

  return (
    <div className="space-y-3">
      {scenario.description && <p className="whitespace-pre-line text-sm text-gray-600">{scenario.description}</p>}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
        <Detail label="Base date" value={scenario.base_date} />
        <Detail label="Horizon" value={`${scenario.horizon_years} ${scenario.horizon_years === 1 ? "year" : "years"}`} />
        <Detail label="Starting net worth" value={automatic
          ? (result ? `Automatic · ${capital}` : "Automatic · calculated from accounts and investments on the base date")
          : `Custom · ${capital}`} />
        {result && <>
          <Detail label="Opening cash" value={formatted(result.opening_cash, formatEur)} />
          <Detail label="Opening portfolio value" value={formatted(result.opening_portfolio_value, formatEur)} />
        </>}
      </dl>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-gray-100 pt-3 sm:grid-cols-3">
        <Detail label="Pessimistic annual return" value={formatted(portfolio?.return_pessimistic, rateFormat.format)} />
        <Detail label="Base annual return" value={formatted(portfolio?.expected_annual_return, rateFormat.format)} />
        <Detail label="Optimistic annual return" value={formatted(portfolio?.return_optimistic, rateFormat.format)} />
        <Detail label="Monthly income" value={formatted(cash?.monthly_income, formatEur)} />
        <Detail label="Monthly expenses" value={formatted(cash?.monthly_expenses, formatEur)} />
        <Detail label="Monthly savings to invest" value={investmentRule} />
        <Detail label="Annual income growth" value={growth(cash?.income_growth_rate_annual)} />
        <Detail label="Annual expense growth" value={growth(cash?.expense_growth_rate_annual)} />
      </dl>
      <div className="border-t border-gray-100 pt-3 text-sm">
        <p className="text-xs text-gray-500">Scheduled contributions and withdrawals</p>
        {!Array.isArray(contributions) ? unavailable : contributions.length === 0 ? "None" : (
          <>
            <ul className="divide-y divide-gray-100">
              {contributions.map((entry, index) => {
                const { date, label, amount } = fields(entry) ?? {};
                return (
                  <li key={index} className="flex flex-wrap justify-between gap-x-3 py-1">
                    <span>{typeof date === "string" ? date : unavailable} · {typeof label === "string" ? label : unavailable}</span>
                    <span>{formatted(amount, formatEur)}</span>
                  </li>
                );
              })}
            </ul>
            <p className="mt-1 text-xs text-gray-500">The projection includes dates after the base date through the final anniversary.</p>
          </>
        )}
      </div>
    </div>
  );
}
