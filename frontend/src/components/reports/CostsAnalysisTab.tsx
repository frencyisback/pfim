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
  type CostImpact,
  type DateRange,
  type FiscalPosition,
  type UnrealizedTaxProjection,
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

/** Costs and taxation (specification §11.6). Distinguishes realised gross
 * performance from the costs reducing it, making net earnings clear. */
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
            <h3 className="mb-1 text-sm font-medium text-gray-600">Realised result (gross)</h3>
            <p className="mb-3 text-xs text-gray-400">
              Investment earnings before costs. Capital losses are market losses, so they appear here rather than in the costs below.
            </p>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
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
                value={formatEur(Number(data.realized.gross_result))}
                positive={Number(data.realized.gross_result) >= 0}
                formula={
                  <>
                    <Formula>Capital gains + Capital losses + Gross income</Formula>
                    Investment earnings before costs.
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
                      <Formula>Gross result − Total costs</Formula>
                      Earnings remaining after costs.
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

          <UnrealizedTaxBlock projection={data.unrealized_tax} rate={data.fiscal.tax_rate_pct} />
          <ImpactMetrics impact={data.impact} projection={data.unrealized_tax} />

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
          The period has a net loss, so no tax is estimated. Version 1.0 does not carry losses forward to subsequent years, which regulations allow up to the fourth year; future tax benefits are therefore not shown.
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
  projection,
  rate,
}: {
  projection: UnrealizedTaxProjection;
  rate: string;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Estimated tax on open positions</h3>
      <p className="mb-3 max-w-3xl text-xs text-gray-600">
        A sale of all open holdings at their last recorded prices would incur an estimated
        {" "}{taxRateFormat.format(Number(rate))}% tax on any net gain over their remaining FIFO cost.
        Open losses offset open gains. Each valuation uses prices available by the date shown.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-200 text-left text-xs text-gray-500">
            <tr>
              <th scope="col" className="p-2">Valuation</th>
              <th scope="col" className="p-2 text-right">Open positions</th>
              <th scope="col" className="p-2 text-right">Net unrealised gain or loss</th>
              <th scope="col" className="p-2 text-right">Estimated tax</th>
            </tr>
          </thead>
          <tbody>
            <TaxSnapshotRow label="Opening" snapshot={projection.opening} />
            <TaxSnapshotRow label="Closing" snapshot={projection.closing} />
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TaxSnapshotRow({ label, snapshot }: { label: string; snapshot: UnrealizedTaxSnapshot }) {
  return (
    <tr className="border-b border-gray-100 align-top">
      <th scope="row" className="p-2 text-left font-medium">
        {label}
        <span className="block text-xs font-normal text-gray-500">{snapshot.as_of ?? "Start of records"}</span>
        {snapshot.missing_price_tickers.length > 0 && (
          <span className="block text-xs font-normal text-amber-800">
            Missing EUR valuation for {snapshot.missing_price_tickers.join(", ")}.
          </span>
        )}
      </th>
      <td className="p-2 text-right">{snapshot.open_positions}</td>
      <td className="p-2 text-right">{eurOrDash(snapshot.net_unrealized_eur)}</td>
      <td className="p-2 text-right font-medium">{eurOrDash(snapshot.estimated_tax_eur)}</td>
    </tr>
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

function ImpactMetrics({ impact, projection }: { impact: CostImpact; projection: UnrealizedTaxProjection }) {
  const drag = impact.twr_drag_pct_points;
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Impact on performance</h3>
      <p className="mb-3 text-xs text-gray-600">
        Period costs include recorded costs and estimated tax still payable on realised gains.
      </p>
      <div className="mb-3 grid grid-cols-1 gap-2 text-xs text-gray-600 sm:grid-cols-3">
        <div className="rounded bg-gray-50 px-3 py-2">
          Days included: <strong>{impact.period_days ?? "—"}</strong>
        </div>
        <div className="rounded bg-gray-50 px-3 py-2">
          Average invested capital:{" "}
          <strong>
            {impact.average_invested_capital === null
              ? "—"
              : formatEur(Number(impact.average_invested_capital))}
          </strong>
        </div>
        <div className="rounded bg-gray-50 px-3 py-2">
          Average portfolio value:{" "}
          <strong>
            {impact.average_portfolio_value === null
              ? "—"
              : formatEur(Number(impact.average_portfolio_value))}
          </strong>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label="Relative to invested capital"
          value={impact.pct_of_invested === null ? "—" : `${Number(impact.pct_of_invested).toFixed(2)}%`}
          formula={
            <>
              <Formula>Total costs ÷ Average invested capital during the period</Formula>
              The amount spent on costs for every €100 invested on average during the period.
            </>
          }
        />
        <KpiCard
          label="Relative to realised gross result"
          value={
            impact.pct_of_gross_result === null
              ? "—"
              : `${Number(impact.pct_of_gross_result).toFixed(1)}%`
          }
          formula={
            <>
              <Formula>Total costs ÷ Gross result</Formula>
              The share of earnings consumed by costs. Unavailable ("—") when the gross result is not positive, since dividing by a loss would not be meaningful.
            </>
          }
        />
        <KpiCard
          label="Annual cost ratio (TER-like)"
          value={
            impact.annual_incidence_pct === null
              ? "—"
              : `${Number(impact.annual_incidence_pct).toFixed(2)}%`
          }
          formula={
            <>
              <Formula>(Costs ÷ Average portfolio value) × (365 ÷ Days in period)</Formula>
              Annualised for comparison with an ETF's published TER.
            </>
          }
        />
        <KpiCard
          label="Return reduction"
          value={drag === null ? "—" : formatReturnDrag(Number(drag))}
          positive={false}
          formula={
            <>
              <Formula>Gross TWR − Net TWR</Formula>
              The percentage points by which costs reduce portfolio returns.
            </>
          }
        />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-2">
        <KpiCard
          label="TWR before costs"
          value={pctOrDash(impact.twr_gross)}
          formula={
            <>
              <Formula>TWR with flows = trade values only</Formula>
              Fees and recurring costs are excluded.
            </>
          }
        />
        <KpiCard
          label="TWR after costs"
          value={pctOrDash(impact.twr_net)}
          formula={
            <>
              <Formula>TWR with flows = trade values + costs</Formula>
              A purchase requires more capital for the same securities, while a sale returns less. Recurring costs consume invested capital without buying securities. Coupon withholding is already deducted in both variants.
            </>
          }
        />
      </div>
      <h4 className="mb-1 mt-5 text-sm font-medium text-gray-700">Cost impact including unrealised gains and losses</h4>
      <p className="mb-3 max-w-3xl text-xs text-gray-600">
        This estimate adds the period’s change in tax on open positions to incurred costs.
        When an open gain becomes realised, its opening tax estimate is released.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label="Change in estimated tax"
          value={eurOrDash(projection.tax_change_eur)}
          formula={<Formula>Closing estimated tax − Opening estimated tax</Formula>}
        />
        <KpiCard
          label="Costs including tax change"
          value={eurOrDash(projection.projected_period_costs_eur)}
          formula={<Formula>Incurred costs + Change in estimated tax</Formula>}
        />
        <KpiCard
          label="Gross result including unrealised change"
          value={eurOrDash(projection.economic_gross_result_eur)}
          formula={<Formula>Gross realised result + Closing unrealised gain or loss − Opening unrealised gain or loss</Formula>}
        />
        <KpiCard
          label="Estimated share of gross result consumed by costs"
          value={projection.projected_cost_impact_pct === null ? "—" : `${Number(projection.projected_cost_impact_pct).toFixed(2)}%`}
          formula={
            <>
              <Formula>Costs including tax change ÷ Gross result including unrealised change × 100</Formula>
              Calculated when both valuations are available and the gross result is positive.
              A negative share indicates that the tax estimate fell by more than the costs incurred.
            </>
          }
        />
      </div>
    </div>
  );
}
