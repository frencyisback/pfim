import { Fragment, useState } from "react";
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
import ForecastAssumptions from "@/components/ForecastAssumptions";
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
  const [expandedId, setExpandedId] = useState<number | null>(null);
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
    base_date: todayIso(),
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
        base_date: form.base_date,
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

        <label className="flex items-center gap-2 text-xs text-gray-500">
          Base date
          <input
            type="date"
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            required
            max={form.startingNetWorthMode === "auto" ? todayIso() : undefined}
            value={form.base_date}
            onChange={(e) => setForm({ ...form, base_date: e.target.value })}
          />
        </label>
        <label className="col-span-full flex flex-wrap items-center gap-2 text-xs text-gray-500">
          Starting net worth:
          <select
            className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            value={form.startingNetWorthMode}
            onChange={(e) =>
              setForm({ ...form, startingNetWorthMode: e.target.value as "auto" | "custom" })
            }
          >
            <option value="auto">Automatic (accounts and portfolio on the base date)</option>
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
        <p className="col-span-full text-xs text-gray-500">
          Enter monthly inflows and outflows as positive amounts or zero. Future base dates require a custom starting amount.
        </p>

        <input
          type="number"
          className="rounded border border-gray-300 px-2 py-1.5 text-sm"
          placeholder="Monthly inflows €"
          aria-label="Monthly inflows in euros"
          min="0"
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
          min="0"
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
          min="-100"
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
          min="-100"
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
          min="-100"
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
          min="-100"
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
          min="-100"
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
          This form invests positive annual cash flow at each anniversary. The API also accepts a custom monthly investment and dated contributions or withdrawals.
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
          <section className="mb-4" aria-label="Scenario assumptions">
            <h4 className="mb-2 text-sm font-medium">Scenario assumptions</h4>
            <ForecastAssumptions scenario={result.scenario} result={result} />
          </section>
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
          {Object.keys(result.scenarios.base.milestones_reached).length > 0 && (
            <div className="mt-3">
              <h4 className="text-sm font-medium">Base scenario milestones</h4>
              <ul className="mt-1 text-sm text-gray-600">
                {Object.entries(result.scenarios.base.milestones_reached).map(([amount, year]) => (
                  <li key={amount}>
                    {formatEur(Number(amount))} — {year === 0 ? "Reached on the base date" : `Year ${year}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
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
                <Fragment key={s.id}>
                  <tr className="border-t border-gray-100">
                    <td className="px-3 py-2">
                      <input
                        type="checkbox"
                        aria-label={`Include ${s.name} in comparison`}
                        checked={selectedIds.includes(s.id)}
                        onChange={() => toggleSelected(s.id)}
                      />
                    </td>
                    <td className="px-3 py-2">
                      {s.name}
                      <div className="text-xs text-gray-500">Base date {s.base_date}</div>
                    </td>
                    <td className="px-3 py-2">{s.horizon_years} years</td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        aria-expanded={expandedId === s.id}
                        aria-controls={`saved-assumptions-${s.id}`}
                        onClick={() => setExpandedId(expandedId === s.id ? null : s.id)}
                        className="mr-3 text-xs text-blue-600 hover:underline"
                      >
                        {expandedId === s.id ? "Hide assumptions" : "View assumptions"}
                      </button>
                      <button
                        onClick={() => handleRun(s.id)}
                        disabled={createScenario.isPending || runForecast.isPending}
                        className="mr-3 text-xs text-blue-600 hover:underline disabled:opacity-50"
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
                  <tr id={`saved-assumptions-${s.id}`} hidden={expandedId !== s.id}>
                    <td colSpan={4} className="border-t border-gray-100 bg-gray-50 px-3 py-3">
                      {expandedId === s.id && <ForecastAssumptions scenario={s} />}
                    </td>
                  </tr>
                </Fragment>
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
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {comparison.results.map((run, index) => (
              <details key={run.scenario_id} open className="rounded-lg border border-gray-200 bg-white p-3">
                <summary className="cursor-pointer text-sm font-medium">
                  Assumptions — {comparisonChart.series[index].label}
                </summary>
                <div className="mt-3">
                  <ForecastAssumptions scenario={run.scenario} result={run} />
                </div>
              </details>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
