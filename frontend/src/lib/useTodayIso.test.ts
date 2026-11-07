import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { subscribeToLocalDate } from "./useTodayIso";

describe("the local price-history cutoff", () => {
  let pageWindow: EventTarget;
  let pageDocument: EventTarget & { visibilityState: string };
  let unsubscribe: () => void;

  beforeEach(() => {
    vi.useFakeTimers();
    // Construct local calendar dates so this boundary test works in any time zone.
    vi.setSystemTime(new Date(2026, 10, 6, 23, 59, 59));
    pageWindow = new EventTarget();
    pageDocument = Object.assign(new EventTarget(), { visibilityState: "visible" });
    vi.stubGlobal("window", pageWindow);
    vi.stubGlobal("document", pageDocument);
  });

  afterEach(() => {
    unsubscribe();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("advances at local midnight while the chart stays open", () => {
    const onDate = vi.fn();
    unsubscribe = subscribeToLocalDate(onDate);
    expect(onDate).toHaveBeenLastCalledWith("2026-11-06");
    vi.advanceTimersByTime(1100);
    expect(onDate).toHaveBeenLastCalledWith("2026-11-07");
  });

  it("updates on focus and when returning to a suspended tab, even if the clock goes back", () => {
    const onDate = vi.fn();
    unsubscribe = subscribeToLocalDate(onDate);
    vi.setSystemTime(new Date(2026, 10, 8, 12));
    pageWindow.dispatchEvent(new Event("focus"));
    expect(onDate).toHaveBeenLastCalledWith("2026-11-08");

    vi.setSystemTime(new Date(2026, 10, 7, 12));
    pageDocument.visibilityState = "hidden";
    pageDocument.dispatchEvent(new Event("visibilitychange"));
    expect(onDate).toHaveBeenLastCalledWith("2026-11-08");
    pageDocument.visibilityState = "visible";
    pageDocument.dispatchEvent(new Event("visibilitychange"));
    expect(onDate).toHaveBeenLastCalledWith("2026-11-07");
  });

  it("stops observing the clock and browser events when the chart is closed", () => {
    const onDate = vi.fn();
    unsubscribe = subscribeToLocalDate(onDate);
    unsubscribe();
    onDate.mockClear();
    vi.advanceTimersByTime(120_000);
    pageWindow.dispatchEvent(new Event("focus"));
    pageDocument.dispatchEvent(new Event("visibilitychange"));
    expect(onDate).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
