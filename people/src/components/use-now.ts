"use client";
import { useCallback, useSyncExternalStore } from "react";

/** Current time, ticking every `ms`. Null during server render so markup matches. */
export function useNow(ms = 1000): number | null {
  const subscribe = useCallback((cb: () => void) => { const t = setInterval(cb, ms); return () => clearInterval(t); }, [ms]);
  return useSyncExternalStore(subscribe, () => Math.floor(Date.now() / ms) * ms, () => null);
}
