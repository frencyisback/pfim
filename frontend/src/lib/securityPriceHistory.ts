import type { Price } from "@/api/prices";

export interface SecurityPriceHistoryPoint {
  date: string;
  /** UTC midnight represents a calendar date, not a local-time observation. */
  timestamp: number;
  /** Floating-point coordinates are only for plotting; keep the stored decimal for text. */
  priceEur: number;
  priceEurExact: string;
  source: string;
}

function isoDateTimestamp(value: string): number | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000-")) {
    return null;
  }
  const timestamp = Date.parse(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) {
    return null;
  }
  return timestamp;
}

/** Match the database's NUMERIC(18, 6) decimal representation without rounding it. */
function priceDecimalParts(value: string): { integer: string; fraction: string } | null {
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,6})?$/.test(value)) return null;
  const [rawInteger, fraction = ""] = value.split(".");
  const integer = rawInteger.replace(/^0+(?=\d)/, "");
  if (integer.length > 12) return null;
  return { integer, fraction };
}

/** Read the saved EUR observation only. No FX lookup, native-price fallback, resampling,
 * gap filling or price interpolation belongs in this view. The caller supplies today's
 * local ISO date so UTC conversion cannot move the cutoff near midnight. */
export function buildSecurityPriceHistory(
  prices: readonly Price[],
  securityId: number,
  today: string
): { points: SecurityPriceHistoryPoint[]; invalidCount: number } {
  const cutoff = isoDateTimestamp(today);
  if (cutoff === null) throw new RangeError("today must be a valid YYYY-MM-DD date");

  const points: SecurityPriceHistoryPoint[] = [];
  let invalidCount = 0;
  for (const price of prices) {
    if (price.security_id !== securityId) continue;
    const timestamp = isoDateTimestamp(price.date);
    if (timestamp === null) {
      invalidCount += 1;
      continue;
    }
    if (timestamp > cutoff) continue;
    const parts = priceDecimalParts(price.price_close_eur);
    if (parts === null || !/[1-9]/.test(parts.integer + parts.fraction)) {
      invalidCount += 1;
      continue;
    }
    points.push({
      date: price.date,
      timestamp,
      priceEur: Number(price.price_close_eur),
      priceEurExact: price.price_close_eur,
      source: price.source,
    });
  }
  points.sort((left, right) => left.timestamp - right.timestamp);
  return { points, invalidCount };
}

/** Preserve all stored significant digits (up to six), including micro-prices and
 * large values that Number would round. Zero is supported for chart-axis labels. */
export function formatSecurityPriceEur(value: string): string {
  const parts = priceDecimalParts(value);
  if (parts === null) return "—";
  const integer = parts.integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const fraction = parts.fraction.replace(/0+$/, "").padEnd(2, "0");
  return `${integer},${fraction}\u00a0€`;
}

export function formatSecurityPriceDate(timestamp: number): string {
  if (!Number.isFinite(timestamp) || Number.isNaN(new Date(timestamp).getTime())) return "—";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  }).format(timestamp);
}

export function securityPriceSourceLabel(source: string): string {
  switch (source) {
    case "manual": return "Manual entry";
    case "csv_import": return "CSV import";
    case "trade": return "Trade";
    case "legacy_trade_orphan": return "Legacy trade (unlinked)";
    default: return "Unknown source";
  }
}
