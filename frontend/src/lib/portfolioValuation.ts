import type { PortfolioValuationMetadata } from "@/api/reports";

export interface PortfolioCostFallbackWarning {
  tickers: string[];
  securitiesLabel: string;
}

/** Map valuation metadata to the minimal warning model. The backend flag
 * is authoritative; missing details must not create an empty sentence. */
export function getPortfolioCostFallbackWarning(
  metadata: PortfolioValuationMetadata
): PortfolioCostFallbackWarning | null {
  if (!metadata.cost_fallback_used) return null;

  const tickers = Array.from(
    new Set(
      metadata.cost_fallback_securities
        .map((security) => security.ticker.trim())
        .filter(Boolean)
    )
  );

  return {
    tickers,
    securitiesLabel: tickers.length > 0 ? tickers.join(", ") : "one or more securities",
  };
}
