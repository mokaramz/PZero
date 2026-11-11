/**
 * Motion helpers (docs/design-system.md → Motion). Motion makes invisible system state understandable — a real signal
 * arriving, a decision changing state — and then stops.
 *
 * Both hooks compare this render with the PREVIOUS committed render, which is what a ref read during render gives:
 * the answer is true for exactly one render and must not cause another one (state would). Hence the lint exception.
 */
/* oxlint-disable react/refs */
import { useEffect, useRef } from "react";

/** Keys that appeared AFTER the first render (something genuinely new arrived while the page is open). The first view
 *  animates nothing — no noise on load; a later arrival enters once (`pz-arrive`). */
export function useNewKeys(keys: string[]): Set<string> {
  const seen = useRef<Set<string> | null>(null);
  const fresh = new Set(seen.current ? keys.filter((k) => !seen.current!.has(k)) : []);
  useEffect(() => {
    seen.current = new Set([...(seen.current ?? []), ...keys]);
  });
  return fresh;
}

/** True on the render where `value` CHANGED (never on first view): a decision visibly changing a row's state. */
export function useChanged(value: string): boolean {
  const prev = useRef<string | null>(null);
  const changed = prev.current !== null && prev.current !== value;
  useEffect(() => {
    prev.current = value;
  });
  return changed;
}
