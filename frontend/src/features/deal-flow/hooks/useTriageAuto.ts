import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/Toast";
import { isMissingEndpoint } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import {
  AUTO_POLL_MS,
  autoTriageText,
  finishedRun,
  RETRY_LABEL,
  retryToast,
  runKey,
  TRIAGE_AUTO,
  TRIAGE_RETRY,
  WATCH_MS,
  type AutoStatus,
  type RetryAnswer,
} from "../model/triageAuto";
import { TRIAGE } from "./useDealFlowData";

/** What Retry now makes stale: the status itself (the old `triage_auto`; every action reads Background activity again). */
export const RETRY_INVALIDATES = [TRIAGE_AUTO] as const;
/** What a newly finished run makes stale: the triage view (its proposals and pending map) and Today — the old `triage`
 *  and `today` in the new keys. */
export const AUTO_FINISHED_INVALIDATES = [TRIAGE, "today"] as const;

/**
 * The 60 s watch after a scan (the old `triageWatch`): `start` sets it, and it ends by itself `WATCH_MS` later; a second
 * start restarts the clock. Machine triage starts once the scan has committed, so the page polls for it meanwhile.
 */
export function useTriageWatch() {
  const [watching, setWatching] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const start = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setWatching(true);
    timer.current = setTimeout(() => {
      timer.current = null;
      setWatching(false);
    }, WATCH_MS);
  }, []);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return { watching, start };
}

/**
 * The post-scan machine-triage status (the old `AutoTriageStatus` logic). `triage_auto` is polled every 2 s while a run
 * is going or while `watch` is on; a server without the endpoint (404) is never polled. A finished run the page has not
 * reflected yet reads the triage and Today again and is announced once — except the run already finished when the page
 * loaded (nothing new), unless the page is watching. Retry now posts `triage_retry` and shows the old started toast or
 * the server's reason.
 */
export function useTriageAuto(watch: boolean) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useApi<AutoStatus>(TRIAGE_AUTO, undefined, {
    staleTime: 0,
    retry: (n, e) => !isMissingEndpoint(e) && n < 1,
    refetchInterval: (s) => (isMissingEndpoint(s.state.error) ? false : s.state.data?.running || watch ? AUTO_POLL_MS : false),
  });
  const retry = useAction<object, RetryAnswer>(TRIAGE_RETRY, { invalidates: [...RETRY_INVALIDATES], label: RETRY_LABEL, success: retryToast });

  /** the last finished run already reflected in the UI (null until the first one is seen) */
  const seen = useRef<string | null>(null);
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    const run = finishedRun(d);
    // a run going (or none yet) at the first read: whatever finishes later is new (declared — the old line stayed
    // silent about a run it had watched from the page load)
    if (!run) {
      seen.current ??= "";
      return;
    }
    const key = runKey(run);
    const first = seen.current === null;
    if (seen.current === key) return;
    seen.current = key;
    if (first && !watch) return; // page load: nothing new to announce
    for (const k of AUTO_FINISHED_INVALIDATES) void qc.invalidateQueries({ queryKey: [k] });
    const t = autoTriageText(run, false);
    // preserved-for-retry after a provider outage is not a Project Zero failure: only a manual retry is red
    if (t) toast.show(t, run.failed?.length ? "error" : "ok");
  }, [d, qc, toast, watch]);

  const { mutate } = retry;
  const retryNow = useCallback(() => mutate({}), [mutate]);
  return { status: d, retryNow, retrying: retry.isPending };
}
