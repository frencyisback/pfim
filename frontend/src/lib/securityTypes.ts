/** Security types: shared values and display labels for forms, tables
 * and charts, keeping readable labels consistent across the interface. */
export type SecurityType =
  | "stock"
  | "bond"
  | "etf_equity"
  | "etf_bond"
  | "fund"
  | "commodity"
  | "etf";

/** Types available during creation, in display order. */
export const SECURITY_TYPE_OPTIONS: { value: SecurityType; label: string }[] = [
  { value: "stock", label: "Stock" },
  { value: "bond", label: "Bond" },
  { value: "etf_equity", label: "Equity ETF" },
  { value: "etf_bond", label: "Bond ETF" },
  { value: "fund", label: "Fund" },
  { value: "commodity", label: "Commodities" },
];

/** The legacy etf type is labelled for existing records even though
 * new entries use the equity/bond ETF types. */
const LEGACY_LABELS: Record<string, string> = {
  etf: "ETF (unspecified)",
};

const LABELS: Record<string, string> = {
  ...Object.fromEntries(SECURITY_TYPE_OPTIONS.map((o) => [o.value, o.label])),
  ...LEGACY_LABELS,
};

/** Readable label, falling back to the raw value when unknown. */
export function securityTypeLabel(type: string): string {
  return LABELS[type] ?? type;
}
