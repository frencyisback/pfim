/** Amount and percentage formatters (docs/multi-currency.md). Totals
 * are always euros and use formatEur. Native amounts use formatMoney
 * with their declared currency symbol to avoid misrepresenting values. */
import { EUR } from "./currency";

export function formatEur(amount: number): string {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(amount);
}

/** Amount in its declared currency. */
export function formatMoney(amount: number, currency: string): string {
  const code = (currency || EUR).trim().toUpperCase();
  try {
    return new Intl.NumberFormat("it-IT", { style: "currency", currency: code }).format(amount);
  } catch {
    // For an unrecognised currency, display its code rather than throwing
    // an exception that would hide the entire table.
    return `${new Intl.NumberFormat("it-IT", { minimumFractionDigits: 2 }).format(amount)} ${code}`;
  }
}

/** Native amount with euro value alongside it, e.g. $ 210,00 (193,20 €).
 * Euro amounts are displayed once to avoid unnecessary duplication. */
export function formatMoneyWithEur(
  amount: number,
  currency: string,
  amountEur: number | null | undefined
): string {
  const code = (currency || EUR).trim().toUpperCase();
  if (code === EUR || amountEur === null || amountEur === undefined) {
    return formatMoney(amount, code);
  }
  return `${formatMoney(amount, code)} (${formatEur(amountEur)})`;
}

/** Format a fraction: 0.1667 becomes 16,67%. Backend returns use this
 * form. Already-percentage indicators such as yield on cost, cost ratios
 * and tax rates use formatPercentageValue instead. */
export function formatPercent(value: number): string {
  return new Intl.NumberFormat("it-IT", { style: "percent", minimumFractionDigits: 2 }).format(value);
}

/** Cost drag in percentage points. Gross TWR minus net TWR is positive
 * when costs reduce returns, displayed as a reduction. Derive the sign
 * from the data: net TWR can exceed gross TWR when sale costs reduce
 * withdrawn capital, so a fixed minus sign could produce a double sign. */
export function formatReturnDrag(gapInPoints: number): string {
  const formatted = new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(gapInPoints));
  if (gapInPoints === 0) return `0,00 p.p.`;
  return `${gapInPoints > 0 ? "−" : "+"}${formatted} p.p.`;
}
