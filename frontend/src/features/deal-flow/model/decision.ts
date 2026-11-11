/**
 * The ONE adapter between the decision names the Deal Flow view speaks (the old `decide` names, kept because the
 * protected rules read them) and the candidate statuses the decision API stores (review 009).
 *
 * `kept` is never sent: Keep is a Conviction save, not a Deal Flow decision.
 */
import type { Candidate, Decision, DecisionResult, InboxPayload } from "./types";

export type SentDecision = Exclude<Decision, "kept">;
export type CandidateStatus = "new" | "reviewing" | "watch" | "rejected" | "baseline";

export const STATUS_FOR: Record<SentDecision, CandidateStatus> = {
  new: "new",
  research: "reviewing",
  watch: "watch",
  rejected: "rejected",
  baseline: "baseline",
};

/** `POST /api/deal-flow/candidates/{id}/decision`. `expected_status` is the stored status the operator saw, so a
 *  decision made on a stale row is refused (409) instead of overwriting a newer one. */
export type DecisionBody = { status: CandidateStatus; notes?: string; expected_status?: string };

export const DECISION_LABEL = "Saving your decision";

export const decisionPath = (id: string) => `deal-flow/candidates/${encodeURIComponent(id)}/decision`;

export function decisionBody(c: Pick<Candidate, "pz_status">, decision: SentDecision, notes?: string): DecisionBody {
  return { status: STATUS_FOR[decision], ...(notes !== undefined ? { notes } : {}), expected_status: c.pz_status };
}

/** The cached inbox after a successful decision: the row changes in place (decision, stored status, the notes when they
 *  were sent, the source feedback the call returned); every other row is untouched until the refetch lands. */
export function patchDecided(ib: InboxPayload, id: string, decision: SentDecision, notes: string | undefined, r: DecisionResult): InboxPayload {
  return {
    ...ib,
    candidates: ib.candidates.map((c) =>
      c.id === id
        ? { ...c, decision, pz_status: r.status, ...(notes !== undefined ? { notes } : {}), ...(r.feedback ? { feedback: r.feedback } : {}) }
        : c,
    ),
  };
}
