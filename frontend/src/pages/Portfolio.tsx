import { usePortfolioSummary, usePositions } from "@/api/portfolio";
import type { Position } from "@/api/types";
import { formatEur, formatMoney, formatPercent } from "@/lib/formatters";
import { EUR } from "@/lib/currency";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import SortableHeader from "@/components/common/SortableHeader";
import { useTableSort } from "@/lib/useTableSort";
import { calendarDaysSince } from "@/lib/dates";

const STALE_PRICE_DAYS = 7;

/** Portfolio page: current remaining quantities and latest valuations
 * per security. Trading history is on Securities. Specification §7.4. */
export default function Portfolio() {
  const { data: positions, isLoading, error } = usePositions();
  const {
    data: summary,
    isLoading: summaryLoading,
    error: summaryError,
  } = usePortfolioSummary();
  type PositionSortKey = "security" | "quantity" | "average" | "current" | "value" | "gain";
  const positionSort = useTableSort<Position, PositionSortKey>(
    positions ?? [],
    { key: "security", direction: "asc" },
    (position, key) => {
      if (key === "security") return `${position.ticker} ${position.name}`;
      if (key === "quantity") return Number(position.quantity);
      if (key === "average") return Number(position.average_cost_eur);
      if (key === "current") {
        return position.current_price_eur === null ? null : Number(position.current_price_eur);
      }
      if (key === "value") {
        return position.current_value_eur === null ? null : Number(position.current_value_eur);
      }
      return position.unrealized_gain_loss_eur === null
        ? null
        : Number(position.unrealized_gain_loss_eur);
    }
  );
  const fallbackWarning = summary
    ? getPortfolioCostFallbackWarning(summary.portfolio_valuation)
    : null;

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Portfolio</h2>

      {summary && summary.positions_count > 0 && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <KpiCard
            label="Invested capital"
            value={formatEur(Number(summary.total_invested))}
            formula={
              <>
                <Formula>Σ cost of remaining portfolio lots (FIFO)</Formula>
                What you paid for holdings owned <em>now</em>. Sales consume the oldest lots first and reduce this value.
              </>
            }
          />
          <KpiCard
            label="Current value"
            value={formatEur(Number(summary.total_current_value))}
            formula={
              <>
                <Formula>Σ (quantity × latest price × exchange rate)</Formula>
                Valued at the latest available price per security. The table shows its date and warns when it is more than 7 days old.
              </>
            }
          />
          <KpiCard
            label="Unrealised gain/loss"
            value={formatEur(Number(summary.total_unrealized_gain_loss))}
            positive={Number(summary.total_unrealized_gain_loss) >= 0}
            formula={
              <>
                <Formula>Current value − Invested capital</Formula>
                Paper gains or losses on holdings you have not yet sold.
              </>
            }
          />
          <KpiCard
            label="Realised gain/loss"
            value={formatEur(Number(summary.total_realized_gain_loss))}
            positive={Number(summary.total_realized_gain_loss) >= 0}
            formula={
              <>
                <Formula>Σ (sale proceeds − cost of consumed FIFO lots)</Formula>
                Gains or losses already realised through sales, used to calculate capital gains tax.
              </>
            }
          />
        </div>
      )}

      <QueryStateNotice
        isLoading={isLoading || summaryLoading}
        error={error ?? summaryError}
      />

      {fallbackWarning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Quote missing for {fallbackWarning.securitiesLabel}: valuation uses remaining FIFO cost. Price intentionally remains unavailable and gain/loss is zero, keeping the position in totals without implying a market price.
        </div>
      )}

      {positions && (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-gray-500">
              <tr>
                {([
                  ["security", "Security", "left"],
                  ["quantity", "Quantity", "right"],
                  ["average", "Average price", "right"],
                  ["current", "Current price", "right"],
                  ["value", "Value (€)", "right"],
                  ["gain", "Gain/loss (€)", "right"],
                ] as const).map(([key, label, align]) => (
                  <SortableHeader
                    key={key}
                    active={positionSort.sort.key === key}
                    direction={positionSort.sort.direction}
                    onSort={() => positionSort.requestSort(key)}
                    align={align}
                    className="px-3 py-2"
                  >
                    {label}
                  </SortableHeader>
                ))}
              </tr>
            </thead>
            <tbody>
              {positionSort.sortedRows.map((p) => (
                <tr key={p.security_id} className="border-t border-gray-100">
                  <td className="px-3 py-2">
                    <div className="font-medium">
                      {p.ticker}
                      {p.currency !== EUR && (
                        <span
                          className="ml-1.5 rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-normal text-amber-700"
                          title={`Quoted in ${p.currency}: native-currency prices, totals converted to euros`}
                        >
                          {p.currency}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-gray-400">{p.name}</div>
                  </td>
                  <td className="px-3 py-2 text-right">{Number(p.quantity).toLocaleString("it-IT")}</td>
                  {/* Prices use the quote currency shown on the broker statement.
                      The euro value appears below; totals always use euros. */}
                  <td className="px-3 py-2 text-right">
                    {formatMoney(Number(p.average_cost), p.currency)}
                    {p.currency !== EUR && (
                      <div className="text-xs text-gray-400">
                        {formatEur(Number(p.average_cost_eur))}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {p.current_price !== null ? (
                      <>
                        {formatMoney(Number(p.current_price), p.currency)}
                        {p.currency !== EUR && p.current_price_eur !== null && (
                          <div className="text-xs text-gray-400">
                            {formatEur(Number(p.current_price_eur))}
                          </div>
                        )}
                        {p.current_price_date && (() => {
                          const daysSince = calendarDaysSince(p.current_price_date);
                          const isStale = daysSince !== null && daysSince > STALE_PRICE_DAYS;
                          return (
                            <div
                              className={`text-xs ${isStale ? "text-amber-600" : "text-gray-400"}`}
                              title={`Price dated ${p.current_price_date}`}
                            >
                              {p.current_price_date}
                              {isStale && ` ⚠ ${daysSince} days ago`}
                            </div>
                          );
                        })()}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {p.current_value_eur !== null ? (
                      <>
                        {formatEur(Number(p.current_value_eur))}
                        {p.valuation_source === "fifo_cost" && (
                          <div className="text-[10px] font-medium text-amber-700">
                            FIFO cost estimate
                          </div>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-medium ${
                      p.unrealized_gain_loss_eur === null
                        ? "text-gray-400"
                        : Number(p.unrealized_gain_loss_eur) >= 0
                          ? "text-green-600"
                          : "text-red-600"
                    }`}
                  >
                    {p.unrealized_gain_loss_eur !== null ? (
                      <>
                        {formatEur(Number(p.unrealized_gain_loss_eur))}{" "}
                        {p.unrealized_gain_loss_pct_eur !== null && (
                          <span className="text-xs">
                            ({formatPercent(Number(p.unrealized_gain_loss_pct_eur) / 100)})
                          </span>
                        )}
                        {/* For a foreign security, the euro percentage includes exchange-rate
                            effects while the native percentage isolates price changes. */}
                        {p.currency !== EUR && p.unrealized_gain_loss_pct !== null && (
                          <div
                            className="text-xs font-normal text-gray-400"
                            title="Price performance only, excluding exchange-rate effects"
                          >
                            price {formatPercent(Number(p.unrealized_gain_loss_pct) / 100)}
                          </div>
                        )}
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
              {positions.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-gray-400">
                    No portfolio positions. Record a purchase on the Securities page to begin.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
