import { useCallback, useSyncExternalStore } from "react";

/** Without `matchMedia` (tests, very old browsers) no query matches: the narrow layout is the safe default. */
const mediaList = (query: string): MediaQueryList | null =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia(query) : null;

/**
 * True while the CSS media query matches (e.g. `"(min-width: 1240px)"`), re-rendering when it changes. Moved here from
 * the old Network view so every page can share one layout switch.
 */
export function useMedia(query: string): boolean {
  const subscribe = useCallback(
    (notify: () => void) => {
      const mq = mediaList(query);
      if (!mq) return () => {};
      mq.addEventListener("change", notify);
      return () => mq.removeEventListener("change", notify);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => mediaList(query)?.matches ?? false,
    () => false,
  );
}
