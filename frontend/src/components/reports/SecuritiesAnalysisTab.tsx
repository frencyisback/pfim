import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import {
  useSecuritiesAnalysis,
  type PortfolioConcentration,
  type SecuritiesByClassification,
  type SecuritiesByCurrency,
  type SecurityPositionItem,
} from "@/api/reports";
import ExportCsvButton from "@/components/common/ExportCsvButton";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import CollapsibleTable from "@/components/common/CollapsibleTable";
import SortableHeader from "@/components/common/SortableHeader";
import { CATEGORY_COLORS } from "@/components/reports/shared";
import { formatEur, formatPercent } from "@/lib/formatters";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";
import { securityTypeLabel } from "@/lib/securityTypes";
import { useTableSort } from "@/lib/useTableSort";

/** Current securities portfolio analysis (specification §7.5): allocation
 * by type and rankings by value, gain and loss. Fully sold positions are
 * excluded; trading history remains on the Securities page. */
export function SecuritiesAnalysisTab() {
  const { data, isLoading, error } = useSecuritiesAnalysis();

  const pieData =
    data?.by_type.map((t) => ({
      name: securityTypeLabel(t.type),
      value: Number(t.total_value),
    })) ?? [];
  const fallbackWarning = data
    ? getPortfolioCostFallbackWarning(data.portfolio_valuation)
    : null;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <ExportCsvButton endpoint="securities-analysis" filename="securities-analysis.csv" />
      </div>
      <QueryStateNotice isLoading={isLoading} error={error} />
      {fallbackWarning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Quote missing for {fallbackWarning.securitiesLabel}: these positions are included in the report and export at remaining FIFO cost, marked as estimates.
        </div>
      )}
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <KpiCard label="Portfolio value" value={formatEur(Number(data.total_value))} />
            <KpiCard label="Open positions" value={String(data.positions_count)} />
            <KpiCard label="Instrument types" value={String(data.by_type.length)} />
          </div>

          <ConcentrationBlock
            concentration={data.concentration}
            positionsCount={data.positions_count}
          />

          <CurrencyExposure rows={data.by_currency} />

          <div>
            <p className="mb-3 text-xs text-gray-500">
              Sector, industry and country are summary classifications assigned to each security. For ETFs, they do not represent weighted exposure to underlying holdings.
            </p>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <ClassificationBreakdown title="Sector" rows={data.by_sector} />
              <ClassificationBreakdown title="Industry" rows={data.by_industry} />
              <ClassificationBreakdown title="Country" rows={data.by_country} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-600">Allocation by type</h3>
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
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
                <p className="flex h-[260px] items-center justify-center text-sm text-gray-400">
                  No portfolio positions.
                </p>
              )}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <h3 className="mb-3 text-sm font-medium text-gray-600">Detail by type</h3>
              <ul className="space-y-1 text-sm">
                {data.by_type.map((t) => (
                  <li key={t.type} className="flex justify-between border-b border-gray-50 py-1">
                    <span className="text-gray-600">
                      {securityTypeLabel(t.type)}{" "}
                      <span className="text-xs text-gray-400">
                        ({t.positions_count} {t.positions_count === 1 ? "security" : "securities"})
                      </span>
                    </span>
                    <span className="font-medium">
                      {formatEur(Number(t.total_value))}{" "}
                      <span className="text-xs text-gray-400">
                        ({Number(t.pct_of_total).toFixed(1)}%)
                      </span>
                    </span>
                  </li>
                ))}
                {data.by_type.length === 0 && (
                  <li className="py-4 text-center text-gray-400">
                    No portfolio positions.
                  </li>
                )}
              </ul>
            </div>
          </div>

          <PositionRanking
            title="Top 10 securities by value"
            items={data.top_by_value}
            emptyLabel="No portfolio positions."
            mode="value"
          />

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <PositionRanking
              title="Top 10 gainers"
              items={data.top_gainers}
              emptyLabel="No profitable positions."
              mode="pct"
            />
            <PositionRanking
              title="Top 10 losers"
              items={data.top_losers}
              emptyLabel="No loss-making positions."
              mode="pct"
            />
          </div>
        </>
      )}
    </div>
  );
}

/** Concentration (specification §7.5): shows portfolio dependence on a
 * small number of securities, beyond a ranking by individual value. */
function ConcentrationBlock({
  concentration,
  positionsCount,
}: {
  concentration: PortfolioConcentration;
  positionsCount: number;
}) {
  const top = concentration.top_weight_pct;
  const effective = concentration.effective_holdings;
  const effectiveNum = effective === null ? null : Number(effective);
  // A security exceeding one third of the portfolio creates strong dependence.
  const topIsHeavy = top !== null && Number(top) > 33;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-1 text-sm font-medium text-gray-600">Concentration</h3>
      <p className="mb-3 text-xs text-gray-400">
        How much the portfolio depends on a few securities. The <strong>effective number of securities</strong> is the equivalent number of equally weighted holdings: with 10 securities but one accounting for 80%, the value stays close to 1, as if the portfolio held only one security.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiCard
          label={`Largest holding${concentration.top_ticker ? ` (${concentration.top_ticker})` : ""}`}
          value={top === null ? "—" : `${Number(top).toFixed(1)}%`}
          positive={top === null ? undefined : !topIsHeavy}
          formula={
            <>
              <Formula>Largest security value ÷ Portfolio value</Formula>
              Above one third, its performance largely determines the overall result.
            </>
          }
        />
        <KpiCard
          label="Top 3"
          value={
            concentration.top3_weight_pct === null
              ? "—"
              : `${Number(concentration.top3_weight_pct).toFixed(1)}%`
          }
          formula={
            <>
              <Formula>Σ value of the 3 largest securities ÷ Portfolio value</Formula>
              The share of the portfolio held in just three positions.
            </>
          }
        />
        <KpiCard
          label="Top 5"
          value={
            concentration.top5_weight_pct === null
              ? "—"
              : `${Number(concentration.top5_weight_pct).toFixed(1)}%`
          }
          formula={
            <>
              <Formula>Σ value of the 5 largest securities ÷ Portfolio value</Formula>
              With five or fewer securities, this is always 100%.
            </>
          }
        />
        <KpiCard
          label="Effective securities"
          value={
            effectiveNum === null
              ? "—"
              : `${effectiveNum.toFixed(1)} out of ${positionsCount}`
          }
          formula={
            <>
              <Formula>1 ÷ Σ(weight of each security)²</Formula>
              Inverse Herfindahl index: the number of <em>equally weighted securities</em> equivalent to this portfolio. Four securities at 25% each give exactly 4; if one accounts for 80%, it falls close to 1.
            </>
          }
        />
      </div>
      {topIsHeavy && (
        <p className="mt-3 text-xs text-amber-700">
          {concentration.top_ticker} alone accounts for more than one third of the portfolio, largely determining its overall performance.
        </p>
      )}
    </div>
  );
}

/** Currency exposure: values throughout the app are converted to EUR,
 * but this view reveals the remaining exchange-rate risk. */
function CurrencyExposure({ rows }: { rows: SecuritiesByCurrency[] }) {
  if (rows.length === 0) return null;
  const nonEur = rows.filter((r) => r.currency !== "EUR");
  const foreignPct = nonEur.reduce((sum, r) => sum + Number(r.pct_of_total), 0);

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-gray-600">Currency exposure</h3>
        {nonEur.length > 0 && (
          <span className="text-xs text-amber-700">
            {foreignPct.toFixed(1)}% exposed to exchange rates
          </span>
        )}
      </div>
      <p className="mb-3 text-xs text-gray-400">
        Values converted to euros. Non-EUR holdings are affected by exchange rates as well as security performance.
      </p>
      <ul className="space-y-1 text-sm">
        {rows.map((r) => (
          <li key={r.currency} className="flex justify-between border-b border-gray-50 py-1">
            <span className="text-gray-600">
              {r.currency}{" "}
              <span className="text-xs text-gray-400">
                ({r.positions_count} {r.positions_count === 1 ? "security" : "securities"})
              </span>
            </span>
            <span className="font-medium">
              {formatEur(Number(r.total_value))}{" "}
              <span className="text-xs text-gray-400">
                ({Number(r.pct_of_total).toFixed(1)}%)
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClassificationBreakdown({
  title,
  rows,
}: {
  title: string;
  rows: SecuritiesByClassification[];
}) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 className="mb-3 text-sm font-medium text-gray-600">Allocation by {title.toLowerCase()}</h3>
      {rows.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {rows.map((row) => (
            <li key={row.key} className="flex justify-between gap-3 border-b border-gray-50 py-1">
              <span className="min-w-0 truncate text-gray-600" title={row.key}>
                {row.key}
                <span className="ml-1 text-xs text-gray-400">({row.positions_count})</span>
              </span>
              <span className="shrink-0 text-right font-medium">
                {formatEur(Number(row.total_value))}
                <span className="ml-1 text-xs text-gray-400">
                  ({Number(row.pct_of_total).toFixed(1)}%)
                </span>
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-4 text-center text-sm text-gray-400">No portfolio positions.</p>
      )}
    </div>
  );
}

function PositionRanking({
  title,
  items,
  emptyLabel,
  mode,
}: {
  title: string;
  items: SecurityPositionItem[];
  emptyLabel: string;
  mode: "value" | "pct";
}) {
  type RankingSortKey =
    | "ticker"
    | "type"
    | "sector"
    | "industry"
    | "country"
    | "value"
    | "change";
  const rankingSort = useTableSort<SecurityPositionItem, RankingSortKey>(
    items,
    { key: mode === "value" ? "value" : "change", direction: "desc" },
    (item, key) => {
      if (key === "ticker") return `${item.ticker} ${item.name}`;
      if (key === "type") return securityTypeLabel(item.type);
      if (key === "sector") return item.sector;
      if (key === "industry") return item.industry;
      if (key === "country") return item.country;
      if (key === "value") return Number(item.current_value);
      return mode === "value"
        ? Number(item.unrealized_gain_loss)
        : item.unrealized_gain_loss_pct === null
          ? null
          : Number(item.unrealized_gain_loss_pct);
    }
  );

  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <h3 className="mb-3 text-sm font-medium text-gray-600">{title}</h3>
        <p className="py-6 text-center text-sm text-gray-400">{emptyLabel}</p>
      </div>
    );
  }

  return (
    <CollapsibleTable title={title} count={items.length}>
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["ticker", "Security", "left"],
                  ["type", "Type", "left"],
                  ["sector", "Sector", "left"],
                  ["industry", "Industry", "left"],
                  ["country", "Country", "left"],
                  ["value", "Value", "right"],
                  ["change", mode === "value" ? "Gain/loss" : "Change", "right"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={rankingSort.sort.key === key}
                    direction={rankingSort.sort.direction}
                    onSort={() => rankingSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
              </tr>
            </thead>
            <tbody>
              {rankingSort.sortedRows.map((i) => {
                const gain = Number(i.unrealized_gain_loss);
                return (
                  <tr key={i.security_id} className="border-t border-gray-100">
                    <td className="px-3 py-2">
                      <div className="font-medium">{i.ticker}</div>
                      <div className="text-xs text-gray-400">{i.name}</div>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {securityTypeLabel(i.type)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">{i.sector ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">{i.industry ?? "—"}</td>
                    <td className="px-3 py-2 text-xs text-gray-500">{i.country ?? "—"}</td>
                    <td className="px-3 py-2 text-right">
                      {formatEur(Number(i.current_value))}
                      {i.valuation_source === "fifo_cost" && (
                        <div className="text-[10px] font-medium text-amber-700">
                          FIFO cost estimate
                        </div>
                      )}
                    </td>
                    <td
                      className={`px-3 py-2 text-right font-medium ${
                        gain >= 0 ? "text-green-600" : "text-red-600"
                      }`}
                    >
                      {formatEur(gain)}
                      {i.unrealized_gain_loss_pct !== null && (
                        <span className="ml-1 text-xs">
                          ({formatPercent(Number(i.unrealized_gain_loss_pct) / 100)})
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
      </div>
    </CollapsibleTable>
  );
}
