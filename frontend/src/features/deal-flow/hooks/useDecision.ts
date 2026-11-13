import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { DECISION_LABEL, decisionBody, decisionPath, patchDecided, type DecisionBody, type SentDecision } from "../model/decision";
import type { Candidate, DecisionResult, InboxPayload } from "../model/types";
import { INBOX, INBOX_KEY } from "./useDealFlowData";

/** The server refused a decision made on a stale row (its body names the `current` status). */
const isStale = (e: unknown) => e instanceof ApiError && e.status === 409;

/**
 * Decide one candidate. Resolves true when the server saved it.
 * - success: the cached row is patched in place first (the page reacts at once), then the inbox is refetched, because
 *   the returned feedback also moves the other candidates of the same source (review 009, Codex #3);
 * - 409 (stale): the error toast, then a refetch, so the cached row equals the server again. Nothing is applied
 *   optimistically, so nothing has to be rolled back.
 */
export function useDecision(c: Candidate | undefined) {
  const qc = useQueryClient();
  const action = useAction<DecisionBody, DecisionResult>(decisionPath(c?.id ?? ""), { invalidates: [], label: DECISION_LABEL });
  const { mutate, isPending } = action;
  const decide = useCallback(
    (decision: SentDecision, notes?: string) =>
      new Promise<boolean>((resolve) => {
        if (!c) return resolve(false);
        mutate(decisionBody(c, decision, notes), {
          onSuccess: (r) => {
            qc.setQueryData<InboxPayload>(INBOX_KEY, (old) => old && patchDecided(old, c.id, decision, notes, r));
            void qc.invalidateQueries({ queryKey: [INBOX] });
            void qc.invalidateQueries({ queryKey: ["today"] }); // Today's triage and live candidates (030a)
            void qc.invalidateQueries({ queryKey: ["home"] }); // the Investment Desk's new signals (031a)
            resolve(true);
          },
          onError: (e) => {
            if (isStale(e)) void qc.invalidateQueries({ queryKey: [INBOX] });
            resolve(false);
          },
        });
      }),
    [c, mutate, qc],
  );
  return { decide, busy: isPending };
}
