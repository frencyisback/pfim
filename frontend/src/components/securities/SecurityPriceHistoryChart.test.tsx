import { cloneElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { SecurityPriceHistoryPoint } from "@/lib/securityPriceHistory";
import SecurityPriceHistoryChart, { SecurityPriceTooltip } from "./SecurityPriceHistoryChart";

// Static rendering has no layout observer. Keep real Recharts rendering and only
// provide the dimensions a measured ResponsiveContainer supplies in a browser.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width: number; height: number }> }) =>
      cloneElement(children, { width: 800, height: 320 }),
  };
});

const today = "2026-11-06";
function point(date: string, value = "92.123456", source = "manual"): SecurityPriceHistoryPoint {
  return { date, timestamp: Date.parse(`${date}T00:00:00Z`), priceEur: Number(value), priceEurExact: value, source };
}

function render(points: SecurityPriceHistoryPoint[], invalidCount = 0) {
  return renderToStaticMarkup(<SecurityPriceHistoryChart points={points} invalidCount={invalidCount} today={today} />);
}

describe("observed price chart", () => {
  it("shows an explicit empty state without inventing a zero chart", () => {
    const html = render([]);
    expect(html).toContain("No recorded prices are available through today.");
    expect(html).not.toContain("recharts-scatter");
    expect(html).not.toContain("recharts-symbols");
  });

  it("distinguishes an unusable history from one with no observations", () => {
    const html = render([], 2);
    expect(html).toContain('role="alert"');
    expect(html).toContain("2 observations were");
    expect(html).toContain("No valid EUR prices are available through today.");
    expect(html).not.toContain("recharts-symbols");
  });

  it("renders one actual point at today's boundary with its exact euro value", () => {
    const html = render([point(today, "0.000001")]);
    expect(html).toContain("Only one recorded price: 06/11/2026");
    expect(html).toContain('aria-label="Recorded EUR prices: 1 observation.');
    expect(html).toContain("0,000001");
    expect(html.match(/class="recharts-symbols"/g)).toHaveLength(1);
    expect(html).not.toContain("NaN");
    expect(html).not.toContain("Infinity");
  });

  it("plots only recorded points on a time axis and does not draw an interpolated line", () => {
    const html = render([
      point("2026-01-01", "10"), point("2026-01-02", "15"), point(today, "20"),
    ]);
    expect(html.match(/class="recharts-symbols"/g)).toHaveLength(3);
    expect(html).toContain("3 recorded prices");
    expect(html).toContain('aria-label="Recorded EUR prices: 3 observations.');
    expect(html).toContain("Recorded prices (EUR)");
    expect(html).not.toContain("recharts-scatter-line");
    expect(html).not.toContain("recharts-line-curve");
    const xCoordinates = [...html.matchAll(/cx="([\d.]+)"/g)].map((match) => Number(match[1]));
    expect(xCoordinates).toHaveLength(3);
    expect(xCoordinates[1] - xCoordinates[0]).toBeLessThan((xCoordinates[2] - xCoordinates[1]) / 100);
  });

  it("continues to show usable data while explaining omitted observations", () => {
    const html = render([point("2026-11-01")], 1);
    expect(html).toContain("1 observation was");
    expect(html.match(/class="recharts-symbols"/g)).toHaveLength(1);
  });

  it("renders large stored values without corrupting exact text or chart coordinates", () => {
    const html = render([point(today, "999999999999.999999")]);
    expect(html).toContain("999.999.999.999,999999");
    expect(html).not.toContain("NaN");
    expect(html).not.toContain("Infinity");
    expect(html.match(/class="recharts-symbols"/g)).toHaveLength(1);
  });
});

describe("recorded price tooltip", () => {
  it("shows recorded date, exact EUR price and source", () => {
    const html = renderToStaticMarkup(<SecurityPriceTooltip active payload={[{ payload: point(today, "123.456789", "csv_import") }]} />);
    expect(html).toContain("06/11/2026");
    expect(html).toContain("123,456789");
    expect(html).toContain("€");
    expect(html).toContain("CSV import");
  });

  it("keeps trade provenance and unknown provenance distinct", () => {
    const trade = renderToStaticMarkup(<SecurityPriceTooltip active payload={[{ payload: point(today, "1", "trade") }]} />);
    const unknown = renderToStaticMarkup(<SecurityPriceTooltip active payload={[{ payload: point(today, "1", "old-source") }]} />);
    expect(trade).toContain("Trade");
    expect(unknown).toContain("Unknown source");
  });

  it("does not display values when inactive or lacking a payload", () => {
    expect(renderToStaticMarkup(<SecurityPriceTooltip />)).toBe("");
    expect(renderToStaticMarkup(<SecurityPriceTooltip active payload={[]} />)).toBe("");
    expect(renderToStaticMarkup(<SecurityPriceTooltip active payload={[{}]} />)).toBe("");
    expect(renderToStaticMarkup(<SecurityPriceTooltip active={false} payload={[{ payload: point(today) }]} />)).toBe("");
  });
});
