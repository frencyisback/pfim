import { useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useCompareForecasts,
  useCreateForecastScenario,
  useDeleteForecastScenario,
  useForecastScenarios,
  useRunForecast,
  type ForecastCompareResult,
  type ForecastScenario,
  type ForecastRunResult,
} from "@/api/forecasts";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { formatEur } from "@/lib/formatters";
import { todayIso } from "@/lib/dates";
import { buildForecastComparison } from "@/lib/forecastComparison";
import { validateForecastForm, type ForecastForm } from "@/lib/forecastForm";
import { useTableSort } from "@/lib/useTableSort";

const COMPARE_COLORS = ["#0ea5e9", "#8b5cf6", "#f97316", "#22c55e", "#ec4899", "#64748b"];

/** Forecast page: scenario creation wizard and optimistic/base/pessimistic
 * projection chart. Specification §7.6 and §10. */
export default function Forecasts() {
  const { data: scenarios, isLoading, error: scenariosError } = useForecastScenarios();
  const createScenario = useCreateForecastScenario();
  const deleteScenario = useDeleteForecastScenario();
  const runForecast = useRunForecast();

  const compareForecasts = useCompareForecasts();

  const [result, setResult] = useState<ForecastRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [comparison, setComparison] = useState<ForecastCompareResult | null>(null);
  type ScenarioSortKey = "name" | "horizon";
  const scenarioSort = useTableSort<ForecastScenario, ScenarioSortKey>(
    scenarios ?? [],
    { key: "name", direction: "asc" },
    (scenario, key) => (key === "name" ? scenario.name : scenario.horizon_years)
  );

  function toggleSelected(id: number) {
    setSelectedIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  }

  async function handleCompare() {
    setError(null);
    setComparison(null);
    try {
      setComparison(await compareForecasts.mutateAsync(selectedIds));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  /** One row per year and one column per scenario. Different horizons
   * remain intact: shorter curves end earlier without truncating the
   * longer scenarios and hiding already-calculated years. */
  const comparisonChart = buildForecastComparison(comparison?.results ?? []);

  const [form, setForm] = useState<ForecastForm>({
    name: "",
    horizon_years: "",
    startingNetWorthMode: "auto",
    startingNetWorthValue: "",
    monthly_income: "",
    monthly_expenses: "",
    income_growth_rate_annual: "",
    expense_growth_rate_annual: "",
    expected_annual_return: "",
    return_optimistic: "",
    return_pessimistic: "",
  });

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const validationError = validateForecastForm(form);
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      const scenario = await createScenario.mutateAsync({
        name: form.name.trim(),
        base_date: todayIso(),
        horizon_years: Number(form.horizon_years),
        parameters: {
          starting_net_worth:
            form.startingNetWorthMode === "auto" ? "auto" : form.startingNetWorthValue,
          cash_flow: {
            monthly_income: Number(form.monthly_income),
            monthly_expenses: Number(form.monthly_expenses),
            income_growth_rate_annual: Number(form.income_growth_rate_annual) / 100,
            expense_growth_rate_annual: Number(form.expense_growth_rate_annual) / 100,
          },
          portfolio: {
            expected_annual_return: Number(form.expected_annual_return) / 100,
            return_optimistic: Number(form.return_optimistic) / 100,
            return_pessimistic: Number(form.return_pessimistic) / 100,
          },
          contributions: [],
        },
      });
      const runResult = await runForecast.mutateAsync(scenario.id);
      setResult(runResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  async function handleRun(id: number) {
    setError(null);
    setResult(null);
    try {
      const runResult = await runForecast.mutateAsync(id);
      setResult(runResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  const chartData = result
    ? result.scenarios.base.years.map((y, i) => ({
        year: y.date.slice(0, 4),
        Pessimistic: Number(result.scenarios.pessimistic.years[i]?.net_worth ?? 0),
        Base: Number(y.net_worth),
        Optimistic: Number(result.scenarios.optimistic.years[i]?.net_worth ?? 0),
      }))
    : [];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Forecasts</h2>

      <form onSubmit={handleCreate} className="grid grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-4">
        <p className="col-span-full text-xs font-medium text-gray-500">New scenario</p>
        <input
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Scenario name"
          aria-label="Scenario name"
          required
          maxLength={120}
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
        <input
          type="number"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Horizon (years)"
          aria-label="Horizon in years"
          min="1"
          max="50"
          step="1"
          required
          value={form.horizon_years}
          onChange={(e) => setForm({ ...form, horizon_years: e.target.value })}
        />

        <label className="col-span-full flex flex-wrap items-center gap-2 text-xs text-gray-500">
          Starting net worth:
          <select
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.startingNetWorthMode}
            onChange={(e) =>
              setForm({ ...form, startingNetWorthMode: e.target.value as "auto" | "custom" })
            }
          >
            <option value="auto">Automatic (actual account balances + portfolio)</option>
            <option value="custom">Custom amount</option>
          </select>
          {form.startingNetWorthMode === "custom" && (
            <input
              type="number"
              step="any"
              placeholder="Starting net worth €"
              aria-label="Starting net worth in euros"
              required
              className="w-40 rounded border border-gray-300 px-2 py-1.5 text-sm"
              value={form.startingNetWorthValue}
              onChange={(e) => setForm({ ...form, startingNetWorthValue: e.target.value })}
            />
          )}
        </label>
        {form.startingNetWorthMode === "custom" && (
          <p className="col-span-full text-xs text-gray-500">
            The custom amount is entirely initial cash. Zero and negative values are allowed.
          </p>
        )}

        <input
          type="number"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Monthly inflows €"
          aria-label="Monthly inflows in euros"
          step="0.01"
          required
          value={form.monthly_income}
          onChange={(e) => setForm({ ...form, monthly_income: e.target.value })}
        />
        <input
          type="number"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Monthly outflows €"
          aria-label="Monthly outflows in euros"
          step="0.01"
          required
          value={form.monthly_expenses}
          onChange={(e) => setForm({ ...form, monthly_expenses: e.target.value })}
        />
        <input
          type="number"
          step="any"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Annual inflow growth %"
          aria-label="Annual inflow growth as a percentage"
          required
          value={form.income_growth_rate_annual}
          onChange={(e) => setForm({ ...form, income_growth_rate_annual: e.target.value })}
        />
        <input
          type="number"
          step="any"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Annual outflow growth %"
          aria-label="Annual outflow growth as a percentage"
          required
          value={form.expense_growth_rate_annual}
          onChange={(e) => setForm({ ...form, expense_growth_rate_annual: e.target.value })}
        />

        <input
          type="number"
          step="any"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Pessimistic return %"
          aria-label="Pessimistic return as a percentage"
          required
          value={form.return_pessimistic}
          onChange={(e) => setForm({ ...form, return_pessimistic: e.target.value })}
        />
        <input
          type="number"
          step="any"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Base return %"
          aria-label="Base return as a percentage"
          required
          value={form.expected_annual_return}
          onChange={(e) => setForm({ ...form, expected_annual_return: e.target.value })}
        />
        <input
          type="number"
          step="any"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Optimistic return %"
          aria-label="Optimistic return as a percentage"
          required
          value={form.return_optimistic}
          onChange={(e) => setForm({ ...form, return_optimistic: e.target.value })}
        />

        {/* Expected return is total return, including reinvested dividends,
            as explained in the note below. */}
        <p className="col-span-full text-xs text-gray-500">
          The returns above are <strong>total returns</strong>: they already include dividends and coupons, assumed reinvested. The projection compounds annually, adding each period's savings to the portfolio.
        </p>
        <p className="col-span-full text-xs text-gray-500">
          Starting net worth represents the base date. Each year ends on its anniversary; contributions after the preceding anniversary through the current anniversary are added at period end, without intrayear returns. Contributions on or before the base date or beyond the horizon are excluded. February 29 becomes February 28 in non-leap years.
        </p>

        <button
          type="submit"
          disabled={createScenario.isPending || runForecast.isPending}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white hover:bg-gray-700 disabled:opacity-50"
        >
          {createScenario.isPending || runForecast.isPending ? "Calculating..." : "Create and run"}
        </button>
        {error && <p className="col-span-full text-sm text-red-600">{error}</p>}
      </form>

      {result && (
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <h3 className="mb-3 text-sm font-medium text-gray-600">
            Net worth projection — {result.scenario_name}
          </h3>
          <ResponsiveContainer width="100%" height={320}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="year" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => formatEur(v)} width={90} />
              <Tooltip formatter={(v: number) => formatEur(v)} />
              <Legend />
              <Area type="monotone" dataKey="Optimistic" stroke="#22c55e" fill="#22c55e" fillOpacity={0.1} />
              <Area type="monotone" dataKey="Base" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.2} />
              <Area type="monotone" dataKey="Pessimistic" stroke="#ef4444" fill="#ef4444" fillOpacity={0.1} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <section>
        <QueryStateNotice isLoading={isLoading} error={scenariosError} />
        <CollapsibleTable title="Saved scenarios" count={scenarios?.length ?? 0}>
          <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                <th className="px-3 py-2 w-8"></th>
                {([ ["name", "Name"], ["horizon", "Horizon"] ] as const).map(
                  ([key, label]) => (
                    <SortableHeader
                      key={key}
                      active={scenarioSort.sort.key === key}
                      direction={scenarioSort.sort.direction}
                      onSort={() => scenarioSort.requestSort(key)}
                      className="px-3 py-2"
                    >
                      {label}
                    </SortableHeader>
                  )
                )}
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {scenarioSort.sortedRows.map((s) => (
                <tr key={s.id} className="border-t border-gray-100">
                  <td className="px-3 py-2">
                    <input
                      type="checkbox"
                      aria-label={`Include ${s.name} in comparison`}
                      checked={selectedIds.includes(s.id)}
                      onChange={() => toggleSelected(s.id)}
                    />
                  </td>
                  <td className="px-3 py-2">{s.name}</td>
                  <td className="px-3 py-2">{s.horizon_years} years</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => handleRun(s.id)}
                      className="mr-3 text-xs text-blue-600 hover:underline"
                    >
                      Run
                    </button>
                    <button
                      onClick={() => deleteScenario.mutate(s.id)}
                      className="text-xs text-gray-400 hover:text-red-600"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {scenarios?.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-gray-400">
                    No saved scenarios.
                  </td>
                </tr>
              )}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            onClick={handleCompare}
            disabled={selectedIds.length < 2 || compareForecasts.isPending}
            className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50 disabled:opacity-50"
          >
            {compareForecasts.isPending ? "Comparing..." : "⇄ Compare selected"}
          </button>
          <span className="text-xs text-gray-500">
            {selectedIds.length < 2
              ? "Select at least two scenarios to compare."
              : `${selectedIds.length} scenarios selected.`}
          </span>
        </div>
      </section>

      {comparison && (
        <section>
          <h3 className="mb-1 font-medium">Scenario comparison</h3>
          <p className="mb-3 max-w-3xl text-xs text-gray-500">
            Overlay of the <strong>base</strong> curve for each scenario. Optimistic and pessimistic curves are omitted to keep multiple scenarios readable. Use Run to see a scenario's full range.
          </p>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <ResponsiveContainer width="100%" height={320}>
              <LineChart data={comparisonChart.data}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="year" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => formatEur(v)} width={90} />
                <Tooltip formatter={(v: number) => formatEur(v)} />
                <Legend />
                {comparisonChart.series.map((series, i) => (
                  <Line
                    key={series.id}
                    type="monotone"
                    dataKey={series.dataKey}
                    name={series.label}
                    stroke={COMPARE_COLORS[i % COMPARE_COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}
    </div>
  );
}
