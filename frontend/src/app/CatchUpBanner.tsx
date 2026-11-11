import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { isMissingEndpoint } from "@/lib/api";
import { useApi } from "@/lib/hooks";

type Done = { label: string; ok: boolean; note: string };
type CatchUp = { running: boolean; queue: string[]; current: string | null; done: Done[]; enabled: boolean };

const POLL_RUNNING_MS = 2500;
const POLL_IDLE_MS = 60_000;

/** Visible catch-up: when the app opens, overdue checks run in the background — never silently. When it finishes,
 *  every cached view refreshes. Renders nothing while idle, and nothing (and stops polling) when the server has no
 *  /api/catchup endpoint yet. */
export function CatchUpBanner() {
  const qc = useQueryClient();
  const q = useApi<CatchUp>("catchup", undefined, {
    staleTime: 0,
    retry: (failures, error) => !isMissingEndpoint(error) && failures < 1,
    refetchInterval: (s) => (isMissingEndpoint(s.state.error) ? false : s.state.data?.running ? POLL_RUNNING_MS : POLL_IDLE_MS),
  });
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
  const left = d.queue.length - d.done.length;
  return (
    <div
      className="small"
      role="status"
      data-testid="catchup-banner"
      style={{ padding: "6px 16px", background: "var(--tint-blue, #eef4ff)", borderBottom: "1px solid var(--hair)" }}
    >
      <b>
        Catching up on {d.queue.length} overdue check{d.queue.length === 1 ? "" : "s"}…
      </b>{" "}
      {d.current ? `Now: ${d.current}.` : "Starting."} {left > 0 && <span className="faint">{left} left. </span>}
      <span className="faint">
        Project Zero runs on your computer, so periodic work (WATCH checks, scans) happens when it is open. Budget caps apply; nothing is sent to
        anyone.
      </span>
    </div>
  );
}
