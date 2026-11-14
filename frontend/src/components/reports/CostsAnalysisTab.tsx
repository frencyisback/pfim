import { useState } from "react";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  useCostsAnalysis,
  type CostGroup,
  type CostsAnalysisReport,
  type DateRange,
  type FiscalPosition,
  type UnrealizedTaxSnapshot,
} from "@/api/reports";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { TaxEventsSection } from "@/components/reports/TaxEventsSection";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { CATEGORY_COLORS, pctOrDash } from "@/components/reports/shared";
import { formatEur, formatReturnDrag } from "@/lib/formatters";
import { useTableSort } from "@/lib/useTableSort";

const COST_GROUP_LABELS: Record<string, { title: string; hint: string }> = {
  taxes: {
    title: "Taxes",
    hint: "Capital gains tax and withholding on coupons and dividends.",
  },
  trading: {
    title: "Trading costs",
    hint: "Fees and spreads paid on purchases and sales.",
  },
  recurring: {
    title: "Recurring costs",
    hint: "Stamp duty, custody and account fees apply to the portfolio, rather than individual trades.",
  },
};

const COST_TYPE_LABELS: Record<string, string> = {
  capital_gains_tax: "Capital gains tax",
  withholding_tax: "Withholding tax",
  tax: "Tax",
  commission: "Fee",
  spread: "Spread",
  stamp_duty: "Stamp duty",
  custody_fee: "Custody",
  account_fee: "Custody account fee",
  other: "Other",
};

const taxRateFormat = new Intl.NumberFormat("en-GB", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

/** Investment results, period costs and their estimated impact (specification §11.6). */
export function CostsAnalysisTab() {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useCostsAnalysis(range);

  const pieData =
    data?.groups
      .filter((g) => Number(g.total_eur) > 0)
      .map((g) => ({
        name: COST_GROUP_LABELS[g.group]?.title ?? g.group,
        value: Number(g.total_eur),
      })) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <DateRangeFilter range={range} onChange={setRange} />
        <ExportCsvButton
          endpoint="costs-analysis"
          range={range}
          filename="costs-and-taxation.csv"
        />
      </div>

      <QueryStateNotice isLoading={isLoading} error={error} />

      {data && (
        <>
          {(data.period_from || data.period_to) && (
            <p className="text-xs text-gray-500">
              Calculated period: {data.period_from ?? "start of records"} –{" "}
              {data.period_to ?? "today"}.
            </p>
          )}
          <section className="rounded-lg border border-gray-200 bg-white p-4">
            <h3 className="mb-1 text-sm font-medium text-gray-600">Investment result (gross)</h3>
            <p className="mb-3 text-xs text-gray-600">
              The unrealised component measures the change in open gains and losses over the selected period.
            </p>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
              <KpiCard
                label="Capital gains"
                value={formatEur(Number(data.realized.capital_gains))}
                positive
                formula={
                  <>
                    <Formula>Σ (sale proceeds − cost of consumed FIFO lots)</Formula>
                    Profitable sales only. The oldest lots are consumed first (FIFO).
                  </>
                }
              />
              <KpiCard
                label="Unrealised gain/loss"
                value={eurOrDash(data.unrealized_tax.unrealized_change_eur)}
                positive={data.unrealized_tax.unrealized_change_eur === null ? undefined : Number(data.unrealized_tax.unrealized_change_eur) >= 0}
                formula={<Formula>Closing unrealised gain/loss − Opening unrealised gain/loss</Formula>}
              />
              <KpiCard
                label="Capital losses"
                value={formatEur(Number(data.realized.capital_losses))}
                positive={false}
                formula={
                  <>
                    <Formula>Σ (sale proceeds − cost of consumed FIFO lots)</Formula>
                    Loss-making sales only. These are market losses rather than costs, so they appear here.
                  </>
                }
              />
              <KpiCard
                label="Gross coupons and dividends"
                value={formatEur(Number(data.realized.income_gross))}
                formula={
                  <>
                    <Formula>Σ gross income (before withholding)</Formula>
                    The corresponding withholding is included in taxes below.
                  </>
                }
              />
              <KpiCard
                label="Gross result"
                value={eurOrDash(data.unrealized_tax.economic_gross_result_eur)}
                positive={data.unrealized_tax.economic_gross_result_eur === null ? undefined : Number(data.unrealized_tax.economic_gross_result_eur) >= 0}
                formula={
                  <>
                    <Formula>Capital gains + Capital losses + Gross income + Unrealised gain/loss</Formula>
                    Includes the change in open gains and losses during this period.
                  </>
                }
              />
            </div>
          </section>

          <section className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-medium text-gray-600">Costs incurred</h3>
              {Number(data.total_estimated) > 0 && (
                <span className="text-xs text-amber-600">
                  of which {formatEur(Number(data.total_estimated))} estimated from tax rates
                </span>
              )}
            </div>
            <p className="mb-3 text-xs text-gray-400">
              Items marked <em>estimated</em> are calculated using the rates in Settings. Recording the actual amount replaces the estimate.
            </p>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div>
                {pieData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={240}>
                    <PieChart>
                      <Pie
                        data={pieData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={85}
                        label={(e) => e.name}
                        isAnimationActive={false}
                      >
                        {pieData.map((_, i) => (
                          <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v: number) => formatEur(v)} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <p className="flex h-[240px] items-center justify-center text-sm text-gray-400">
                    No costs in this period.
                  </p>
                )}
              </div>
              <div className="flex flex-col justify-center gap-3">
                <KpiCard
                  label="Total incurred costs"
                  value={formatEur(Number(data.total_costs))}
                  positive={false}
                  formula={
                    <>
                      <Formula>Taxes + Trading costs + Recurring costs</Formula>
                      All costs for the period. Estimated items use the rates in Settings, rather than tax documents.
                    </>
                  }
                />
                <KpiCard
                  label="Net realised result"
                  value={formatEur(Number(data.net_result))}
                  positive={Number(data.net_result) >= 0}
                  formula={
                    <>
                      <Formula>Realised gross result − Incurred costs</Formula>
                      Realised gross result includes gains and losses on sales, gross coupons and dividends.
                    </>
                  }
                />
              </div>
            </div>
          </section>

          {data.current_stamp_duty_estimate && (
            <section className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium">Current annual stamp duty estimate</h3>
                <span className="font-semibold">
                  {formatEur(Number(data.current_stamp_duty_estimate.amount_eur))}
                </span>
              </div>
              <p className="mt-1 text-xs text-amber-800">
                {data.current_stamp_duty_estimate.description}. This separate informational figure is excluded from incurred costs, the net result and cost ratios for the period.
              </p>
            </section>
          )}

          <FiscalPositionBlock fiscal={data.fiscal} />

          {data.groups.map((g) => (
            <CostGroupTable key={g.group} group={g} />
          ))}

          <UnrealizedTaxBlock closing={data.unrealized_tax.closing} rate={data.fiscal.tax_rate_pct} />
          <ImpactMetrics report={data} />

          <section className="rounded-lg border border-gray-200 bg-white p-4">
            <TaxEventsSection range={range} />
          </section>

          <p className="text-xs italic text-gray-500">{data.disclaimer}</p>
        </>
      )}
    </div>
  );
}

/** Explains the capital gains tax estimate. The tax rate applies to net
 * gains after losses, rather than each profitable sale individually. */
function FiscalPositionBlock({ fiscal }: { fiscal: FiscalPosition }) {
  const hasLosses = Number(fiscal.capital_losses) !== 0;
  const hasWithheld = Number(fiscal.tax_already_withheld) > 0;

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Tax on realised capital gains</h3>
      <p className="mb-3 max-w-3xl text-xs text-gray-400">
        Capital losses <strong>offset</strong> capital gains: the rate applies to the net amount, rather than each gain separately.
      </p>

      <div className="max-w-xl space-y-1 text-sm">
        <FiscalRow label="Realised capital gains" value={Number(fiscal.capital_gains)} />
        {hasLosses && (
          <FiscalRow label="Eligible capital losses" value={Number(fiscal.capital_losses)} />
        )}
        <FiscalRow
          label="Taxable base (net)"
          value={Number(fiscal.net_capital_gain_loss)}
          strong
        />
        <FiscalRow
          label={`Tax at ${taxRateFormat.format(Number(fiscal.tax_rate_pct))}%`}
          value={-Number(fiscal.gross_estimated_tax)}
        />
        {hasWithheld && (
          <FiscalRow
            label="of which already withheld and recorded"
            value={Number(fiscal.tax_already_withheld)}
          />
        )}
        <div className="border-t border-gray-200 pt-1">
          <FiscalRow
            label="Estimated tax still payable"
            value={-Number(fiscal.estimated_tax_due)}
            strong
          />
        </div>
      </div>

      {Number(fiscal.net_capital_gain_loss) < 0 && (
        <p className="mt-3 max-w-3xl text-xs text-amber-700">
          The net realised loss gives a zero tax estimate on sales for this period. PFIM excludes loss carryforwards.
        </p>
      )}
    </section>
  );
}

function FiscalRow({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: number;
  strong?: boolean;
}) {
  // JavaScript supports `-0`, which formats as "-0,00 €". Normalising it
  // avoids a minus sign before an amount that is simply zero.
  const amount = value === 0 ? 0 : value;
  return (
    <div className={`flex justify-between gap-4 ${strong ? "font-medium" : ""}`}>
      <span className={strong ? "text-gray-800" : "text-gray-500"}>{label}</span>
      <span className={amount < 0 ? "text-red-600" : "text-gray-800"}>{formatEur(amount)}</span>
    </div>
  );
}

function eurOrDash(value: string | null) {
  return value === null ? "—" : formatEur(Number(value));
}

function UnrealizedTaxBlock({
  closing,
  rate,
}: {
  closing: UnrealizedTaxSnapshot;
  rate: string;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Estimated tax on open positions</h3>
      <p className="mb-3 max-w-3xl text-xs text-gray-600">
        The estimate applies the configured {taxRateFormat.format(Number(rate))}% rate to the
        positive net gain if all open holdings were sold at their last recorded EUR values
        through the closing date. Open losses offset open gains.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-200 text-left text-xs text-gray-500">
            <tr>
              <th scope="col" className="p-2">Closing date</th>
              <th scope="col" className="p-2 text-right">Open positions</th>
              <th scope="col" className="p-2 text-right">Net unrealised gain or loss</th>
              <th scope="col" className="p-2 text-right">Estimated tax</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-b border-gray-100">
              <th scope="row" className="p-2 text-left font-medium">{closing.as_of ?? "—"}</th>
              <td className="p-2 text-right">{closing.open_positions}</td>
              <td className="p-2 text-right">{eurOrDash(closing.net_unrealized_eur)}</td>
              <td className="p-2 text-right font-medium">{eurOrDash(closing.estimated_tax_eur)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {closing.missing_price_tickers.length > 0 && (
        <p className="mt-2 text-xs text-amber-800">
          Closing valuation unavailable. Missing EUR prices for {closing.missing_price_tickers.join(", ")}.
        </p>
      )}
    </section>
  );
}

function CostGroupTable({ group }: { group: CostGroup }) {
  const meta = COST_GROUP_LABELS[group.group] ?? { title: group.group, hint: "" };
  type CostSortKey = "date" | "type" | "description" | "amount";
  const itemSort = useTableSort(
    group.items,
    { key: "date" as CostSortKey, direction: "desc" },
    (item, key) => {
      if (key === "date") return item.date;
      if (key === "type") return COST_TYPE_LABELS[item.cost_type] ?? item.cost_type;
      if (key === "description") return item.description;
      return Number(item.amount_eur);
    }
  );
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-600">{meta.title}</h3>
        <span className="text-sm font-semibold">
          {formatEur(Number(group.total_eur))}{" "}
          <span className="text-xs font-normal text-gray-400">
            ({Number(group.pct_of_total).toFixed(1)}% of costs)
          </span>
        </span>
      </div>
      <p className="mb-3 text-xs text-gray-400">{meta.hint}</p>
      {group.items.length > 0 ? (
        <CollapsibleTable title={`Details: ${meta.title.toLowerCase()}`} count={group.items.length}>
          <div className="overflow-hidden rounded border border-gray-200">
            <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["date", "Date", "left"],
                  ["type", "Type", "left"],
                  ["description", "Description", "left"],
                  ["amount", "Amount", "right"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={itemSort.sort.key === key}
                    direction={itemSort.sort.direction}
                    onSort={() => itemSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
              </tr>
            </thead>
            <tbody>
              {itemSort.sortedRows.map((i, idx) => (
                <tr key={`${i.cost_type}-${idx}`} className="border-t border-gray-100">
                  <td className="px-3 py-2">{i.date ?? "—"}</td>
                  <td className="px-3 py-2">
                    {COST_TYPE_LABELS[i.cost_type] ?? i.cost_type}
                    {i.is_estimated && (
                      <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                        estimated
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-gray-500">{i.description}</td>
                  <td className="px-3 py-2 text-right font-medium text-red-600">
                    {formatEur(Number(i.amount_eur))}
                  </td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
        </CollapsibleTable>
      ) : (
        <p className="py-4 text-center text-sm text-gray-400">No costs of this type.</p>
      )}
    </div>
  );
}

function percentValueOrDash(value: string | null) {
  return value === null ? "—" : `${Number(value).toFixed(2)}%`;
}

function ImpactMetrics({ report }: { report: CostsAnalysisReport }) {
  const { impact, unrealized_tax: projection } = report;
  const drag = impact.estimated_twr_drag_pct_points;
  const inputs = [
    {
      label: "Days included",
      value: impact.period_days ?? "—",
      note: `${report.period_from ?? "Start of records"} – ${report.period_to ?? "today"}`,
    },
    { label: "Average invested capital (FIFO)", value: eurOrDash(impact.average_invested_capital) },
    { label: "Average portfolio value", value: eurOrDash(impact.average_quoted_portfolio_value) },
    { label: "Realised gross result", value: eurOrDash(report.realized.gross_result) },
    { label: "Unrealised gain/loss for the period", value: eurOrDash(projection.unrealized_change_eur) },
    { label: "Gross result", value: eurOrDash(projection.economic_gross_result_eur) },
    { label: "Incurred costs", value: eurOrDash(report.total_costs) },
    {
      label: "Change in estimated tax",
      value: eurOrDash(projection.tax_change_eur),
      note: `Capital gains tax rate ${taxRateFormat.format(Number(report.fiscal.tax_rate_pct))}%`,
    },
    { label: "Costs including tax change", value: eurOrDash(projection.projected_period_costs_eur) },
  ];

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Impact on performance</h3>
      <p className="mb-3 max-w-3xl text-xs text-gray-600">
        The cost ratios use incurred costs plus the change in estimated tax on open positions.
        A fall in this estimate reduces the period’s costs.
      </p>
      {projection.opening.missing_price_tickers.length > 0 && (
        <p className="mb-3 text-xs text-amber-800">
          Opening valuation unavailable at {projection.opening.as_of}.
          Missing EUR prices for {projection.opening.missing_price_tickers.join(", ")}.
        </p>
      )}
      <dl className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
        {inputs.map(({ label, value, note }) => (
          <div key={label} className="rounded bg-gray-50 px-3 py-2">
            <dt className="text-xs text-gray-600">{label}</dt>
            <dd className="text-sm font-semibold text-gray-900">{value}</dd>
            {note && <dd className="text-xs text-gray-500">{note}</dd>}
          </div>
        ))}
      </dl>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <KpiCard
          label="Relative to invested capital"
          value={percentValueOrDash(impact.projected_pct_of_invested)}
          formula={<Formula>Costs including tax change ÷ Average invested capital (FIFO) × 100</Formula>}
        />
        <KpiCard
          label="Relative to gross result"
          value={percentValueOrDash(projection.projected_cost_impact_pct)}
          formula={
            <>
              <Formula>Costs including tax change ÷ Gross result × 100</Formula>
              Available when the period’s gross result is positive.
            </>
          }
        />
        <KpiCard
          label="Annual cost ratio (TER-like)"
          value={percentValueOrDash(impact.projected_annual_incidence_pct)}
          formula={
            <>
              <Formula>Costs including tax change ÷ Average portfolio value × 365 ÷ Days included × 100</Formula>
              The average uses each holding’s last recorded quote on or before each day of the period.
              The annualised ratio includes estimated taxes.
            </>
          }
        />
        <KpiCard
          label="TWR before costs"
          value={pctOrDash(impact.twr_gross)}
          formula={
            <>
              <Formula>Product of subperiod return factors − 1</Formula>
              Uses market values, trade flows and investment income net of withholding.
            </>
          }
        />
        <KpiCard
          label="TWR after costs (estimated)"
          value={pctOrDash(impact.estimated_twr_net)}
          formula={
            <>
              <Formula>Product of after-cost subperiod return factors − 1</Formula>
              Values include trading costs, recurring charges and estimated capital gains tax.
              At a sale, recorded withholding or the remaining tax due replaces the estimate on the sold lots.
            </>
          }
        />
        <KpiCard
          label="Return reduction"
          value={drag === null ? "—" : formatReturnDrag(Number(drag))}
          formula={<Formula>TWR before costs − TWR after costs (estimated), in percentage points</Formula>}
        />
      </div>
    </section>
  );
}
