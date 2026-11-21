import { useState } from "react";
import { useIncomeStatement, type DateRange } from "@/api/reports";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { formatEur, formatPercent } from "@/lib/formatters";

export function SavingsRateMetrics() {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useIncomeStatement(range);

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4" aria-label="Household savings">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-gray-600">Household savings</h3>
          <p className="mt-1 max-w-xl text-xs text-gray-500">
            Income left after spending in the selected period. Buying or selling securities and receiving principal repayments change the form of savings.
            {!range.from && !range.to && " Period: all history."}
          </p>
        </div>
        <DateRangeFilter range={range} onChange={setRange} />
      </div>
      <QueryStateNotice isLoading={isLoading} error={error} />
      {data && (
        <div className="grid gap-3 sm:grid-cols-3">
          <KpiCard label="Economic savings" value={formatEur(Number(data.economic_savings))}
            positive={Number(data.economic_savings) >= 0}
            formula={<><Formula>Economic income − economic spending</Formula>Dividends and coupons enter at their net amount. Recorded trade fees and recurring costs reduce savings.</>}
          />
          <KpiCard label="Economic savings rate" value={data.economic_savings_rate_pct === null ? "—" : formatPercent(Number(data.economic_savings_rate_pct) / 100)}
            formula={<><Formula>Period savings ÷ period economic income × 100</Formula>Includes expenses from months without income. A percentage requires positive income for the selected period.</>}
          />
          <KpiCard
            label="Average monthly cash surplus rate"
            value={data.average_savings_rate_pct === null ? "—" : formatPercent(Number(data.average_savings_rate_pct) / 100)}
            positive={data.average_savings_rate_pct === null ? undefined : Number(data.average_savings_rate_pct) >= 0}
            formula={
              <>
                <Formula>Σ monthly rates capped at P5–P95 ÷ months with a calculable rate</Formula>
                Rates below P5 are raised to P5 and those above P95 are lowered to P95, without excluding months. Percentiles are inclusive with linear interpolation, as in average spending. Monthly rate equals net balance ÷ inflows × 100, including security purchases and sales. Months without inflows are excluded; negative rates are allowed. Monthly detail rates remain unchanged.
              </>
            }
          />
          <p className="col-span-full text-xs leading-relaxed text-gray-500">
            {data.savings_rate_months === 0
              ? "No months with inflows in the period: the average rate cannot be calculated."
              : `Average calculated over ${data.savings_rate_months} ${data.savings_rate_months === 1 ? "month with inflows" : "months with inflows"}.`}
            {" "}Security purchases and sales affect the result, as in the income statement.
          </p>
        </div>
      )}
    </section>
  );
}
