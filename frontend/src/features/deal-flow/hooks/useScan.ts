import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useToast } from "@/components/Toast";
import { isMissingEndpoint } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { ALREADY_RUNNING, FIND, FIND_LABEL, FIND_STATUS, finishToast, POLL_MS, SCAN_FINISHED_INVALIDATES, stoppedToast } from "../model/scan";
import type { FindStart, FindStatus } from "../model/types";

/**
 * The scan job (the old `FindBar` logic, review 034a): `find_status` is polled every 1.2 s while a scan runs — also one
 * started elsewhere, before the page was opened — and right after this page started one. When a scan it saw running
 * ends, the finish (or stopped) toast is shown, the views a scan changes are read again, and `onFinished` runs. A server
 * without the endpoint (404) is never polled.
 */
export function useScan(onFinished: () => void) {
  const qc = useQueryClient();
  const toast = useToast();
  /** this page just started a scan: keep polling until find_status has seen it (read by the interval on each fetch) */
  const kicked = useRef(false);
  const fs = useApi<FindStatus>(FIND_STATUS, undefined, {
    staleTime: 0,
    retry: (n, e) => !isMissingEndpoint(e) && n < 1,
    refetchInterval: (q) => (isMissingEndpoint(q.state.error) ? false : q.state.data?.running || kicked.current ? POLL_MS : false),
  });
  const running = !!fs.data?.running;
  const wasRunning = useRef(false);
  useEffect(() => {
    const j = fs.data;
    if (!j) return;
    if (j.running) {
      wasRunning.current = true;
      kicked.current = false;
      return;
    }
    if (!wasRunning.current) return;
    wasRunning.current = false;
    kicked.current = false;
    if (j.error) toast.show(stoppedToast(j.error), "error");
    else if (j.result) toast.show(finishToast(j.result), "ok");
    for (const k of SCAN_FINISHED_INVALIDATES) void qc.invalidateQueries({ queryKey: [k] });
    onFinished();
  }, [fs.data, fs.dataUpdatedAt, qc, toast, onFinished]);

  const find = useAction<{ days: string }, FindStart>(FIND, { invalidates: [FIND_STATUS], label: FIND_LABEL });
  const start = (days: string) =>
    find.mutate(
      { days },
      {
        onSuccess: (r) => {
          if (r.running) toast.show(ALREADY_RUNNING);
          wasRunning.current = true;
          kicked.current = true;
          void fs.refetch();
        },
      },
    );

  return { status: fs.data, running, pending: find.isPending, start };
}
