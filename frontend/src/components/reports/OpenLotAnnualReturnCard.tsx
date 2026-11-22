import type { OpenLotAnnualReturnReason, PortfolioPerformance } from "@/api/performance";
import KpiCard, { Formula } from "@/components/common/KpiCard";
import { getPortfolioCostFallbackWarning } from "@/lib/portfolioValuation";
import { pctOrDash } from "./shared";

type ReturnData = Pick<PortfolioPerformance,
  "total_return_annualized" | "total_return_annualized_unavailable_reason" | "portfolio_valuation"
>;

const reasonText: Record<Exclude<OpenLotAnnualReturnReason, "missing_quote">, string> = {
  no_open_cost: "There are no open holdings with a positive acquisition cost.",
  no_elapsed_days: "All remaining lots were bought today. At least one day must elapse.",
  undefined_rate: "The lot costs and ending value do not yield a representable annual rate.",
};

export default function OpenLotAnnualReturnCard({ performance }: { performance: ReturnData }) {
  const rate = performance.total_return_annualized;
  const reason = performance.total_return_annualized_unavailable_reason;
  let note: string | undefined;
  if (rate === null) {
    if (reason === "missing_quote") {
      const tickers = getPortfolioCostFallbackWarning(performance.portfolio_valuation)?.tickers;
      note = tickers?.length
        ? `A market quote is missing for ${tickers.join(", ")}.`
        : "A market quote is missing for at least one open holding.";
    } else {
      note = reason ? reasonText[reason] : "The annual rate is unavailable.";
    }
  }
  return (
    <KpiCard
      label="Annualised return on open lots"
      value={pctOrDash(rate)}
      positive={rate === null ? undefined : Number(rate) >= 0}
      note={note}
      formula={
        <>
          <Formula>Σ remaining cost by purchase date × (1 + r)^(days held ÷ 365) = market value + attributed distributions − included costs</Formula>
          Each remaining FIFO lot grows from its purchase date at the same annual rate r.
          Distributions enter once at their recorded amount, without reinvestment.
          When costs are included, the ending amount deducts the purchase costs attributable to the remaining units.
        </>
      }
    />
  );
}
