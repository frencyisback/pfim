/** todayIso uses the user's local day rather than UTC, avoiding a
 * previous-day default near midnight that could affect monthly reports. */
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  calendarDaysSince,
  formatUtcDateTime,
  isoMonth,
  monthEndIso,
  monthStartIso,
  recentMonthRange,
  todayIso,
} from "./dates";

afterEach(() => {
  vi.useRealTimers();
});

describe("todayIso", () => {
  it("returns the date format used by the backend and date inputs", () => {
    expect(todayIso()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("pads month and day to two digits", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0, 0)); // January 5, local time

    expect(todayIso()).toBe("2026-01-05");
  });

  it("keeps the local date close to midnight", () => {
    vi.useFakeTimers();
    // March 1 at 00:30 local time in the test zone is still February 28 UTC:
    // this is where new Date().toISOString() selects the wrong day.
    vi.setSystemTime(new Date(2026, 2, 1, 0, 30, 0));

    expect(todayIso()).toBe("2026-03-01");
  });
});

describe("monthly periods", () => {
  it("selects the entire current month even at month end", () => {
    expect(recentMonthRange(1, new Date(2024, 1, 29, 0, 30))).toEqual({
      from: "2024-02-01", to: "2024-02-29",
    });
  });

  it("selects three inclusive months across a year boundary without shifting days", () => {
    expect(recentMonthRange(3, new Date(2026, 0, 31, 23, 30))).toEqual({
      from: "2025-11-01", to: "2026-01-31",
    });
    expect(recentMonthRange(3, new Date(2026, 8, 11))).toEqual({
      from: "2026-07-01", to: "2026-09-30",
    });
  });

  it("converts a month into the inclusive bounds expected by the backend", () => {
    expect(monthStartIso("2026-08")).toBe("2026-08-01");
    expect(monthEndIso("2026-08")).toBe("2026-08-31");
  });

  it("handles leap-year February and rejects invalid values", () => {
    expect(monthEndIso("2024-02")).toBe("2024-02-29");
    expect(monthEndIso("2025-02")).toBe("2025-02-28");
    expect(monthStartIso("2026-13")).toBeUndefined();
    expect(monthEndIso("not-a-month")).toBeUndefined();
  });

  it("extracts the month from an ISO bound without a time zone", () => {
    expect(isoMonth("2026-08-31")).toBe("2026-08");
    expect(isoMonth(undefined)).toBe("");
    expect(isoMonth("2026-08")).toBe("");
  });
});

describe("calendarDaysSince", () => {
  it("compares calendar days independently of local time", () => {
    expect(calendarDaysSince("2026-03-22", "2026-03-30")).toBe(8);
    expect(calendarDaysSince("2026-03-30", "2026-03-30")).toBe(0);
  });

  it("handles months, leap years and future dates correctly", () => {
    expect(calendarDaysSince("2024-02-28", "2024-03-01")).toBe(2);
    expect(calendarDaysSince("2026-04-01", "2026-03-30")).toBe(-2);
  });

  it("rejects nonexistent or malformed ISO dates", () => {
    expect(calendarDaysSince("2026-02-30", "2026-03-01")).toBeNull();
    expect(calendarDaysSince("not-a-date", "2026-03-01")).toBeNull();
  });
});

describe("formatUtcDateTime", () => {
  it("converts UTC timestamps to the displayed time zone", () => {
    const formatted = formatUtcDateTime(
      "2026-08-18T09:16:27+00:00",
      "it-IT",
      { timeZone: "Europe/Rome" }
    );

    expect(formatted).toContain("18/08/2026");
    expect(formatted).toContain("11:16:27");
  });

  it("also treats legacy timestamps without a suffix as UTC", () => {
    expect(
      formatUtcDateTime("2026-08-18T09:16:27", "it-IT", {
        timeZone: "Europe/Rome",
      })
    ).toContain("11:16:27");
  });

  it("does not display Invalid Date for malformed values", () => {
    expect(formatUtcDateTime("not-a-date")).toBe("—");
  });
});
