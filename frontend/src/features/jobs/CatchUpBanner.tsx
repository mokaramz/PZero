import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useCatchUp } from "./api";

/** Where the periodic work runs in the new app (review 032c). The old sentence said "Project Zero runs on your
 *  computer, so periodic work (WATCH checks, scans) happens when it is open."; the WATCH checks are not ported, and the
 *  jobs now run in this catch-up and in the new, optional Windows task. */
export const WHERE_JOBS_RUN =
  "Project Zero runs its periodic work (scans, news, snapshots) in this catch-up when the app opens, and in the optional Windows task “Project Zero v2 - background jobs”, registered disabled until the cutover.";
/** Kept verbatim from the old banner. */
export const BUDGET_NOTE = "Budget caps apply; nothing is sent to anyone.";

/** Visible catch-up (ported from the old `app/CatchUpBanner.tsx`, review 032c): when the app opens, overdue checks run
 *  in the background — never silently. When it finishes, every cached view refreshes. Renders nothing while idle, and
 *  nothing (and stops polling) when the server has no /api/catchup endpoint. */
export function CatchUpBanner() {
  const qc = useQueryClient();
  const q = useCatchUp();
  const wasRunning = useRef(false);
  const d = q.data;
  useEffect(() => {
    if (!d) return;
    if (d.running) wasRunning.current = true;
    else if (wasRunning.current) {
      wasRunning.current = false;
      void qc.invalidateQueries(); // fresh scans / triggers / snapshots everywhere
    }
  }, [d, qc]);
  if (!d || !d.running) return null;
  const queue = d.queue ?? [];
  const left = queue.length - (d.done ?? []).length;
  return (
    <div
      className="small"
      role="status"
      data-testid="catchup-banner"
      style={{ padding: "6px 16px", background: "var(--tint-blue, #eef4ff)", borderBottom: "1px solid var(--hair)", overflowWrap: "anywhere" }}
    >
      <b>
        Catching up on {queue.length} overdue check{queue.length === 1 ? "" : "s"}…
      </b>{" "}
      {d.current ? `Now: ${d.current}.` : "Starting."} {left > 0 && <span className="faint">{left} left. </span>}
      <span className="faint">
        {WHERE_JOBS_RUN} {BUDGET_NOTE}
      </span>
    </div>
  );
}
