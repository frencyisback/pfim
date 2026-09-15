import { describe, expect, it } from "vitest";

import type { PortfolioValuationMetadata } from "@/api/reports";
import { getPortfolioCostFallbackWarning } from "./portfolioValuation";

const baseMetadata: PortfolioValuationMetadata = {
  price_policy: "latest_price_at_or_before_date_else_fifo_cost",
  cost_fallback_used: false,
  cost_fallback_securities: [],
};

describe("portfolio valuation warning", () => {
  it("remains absent when fallback was not used", () => {
    expect(getPortfolioCostFallbackWarning(baseMetadata)).toBeNull();
  });

  it("lists affected tickers once when fallback was used", () => {
    expect(
      getPortfolioCostFallbackWarning({
        ...baseMetadata,
        cost_fallback_used: true,
        cost_fallback_securities: [
          { security_id: 1, ticker: "AAPL", name: "Apple" },
          { security_id: 2, ticker: "ENI.MI", name: "Eni" },
          { security_id: 1, ticker: "AAPL", name: "Apple" },
        ],
      })
    ).toEqual({
      tickers: ["AAPL", "ENI.MI"],
      securitiesLabel: "AAPL, ENI.MI",
    });
  });

  it("keeps a readable warning when details are incomplete", () => {
    expect(
      getPortfolioCostFallbackWarning({ ...baseMetadata, cost_fallback_used: true })
    ).toEqual({
      tickers: [],
      securitiesLabel: "one or more securities",
    });
  });
});
