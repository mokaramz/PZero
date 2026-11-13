import { useState } from "react";

import { notStarted, useRunOverdue } from "@/features/jobs/api";
import { portedOverdue, runnerLive } from "../model/jobs";
import type { Health } from "../model/types";

export type RunOverdueState = ReturnType<typeof useRunOverdueNow>;

/**
 * "Run overdue now" (review 032c), one state for both of its places (the jobs panel and "Handled automatically"), as
 * the old page had one action. With the live runner it posts `catchup_run {only}` — the ported overdue jobs only — and
 * says why when the server did not start a run; without it (the deferred lock) it stays disabled with its reason (032a
 * decision h). It is offered while the server counts an overdue job and, with the runner, at least one of them is
 * ported.
 */
export function useRunOverdueNow(d: Health) {
  const live = runnerLive(d);
  const only = portedOverdue(d.jobs);
  const run = useRunOverdue();
  const [why, setWhy] = useState<string | null>(null);
  const start = () => {
    setWhy(null);
    run.mutate({ only }, { onSuccess: (r) => setWhy(r.started === false ? notStarted(r.reason) : null) });
  };
  return { live, only, visible: d.overdue > 0 && (!live || only.length > 0), start, pending: run.isPending, why };
}
