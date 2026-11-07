import { useEffect, useState } from "react";
import { todayIso } from "./dates";

/** Keep a local calendar cutoff current across midnight, suspended tabs and clock changes. */
export function subscribeToLocalDate(onDate: (date: string) => void): () => void {
  let timer: ReturnType<typeof setTimeout>;
  const refresh = () => {
    onDate(todayIso());
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    // The minute limit also notices a manual clock/time-zone change while the tab stays open.
    const delay = Math.max(1, Math.min(60_000, midnight.getTime() - now.getTime() + 50));
    clearTimeout(timer);
    timer = setTimeout(refresh, delay);
  };
  const onVisibilityChange = () => {
    if (document.visibilityState === "visible") refresh();
  };
  refresh();
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", onVisibilityChange);
  return () => {
    clearTimeout(timer);
    window.removeEventListener("focus", refresh);
    document.removeEventListener("visibilitychange", onVisibilityChange);
  };
}

export function useTodayIso(): string {
  const [today, setToday] = useState(todayIso);
  useEffect(() => subscribeToLocalDate(setToday), []);
  return today;
}
