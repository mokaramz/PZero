/**
 * The Investment Desk reads (review 031a) — five GETs, as the old page made them, under the NEW paths:
 *
 * - `GET home` → the old `GET /api/home` body, key for key and in the old order (`priority, best_event, due,
 *   new_signals, latest_signals, omar, progress, watch, weekday, date`; ./model/types), computed in one read-only
 *   snapshot at the Berlin request clock;
 * - `GET deal-flow/inbox` (the old `inbox`), then, once the inbox has loaded, `GET conviction/pipeline` (the old
 *   `pipeline`), `GET today` and `GET sources`: the old staggered loading (the server is kinder to a staggered burst
 *   than to five at once). The keys are the views' own, so the desk shares their caches.
 * - The old `GET review_queue` is DEFERRED until the analysis port (decision d): no request, no rows.
 * - `POST conviction/weekly` from the weekly drawer (Conviction's `WeeklyDrawer`); it writes nothing.
 *
 * Nothing on the desk writes. The NEW writers that change it list `home` among their invalidations: Conviction's
 * writes, the people writes (`due`), the Events writes (the best event), the Founder Calls writes, the Active Evaluator
 * end and why-now trigger (the pipeline) and a Deal Flow decision (the new signals).
 */
import { PIPELINE } from "@/features/conviction/api";
import { INBOX } from "@/features/deal-flow/hooks/useDealFlowData";
import { SOURCES } from "@/features/sources/api";
import { TODAY } from "@/features/today/api";
import { useApi } from "@/lib/hooks";
import type { HomePayload, Inbox, Pipeline, ReviewRow, Sources, TodayView } from "./model/types";

export const HOME = "home";

/** The deferred Agent Review Queue (decision d): the desk reads no review rows until the analysis port. */
export const REVIEW_ROWS: ReviewRow[] = [];

export function useDeskReads() {
  const home = useApi<HomePayload>(HOME);
  const inbox = useApi<Inbox>(INBOX);
  const after = { enabled: !!inbox.data };
  const pipe = useApi<Pipeline>(PIPELINE, undefined, after);
  const today = useApi<TodayView>(TODAY, undefined, { ...after, staleTime: 30_000 });
  const sources = useApi<Sources>(SOURCES, undefined, after);
  return { home, inbox, pipe, today, sources };
}
