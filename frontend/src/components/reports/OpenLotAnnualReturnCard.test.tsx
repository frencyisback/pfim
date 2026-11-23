import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { OpenLotAnnualReturnReason } from "@/api/performance";
import OpenLotAnnualReturnCard from "./OpenLotAnnualReturnCard";

function render(rate: string | null, reason: OpenLotAnnualReturnReason | null, tickers: string[] = []) {
  const html = renderToStaticMarkup(<OpenLotAnnualReturnCard performance={{
    total_return_annualized: rate,
    total_return_annualized_unavailable_reason: reason,
    portfolio_valuation: {
      price_policy: "latest_price_at_or_before_date_else_fifo_cost",
      cost_fallback_used: reason === "missing_quote",
      cost_fallback_securities: tickers.map((ticker, index) => ({ security_id: index + 1, ticker, name: ticker })),
    },
  }} />);
  const [card, tooltip] = html.split('role="tooltip"');
  return { card, tooltip };
}

describe("annualised return on open FIFO lots", () => {
  it.each([
    ["no_open_cost", "no open holdings with a positive acquisition cost"],
    ["no_elapsed_days", "All remaining lots were bought today"],
    ["missing_quote", "market quote is missing for at least one open holding"],
    ["undefined_rate", "do not yield a representable annual rate"],
  ] as const)("shows %s beside the missing value even when the tooltip is closed", (reason, message) => {
    const { card } = render(null, reason);
    expect(card).toContain("—");
    expect(card).toContain(message);
    expect(card).not.toContain("0,00%");
  });

  it("names the open holdings missing a market quote", () => {
    expect(render(null, "missing_quote", ["ETF1", "ABC"]).card).toContain("ETF1, ABC");
  });

  it.each([["0", "0,00%"], ["0.10", "10,00%"]])("displays a calculated rate of %s", (rate, value) => {
    const { card, tooltip } = render(rate, null);
    expect(card).toContain(value);
    expect(card).not.toContain("—");
    expect(card).not.toContain("unavailable");
    expect(tooltip).toContain("remaining cost by purchase date");
    expect(tooltip).toContain("attributed distributions");
    expect(tooltip).toContain("without reinvestment");
  });
});
