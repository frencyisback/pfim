import { renderToStaticMarkup } from "react-dom/server";
import { Bar, BarChart, XAxis, YAxis } from "recharts";
import { describe, expect, it } from "vitest";
import { currencyChartLowerBound, currencyYAxisProps } from "./chartScale";

function renderCurrencyChart(values: number[]): string {
  return renderToStaticMarkup(
    <BarChart width={500} height={250} data={values.map((value, index) => ({ value, index }))}>
      <XAxis dataKey="index" />
      <YAxis {...currencyYAxisProps} />
      <Bar dataKey="value" isAnimationActive={false} />
    </BarChart>
  );
}

describe("automatic monetary chart scale", () => {
  it("preserves negative values and otherwise starts at zero", () => {
    expect(currencyChartLowerBound(250)).toBe(0);
    expect(currencyChartLowerBound(-300)).toBe(-300);
  });

  it("renders a readable monetary axis even for small amounts", () => {
    const markup = renderCurrencyChart([25, 50, 100]);
    expect(markup).toContain("recharts-yAxis");
    expect(markup).toContain("100,00");
    expect(markup).not.toContain("10.000,00");
  });

  it("shows negative values and values above the old minimum", () => {
    const markup = renderCurrencyChart([-5000, 20000]);
    const ticks = [...markup.matchAll(/<tspan[^>]*>([-\d.,]+)\s*€<\/tspan>/g)]
      .map((match) => Number(match[1].replace(/\./g, "").replace(",", ".")));
    expect(Math.min(...ticks)).toBeLessThanOrEqual(-5000);
    expect(Math.max(...ticks)).toBeGreaterThanOrEqual(20000);
  });
});
