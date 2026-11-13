/**
 * The System health reads (review 032a) — the ONE place their paths live. Two GETs, under the old paths:
 *
 * - `GET system_health` → the old body key for key: the verdict, status, issues, sources, coverage, jobs, spend,
 *   providers and diagnostics (./model/types), in one read-only snapshot at the Berlin request clock;
 * - `GET system_health_overview` → the 30-day job history, the model calls and spend by day, and the pipeline
 *   counts; `backups`, `integrity` and `releases` arrive as their deferred reason (decision d).
 *
 * The old `backups`, `integrity`, `governance` and `source_network` reads (the Hardening and New sources panels) are
 * 032b: the page makes NO request for them and shows their reason instead. Nothing on this page writes: every action
 * control is deferred (decision h), and Refresh re-reads these two GETs.
 */
import { useApi } from "@/lib/hooks";
import type { Health, Overview } from "./model/types";

export const SYSTEM_HEALTH = "system_health";
export const SYSTEM_HEALTH_OVERVIEW = "system_health_overview";

export function useHealthReads() {
  const health = useApi<Health>(SYSTEM_HEALTH, undefined, { staleTime: 15_000 });
  const overview = useApi<Overview>(SYSTEM_HEALTH_OVERVIEW, undefined, { staleTime: 15_000 });
  return { health, overview };
}
