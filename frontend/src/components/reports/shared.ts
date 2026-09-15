/** Values shared by Report tabs. Kept in a module without JSX because
 * mixing constants and components causes Vite hot reload to reload the
 * whole page instead of the modified component alone. */
import { formatPercent } from "@/lib/formatters";

/** Formatted percentage, or a dash when no value is available. */
export function pctOrDash(value: string | null): string {
  return value === null ? "—" : formatPercent(Number(value));
}

export const CATEGORY_COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#0ea5e9", "#8b5cf6", "#ec4899", "#64748b", "#14b8a6", "#a855f7"];

/** Pie charts use isAnimationActive={false}: React.StrictMode double
 * mounting interrupts Recharts 2.x entry animations, leaving zero-angle
 * sectors and an empty-looking chart. Bar charts are unaffected. */
