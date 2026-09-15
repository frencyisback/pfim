/** Frontend dates. Both the backend and date inputs use YYYY-MM-DD,
 * so the main required conversion is finding today's local date. */

/** Today's ISO date using the user's local clock. UTC conversion can
 * return the previous date near midnight, creating an incorrect default
 * that may put transactions in the wrong income statement month. */
export function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/** Calendar days since an ISO date. Validate components before converting
 * both dates to UTC day numbers, avoiding local-time and DST differences
 * that can understate a quote's age near midnight. */
export function calendarDaysSince(value: string, today = todayIso()): number | null {
  const toUtcDay = (iso: string): number | null => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const timestamp = Date.UTC(year, month - 1, day);
    const parsed = new Date(timestamp);
    if (
      parsed.getUTCFullYear() !== year ||
      parsed.getUTCMonth() !== month - 1 ||
      parsed.getUTCDate() !== day
    ) {
      return null;
    }
    return Math.floor(timestamp / 86_400_000);
  };

  const valueDay = toUtcDay(value);
  const todayDay = toUtcDay(today);
  return valueDay === null || todayDay === null ? null : todayDay - valueDay;
}

/** Convert a native month input to its first ISO day without Date,
 * preventing time zones or daylight saving from shifting the period. */
export function monthStartIso(month: string): string | undefined {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (!match) return undefined;
  const monthNumber = Number(match[2]);
  if (monthNumber < 1 || monthNumber > 12) return undefined;
  return `${match[1]}-${match[2]}-01`;
}

/** Last ISO day of a month, including leap years. */
export function monthEndIso(month: string): string | undefined {
  const start = monthStartIso(month);
  if (!start) return undefined;
  const [year, monthNumber] = month.split("-").map(Number);
  const lastDay = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  return `${month}-${String(lastDay).padStart(2, "0")}`;
}

/** Convert an ISO date to the month input value. */
export function isoMonth(value: string | undefined): string {
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value.slice(0, 7) : "";
}

/** Inclusive calendar months ending in the current local month. */
export function recentMonthRange(months: 1 | 3, now = new Date()): { from: string; to: string } {
  const firstMonth = new Date(now.getFullYear(), now.getMonth() - months + 1, 1);
  const fromMonth = `${firstMonth.getFullYear()}-${String(firstMonth.getMonth() + 1).padStart(2, "0")}`;
  const toMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  return { from: monthStartIso(fromMonth)!, to: monthEndIso(toMonth)! };
}

/** Convert backend UTC timestamps to local time. Legacy ISO responses
 * without a suffix are normalised to UTC so JavaScript does not interpret
 * them as local time and display an incorrect timestamp. */
export function formatUtcDateTime(
  value: string,
  locale = "it-IT",
  options?: Intl.DateTimeFormatOptions
): string {
  const hasTimeZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value);
  const parsed = new Date(hasTimeZone ? value : `${value}Z`);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString(locale, options);
}
