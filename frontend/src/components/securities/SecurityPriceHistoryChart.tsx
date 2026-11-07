import {
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  formatSecurityPriceDate,
  formatSecurityPriceEur,
  securityPriceSourceLabel,
  type SecurityPriceHistoryPoint,
} from "@/lib/securityPriceHistory";

const DAY_MS = 86_400_000;
const axisCurrency = new Intl.NumberFormat("it-IT", {
  style: "currency",
  currency: "EUR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
});
const tinyAxisCurrency = new Intl.NumberFormat("it-IT", {
  style: "currency",
  currency: "EUR",
  notation: "scientific",
  maximumFractionDigits: 2,
});

function formatAxisPrice(value: number): string {
  // Axis ticks can fall between micro-price observations. Do not label a positive tick as zero.
  return value !== 0 && Math.abs(value) < 0.000001
    ? tinyAxisCurrency.format(value)
    : axisCurrency.format(value);
}

export function SecurityPriceTooltip({ active, payload }: {
  active?: boolean;
  payload?: readonly { payload?: SecurityPriceHistoryPoint }[];
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-xs shadow-sm">
      <p className="font-medium">{formatSecurityPriceDate(point.timestamp)}</p>
      <p className="mt-1">Price: <strong>{formatSecurityPriceEur(point.priceEurExact)}</strong></p>
      <p className="mt-1 text-gray-500">Source: {securityPriceSourceLabel(point.source)}</p>
    </div>
  );
}

export default function SecurityPriceHistoryChart({ points, invalidCount = 0, today }: {
  points: SecurityPriceHistoryPoint[];
  invalidCount?: number;
  today: string;
}) {
  const first = points[0];
  const last = points[points.length - 1];
  const cutoff = Date.parse(`${today}T00:00:00.000Z`);
  const largestPrice = points.reduce((maximum, point) => Math.max(maximum, point.priceEur), 0);
  const axisWidth = Math.max(85, Math.ceil(formatAxisPrice(largestPrice).length * 6.5) + 16);
  // Expand a single observation's axis only; never add an observation or extend past today.
  const domain: [number, number] | undefined = first && last
    ? first.timestamp === last.timestamp
      ? [first.timestamp - DAY_MS, Math.min(cutoff, first.timestamp + DAY_MS)]
      : [first.timestamp, last.timestamp]
    : undefined;

  return (
    <section aria-labelledby="security-price-history-title" className="rounded-lg border border-gray-200 bg-white p-4">
      <h3 id="security-price-history-title" className="font-medium">Recorded prices (EUR)</h3>
      <p className="mt-1 text-xs text-gray-500">
        Each dot is a recorded EUR price through {formatSecurityPriceDate(cutoff)}, using the exchange
        rate saved on entry. Straight lines connect consecutive observations. Only dots have a quoted price.
      </p>
      {invalidCount > 0 && (
        <p role="alert" className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {invalidCount} {invalidCount === 1 ? "observation was" : "observations were"} omitted because
          the saved date or EUR price is invalid.
        </p>
      )}
      {first && last ? (
        <>
          <p className="mt-3 text-sm text-gray-600">
            {points.length === 1
              ? `Only one recorded price: ${formatSecurityPriceDate(first.timestamp)} · ${formatSecurityPriceEur(first.priceEurExact)}.`
              : `${points.length} recorded prices · ${formatSecurityPriceDate(first.timestamp)} – ${formatSecurityPriceDate(last.timestamp)}.`}
          </p>
          <div
            className="mt-3 min-w-0"
            role="img"
            aria-label={`Recorded EUR prices: ${points.length} ${points.length === 1 ? "observation" : "observations"}. Latest observation ${formatSecurityPriceDate(last.timestamp)}: ${formatSecurityPriceEur(last.priceEurExact)}.`}
          >
            <ResponsiveContainer width="100%" height={320}>
              <ScatterChart margin={{ top: 12, right: 24, bottom: 16, left: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="timestamp"
                  type="number"
                  scale="time"
                  domain={domain}
                  tickFormatter={formatSecurityPriceDate}
                  tick={{ fontSize: 11 }}
                  minTickGap={35}
                  name="Date"
                />
                <YAxis
                  dataKey="priceEur"
                  type="number"
                  domain={[0, "auto"]}
                  tickFormatter={formatAxisPrice}
                  tick={{ fontSize: 11 }}
                  width={axisWidth}
                  name="Price (EUR)"
                />
                <Tooltip content={<SecurityPriceTooltip />} cursor={{ strokeDasharray: "3 3" }} />
                <Scatter
                  name="Recorded EUR price"
                  data={points}
                  fill="#2563eb"
                  line={points.length > 1}
                  lineType="joint"
                  lineJointType="linear"
                  isAnimationActive={false}
                />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        </>
      ) : (
        <p role="status" className="py-12 text-center text-sm text-gray-500">
          {invalidCount > 0
            ? "No valid EUR prices are available through today."
            : "No recorded prices are available through today."}
        </p>
      )}
    </section>
  );
}
