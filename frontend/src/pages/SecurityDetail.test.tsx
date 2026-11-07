import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePriceHistory, type Price } from "@/api/prices";
import { useSecurities } from "@/api/securities";
import type { Security } from "@/api/types";
import SecurityDetail, { SelectedSecurityDetail } from "./SecurityDetail";
vi.mock("@/api/prices", () => ({ usePriceHistory: vi.fn() }));
vi.mock("@/api/securities", () => ({ useSecurities: vi.fn() }));
vi.mock("@/lib/useTodayIso", () => ({ useTodayIso: () => "2026-11-06" }));

const security: Security = {
  id: 7, ticker: "TEST", name: "First security", type: "stock", market: null,
  currency: "USD", isin: null, sector: null, industry: null, country: null, is_active: true,
};
const otherSecurity: Security = { ...security, id: 8, ticker: "SECOND", name: "Second security", is_active: false };
const price: Price = {
  id: 1, security_id: 7, date: "2026-11-01", price_close: "1000", fx_rate: "0.5",
  price_close_eur: "123.456789", source: "csv_import", origin_trade_id: null,
};

function registry(overrides: Partial<ReturnType<typeof useSecurities>> = {}) {
  vi.mocked(useSecurities).mockReturnValue({
    data: [security, otherSecurity], isLoading: false, isFetching: false, error: null, ...overrides,
  } as ReturnType<typeof useSecurities>);
}
function prices(overrides: Partial<ReturnType<typeof usePriceHistory>> = {}) {
  vi.mocked(usePriceHistory).mockReturnValue({
    data: [price], isLoading: false, isFetching: false, error: null, ...overrides,
  } as ReturnType<typeof usePriceHistory>);
}

beforeEach(() => {
  vi.clearAllMocks();
  registry();
  prices();
});

describe("security detail page rendering", () => {
  it("starts without a selection or a history request and includes inactive catalogue entries", () => {
    const html = renderToStaticMarkup(<SecurityDetail />);
    expect(html).toContain("Choose a security");
    expect(html).toContain("SECOND — Second security (inactive)");
    expect(html).not.toContain("Security record");
    expect(html).not.toContain("Recorded prices (EUR)");
    expect(usePriceHistory).not.toHaveBeenCalled();
  });

  it("distinguishes an empty catalogue from loading and failure", () => {
    registry({ data: [] });
    const html = renderToStaticMarkup(<SecurityDetail />);
    expect(html).toContain("No securities registered.");
    expect(html).not.toContain("<select");
    expect(usePriceHistory).not.toHaveBeenCalled();
  });

  it("shows the selected record and only its stored EUR observations through today", () => {
    prices({ data: [price, { ...price, id: 2, date: "2026-11-07", price_close_eur: "999" }] });
    const html = renderToStaticMarkup(<SelectedSecurityDetail security={security} />);
    expect(html).toContain("Security record");
    expect(html).toContain("Only one recorded price: 01/11/2026");
    expect(html).toContain("123,456789");
    expect(html).not.toContain("999,00");
    expect(html).not.toContain("1.000,00");
    expect(html).not.toContain("500,00");
    expect(usePriceHistory).toHaveBeenCalledWith(7);
  });

  it("keeps a selected inactive security readable", () => {
    prices({ data: [] });
    const html = renderToStaticMarkup(<SelectedSecurityDetail security={otherSecurity} />);
    expect(html).toContain("Security record");
    expect(html).toContain("Inactive");
    expect(html).toContain("No recorded prices are available through today.");
    expect(usePriceHistory).toHaveBeenCalledWith(8);
  });

  it.each(["isLoading", "isFetching"] as const)(
    "disables selection while the catalogue is %s", (flag) => {
      registry({ [flag]: true });
      const html = renderToStaticMarkup(<SecurityDetail />);
      expect(html).toContain("Loading");
      expect(html).toContain("disabled");
      expect(html).not.toContain("Security record");
      expect(html).not.toContain("Recorded prices (EUR)");
      expect(usePriceHistory).not.toHaveBeenCalled();
    }
  );

  it("shows registry failure without exposing cached detail data", () => {
    registry({ error: new Error("Registry unavailable") });
    const html = renderToStaticMarkup(<SecurityDetail />);
    expect(html).toContain("Registry unavailable");
    expect(html).not.toContain("Security record");
    expect(usePriceHistory).not.toHaveBeenCalled();
  });

  it.each(["isLoading", "isFetching"] as const)(
    "retains the record but hides cached price data while history is %s", (flag) => {
      prices({ [flag]: true });
      const html = renderToStaticMarkup(<SelectedSecurityDetail security={security} />);
      expect(html).toContain("Security record");
      expect(html).toContain("Loading");
      expect(html).not.toContain("Recorded prices (EUR)");
      expect(html).not.toContain("123,456789");
    }
  );

  it("reports a history failure instead of describing it as an empty history", () => {
    prices({ error: new Error("History unavailable") });
    const html = renderToStaticMarkup(<SelectedSecurityDetail security={security} />);
    expect(html).toContain("Price history error");
    expect(html).toContain("History unavailable");
    expect(html).not.toContain("No recorded prices");
    expect(html).not.toContain("123,456789");
  });

  it("cannot display another title's prices after the selection changes", () => {
    // Defensive check even if a caller accidentally supplied the previous title's data.
    prices({ data: [price] });
    const html = renderToStaticMarkup(<SelectedSecurityDetail security={otherSecurity} />);
    expect(html).toContain("Second security");
    expect(html).not.toContain("123,456789");
    expect(html).toContain("No recorded prices are available through today.");
    expect(usePriceHistory).toHaveBeenCalledWith(8);
  });

  it("reports invalid saved EUR values without creating a replacement price", () => {
    prices({ data: [{ ...price, price_close_eur: "0" }] });
    const html = renderToStaticMarkup(<SelectedSecurityDetail security={security} />);
    expect(html).toContain("1 observation was");
    expect(html).toContain("No valid EUR prices are available through today.");
    expect(html).not.toContain("1.000,00");
    expect(html).not.toContain("500,00");
  });
});
