import { useState } from "react";
import { useIncomeStatement, type DateRange } from "@/api/reports";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import QueryStateNotice from "@/components/common/QueryStateNotice";
import { DateRangeFilter } from "@/components/reports/DateRangeFilter";
import { formatPercent } from "@/lib/formatters";

export function SavingsRateMetrics() {
  const [range, setRange] = useState<DateRange>({});
  const { data, isLoading, error } = useIncomeStatement(range);

  return (
    <section className="rounded-lg border border-gray-200 bg-white p-4" aria-label="Average savings">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-gray-600">Average savings</h3>
          <p className="mt-1 max-w-xl text-xs text-gray-500">
            Average monthly income statement rates, with extreme values capped at percentiles P5–P95 as in average spending. The period selected here applies to this indicator.
            {!range.from && !range.to && " Period: all history."}
          </p>
        </div>
        <DateRangeFilter range={range} onChange={setRange} />
      </div>
      <QueryStateNotice isLoading={isLoading} error={error} />
      {data && (
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_2fr]">
          <KpiCard
            label="Average savings rate"
            value={data.average_savings_rate_pct === null ? "—" : formatPercent(Number(data.average_savings_rate_pct) / 100)}
            positive={data.average_savings_rate_pct === null ? undefined : Number(data.average_savings_rate_pct) >= 0}
            formula={
              <>
                <Formula>Σ monthly rates capped at P5–P95 ÷ months with a calculable rate</Formula>
                Rates below P5 are raised to P5 and those above P95 are lowered to P95, without excluding months. Percentiles are inclusive with linear interpolation, as in average spending. Monthly rate equals net balance ÷ inflows × 100, including security purchases and sales. Months without inflows are excluded; negative rates are allowed. Monthly detail rates remain unchanged.
              </>
            }
          />
          <p className="self-center text-xs leading-relaxed text-gray-500">
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
