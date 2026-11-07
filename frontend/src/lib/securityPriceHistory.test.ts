import { afterEach, describe, expect, it, vi } from "vitest";
import type { Price } from "@/api/prices";
import { todayIso } from "./dates";
import {
  buildSecurityPriceHistory,
  formatSecurityPriceDate,
  formatSecurityPriceEur,
  securityPriceSourceLabel,
} from "./securityPriceHistory";

const today = "2026-11-06";
const dayMs = 86_400_000;

function price(overrides: Partial<Price> = {}): Price {
  return {
    id: 1,
    security_id: 7,
    date: "2026-11-01",
    price_close: "100.000000",
    fx_rate: "0.92000000",
    price_close_eur: "92.000000",
    source: "manual",
    origin_trade_id: null,
    ...overrides,
  };
}

afterEach(() => vi.useRealTimers());

describe("recorded EUR security history", () => {
  it("keeps an empty history empty", () => {
    expect(buildSecurityPriceHistory([], 7, today)).toEqual({ points: [], invalidCount: 0 });
  });

  it("uses the saved EUR value even when native price and FX disagree with it", () => {
    const result = buildSecurityPriceHistory([
      price({ price_close: "400", fx_rate: "0.5", price_close_eur: "123.456789" }),
    ], 7, today);
    expect(result.points).toEqual([{
      date: "2026-11-01",
      timestamp: Date.UTC(2026, 10, 1),
      priceEur: 123.456789,
      priceEurExact: "123.456789",
      source: "manual",
    }]);
    expect(result.invalidCount).toBe(0);
  });

  it("retains sparse observations and their real spacing without adding intermediate days", () => {
    const result = buildSecurityPriceHistory([
      price({ date: "2026-10-01", price_close_eur: "10" }),
      price({ id: 2, date: "2026-10-02", price_close_eur: "11" }),
      price({ id: 3, date: "2026-11-01", price_close_eur: "12" }),
    ], 7, today);
    expect(result.points.map(({ date, priceEur }) => [date, priceEur])).toEqual([
      ["2026-10-01", 10], ["2026-10-02", 11], ["2026-11-01", 12],
    ]);
    expect(result.points[1].timestamp - result.points[0].timestamp).toBe(dayMs);
    expect(result.points[2].timestamp - result.points[1].timestamp).toBe(30 * dayMs);
  });

  it("sorts chronologically without changing the response array or its objects", () => {
    const last = Object.freeze(price({ id: 3, date: today }));
    const first = Object.freeze(price({ id: 1, date: "2026-01-01" }));
    const middle = Object.freeze(price({ id: 2, date: "2026-06-01" }));
    const input = Object.freeze([last, first, middle]);
    const result = buildSecurityPriceHistory(input, 7, today);
    expect(result.points.map((point) => point.date)).toEqual([
      "2026-01-01", "2026-06-01", today,
    ]);
    expect(input).toEqual([last, first, middle]);
    expect(result.points[0]).not.toBe(first);
  });

  it("includes today and excludes all future observations, including invalid future prices", () => {
    const result = buildSecurityPriceHistory([
      price({ date: today }),
      price({ id: 2, date: "2026-11-07", price_close_eur: "999" }),
      price({ id: 3, date: "2027-01-01", price_close_eur: "NaN" }),
    ], 7, today);
    expect(result.points.map((point) => point.date)).toEqual([today]);
    expect(result.invalidCount).toBe(0);
  });

  it("does not leak observations from another security into the selection", () => {
    const result = buildSecurityPriceHistory([
      price(),
      price({ security_id: 8, price_close_eur: "999" }),
      price({ security_id: 8, date: "not-a-date", price_close_eur: "NaN" }),
    ], 7, today);
    expect(result.points).toHaveLength(1);
    expect(result.points[0].priceEur).toBe(92);
    expect(result.invalidCount).toBe(0);
  });

  it("keeps a single actual observation without constructing a flat series", () => {
    const result = buildSecurityPriceHistory([price({ date: "2020-01-01" })], 7, today);
    expect(result.points).toHaveLength(1);
    expect(result.points[0].date).toBe("2020-01-01");
  });

  it("accepts leap days and keeps DST transitions as calendar-day intervals", () => {
    const leap = buildSecurityPriceHistory([
      price({ date: "2024-02-28" }), price({ date: "2024-02-29" }),
      price({ date: "2024-03-01" }),
    ], 7, today);
    expect(leap.points).toHaveLength(3);
    expect(leap.points[2].timestamp - leap.points[0].timestamp).toBe(2 * dayMs);
    const dst = buildSecurityPriceHistory([
      price({ date: "2026-03-28" }), price({ date: "2026-03-29" }),
      price({ date: "2026-03-30" }),
    ], 7, today);
    expect(dst.points[2].timestamp - dst.points[0].timestamp).toBe(2 * dayMs);
  });

  it("uses the local cutoff supplied by todayIso close to local midnight", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 10, 6, 0, 1));
    const result = buildSecurityPriceHistory([
      price({ date: "2026-11-06" }), price({ date: "2026-11-07" }),
    ], 7, todayIso());
    expect(result.points.map((point) => point.date)).toEqual(["2026-11-06"]);
  });

  it.each([
    "2026-02-29", "2026-02-30", "2026-13-01", "2026-11-31", "0000-01-01",
    "2026-1-01", "2026-01-01T00:00:00Z", "not-a-date", "",
  ])("excludes and reports an invalid stored calendar date: %s", (date) => {
    expect(buildSecurityPriceHistory([price({ date })], 7, today)).toEqual({
      points: [], invalidCount: 1,
    });
  });

  it.each(["2026-02-29", "", "2026-13-01", "2026-11-06T12:00:00Z"])(
    "rejects an invalid cutoff instead of silently showing future data: %s", (cutoff) => {
      expect(() => buildSecurityPriceHistory([price()], 7, cutoff)).toThrow(RangeError);
    }
  );

  it.each([
    "0", "0.000000", "-1", "NaN", "Infinity", "-Infinity", "", " ",
    "1e2", "1,25", "0.0000001", "1000000000000", "1.1234567", "12oops",
  ])("reports an unusable EUR value without falling back to native or zero: %s", (eur) => {
    expect(buildSecurityPriceHistory([price({ price_close_eur: eur })], 7, today)).toEqual({
      points: [], invalidCount: 1,
    });
  });

  it.each([null, undefined, 92, Number.NaN])(
    "rejects missing or non-string EUR response values: %s", (eur) => {
      const malformed = { ...price(), price_close_eur: eur } as unknown as Price;
      expect(buildSecurityPriceHistory([malformed], 7, today)).toEqual({
        points: [], invalidCount: 1,
      });
    }
  );

  it("keeps valid points when other observations are unusable and reports their count", () => {
    const result = buildSecurityPriceHistory([
      price(), price({ date: "2026-10-01", price_close_eur: "0" }),
      price({ date: "2026-10-02", price_close_eur: "NaN" }),
    ], 7, today);
    expect(result.points).toHaveLength(1);
    expect(result.invalidCount).toBe(2);
  });

  it("preserves micro-prices and the exact decimal at the database upper boundary", () => {
    const result = buildSecurityPriceHistory([
      price({ price_close_eur: "0.000001" }),
      price({ date: "2026-11-02", price_close_eur: "999999999999.999999" }),
    ], 7, today);
    expect(result.points[0].priceEur).toBe(0.000001);
    expect(result.points[1].priceEurExact).toBe("999999999999.999999");
    expect(result.points.every((point) => Number.isFinite(point.priceEur) && point.priceEur > 0)).toBe(true);
  });

  it("keeps the recorded source rather than inferring one from the value", () => {
    const result = buildSecurityPriceHistory([
      price({ source: "csv_import" }), price({ source: "trade" }), price({ source: "legacy" }),
    ], 7, today);
    expect(result.points.map((point) => point.source)).toEqual(["csv_import", "trade", "legacy"]);
  });
});

describe("precise EUR presentation", () => {
  it.each([
    ["92", "92,00\u00a0€"], ["92.000000", "92,00\u00a0€"],
    ["92.120000", "92,12\u00a0€"], ["92.123456", "92,123456\u00a0€"],
    ["0.000001", "0,000001\u00a0€"], ["0.001000", "0,001\u00a0€"],
    ["1234.5", "1.234,50\u00a0€"], ["00012.34", "12,34\u00a0€"],
    ["999999999999.999999", "999.999.999.999,999999\u00a0€"],
    ["0", "0,00\u00a0€"],
  ])("formats %s in euros without losing stored decimal precision", (value, expected) => {
    expect(formatSecurityPriceEur(value)).toBe(expected);
  });

  it.each(["NaN", "Infinity", "-1", "", "1e-6", "1.1234567", "1000000000000"])(
    "marks invalid amounts unavailable instead of displaying them as zero: %s", (value) => {
      expect(formatSecurityPriceEur(value)).toBe("—");
    }
  );

  it("formats calendar dates in UTC consistently with the numeric X axis", () => {
    expect(formatSecurityPriceDate(Date.UTC(2026, 10, 6))).toBe("06/11/2026");
    expect(formatSecurityPriceDate(Date.UTC(2024, 1, 29))).toBe("29/02/2024");
  });

  it.each([Number.NaN, Number.POSITIVE_INFINITY, 8.64e15 + 1])(
    "does not throw on an invalid timestamp: %s", (timestamp) => {
      expect(formatSecurityPriceDate(timestamp)).toBe("—");
    }
  );

  it.each([
    ["manual", "Manual entry"], ["csv_import", "CSV import"],
    ["trade", "Trade"], ["legacy_trade_orphan", "Legacy trade (unlinked)"],
    ["legacy", "Unknown source"], ["", "Unknown source"],
  ])("presents source %s without inventing provenance", (source, expected) => {
    expect(securityPriceSourceLabel(source)).toBe(expected);
  });
});
