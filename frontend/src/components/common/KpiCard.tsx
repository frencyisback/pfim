import type { ReactNode } from "react";

/** KPI card with a calculation formula tooltip (specification §7.1.2).
 * Formula explanations make calculation choices visible, such as why
 * account balances include investment accounts but available cash does not.
 * Tooltips appear on hover and keyboard focus; cards with formulas are
 * reachable with Tab so the information is keyboard-accessible. */
export interface KpiCardProps {
  label: string;
  value: string;
  /** Green if true, red if false, neutral if omitted. */
  positive?: boolean;
  /** How the number is calculated; omitted for descriptive values. */
  formula?: ReactNode;
}

export default function KpiCard({ label, value, positive, formula }: KpiCardProps) {
  return (
    <div
      className={`group relative rounded-lg border border-gray-200 bg-white p-3 ${
        formula ? "cursor-help focus:outline-none focus:ring-2 focus:ring-gray-300" : ""
      }`}
      tabIndex={formula ? 0 : undefined}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs text-gray-500">{label}</div>
        {formula && (
          <span
            aria-hidden="true"
            className="mt-0.5 shrink-0 rounded-full border border-gray-300 px-1 text-[10px] leading-tight text-gray-400"
          >
            ?
          </span>
        )}
      </div>
      <div
        className={`mt-1 text-lg font-semibold ${
          positive === undefined ? "" : positive ? "text-green-600" : "text-red-600"
        }`}
      >
        {value}
      </div>

      {formula && (
        <div
          role="tooltip"
          className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-72 rounded-lg border border-gray-700 bg-gray-900 p-3 text-xs leading-relaxed text-gray-100 shadow-xl group-hover:block group-focus:block"
        >
          <div className="mb-1 font-medium text-white">How it is calculated</div>
          {formula}
        </div>
      )}
    </div>
  );
}

/** Highlight the calculation within a tooltip, separating the
 * formula from its explanation. */
export function Formula({ children }: { children: ReactNode }) {
  return (
    <code className="mb-1.5 block rounded bg-gray-800 px-2 py-1 font-mono text-[11px] text-amber-200">
      {children}
    </code>
  );
}
