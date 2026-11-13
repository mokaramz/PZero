/**
 * The Today endpoint (review 030a) — the ONE place its path lives. Today is a read model with no writes: every button
 * on the page is a link (decision j).
 *
 * - `GET today` → the old `GET /api/today` body, key for key and in the old order (`date, actions, more, considered,
 *   exceptions, machine_working, triage, rules`), computed in one read-only snapshot at the Berlin request clock; then
 *   `snapshot` (./model/types). Without the dropped SCOUT00_CYCLE / NATIVE_INTEL sections and their `considered`
 *   keys (decision c), and never with the `jobs` exceptions row (decision d).
 * - The company facts and the four tiles come from Conviction's pipeline read (`conviction/pipeline`, its own hook).
 *
 * The NEW writers that change Today re-read it: Events save / status, Conviction save / status / `imq_trigger`, the
 * Founder Calls writes, every Active Evaluator write (the sessions feed the hold), the people writes (the IMQ) and a
 * Deal Flow decision (the triage card and the live candidates) list or invalidate the `today` key.
 */
import { useApi } from "@/lib/hooks";
import type { TodayView } from "./model/types";

export const TODAY = "today";

/** The day's actions, read again after 30 s at most (as before). */
export const useToday = () => useApi<TodayView>(TODAY, undefined, { staleTime: 30_000 });

export { usePipeline } from "@/features/conviction/api";
