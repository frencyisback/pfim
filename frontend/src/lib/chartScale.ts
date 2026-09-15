import type { ComponentProps } from "react";
import type { YAxis } from "recharts";
import { formatEur } from "./formatters";

/** Automatic scale with zero as reference and all negative values visible. */
export function currencyChartLowerBound(dataMin: number): number {
  return Math.min(0, dataMin);
}

// YAxis must remain a direct chart child for Recharts to recognise it.
export const currencyYAxisProps = {
  domain: [currencyChartLowerBound, "auto"],
  tickFormatter: (value: number) => formatEur(value),
  width: 80,
} satisfies ComponentProps<typeof YAxis>;
