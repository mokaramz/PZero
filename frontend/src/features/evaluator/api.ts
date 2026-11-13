/**
 * The Active Evaluator endpoints (review 024) — the ONE place their paths live. The bodies are the old ones under new
 * paths.
 *
 * - `GET evaluator/sessions` → the old `GET evaluations` body (strip rows, states, families, labels).
 * - `GET evaluator/session?id=` → the old `GET evaluation` body `{session, panel, next}` | 404 `{error: "unknown session"}`.
 * - `POST evaluator/start {subject}`, `deck {id, text}`, `next {id}`, `skip {id, qid}`, `answer {id, qid, text}`,
 *   `evidence {id, claim_id, …}`, `resolve {id, claim_id, note}`, `end {id}` → the old answers with `session`, `panel`
 *   and `row`. A refusal is HTTP 200 `{ok: false, error}` (409 before the legacy import): `lib/api` turns it into a
 *   failure toast, and nothing is refreshed. The old page never called `next` (the session read carries the question).
 * - The why-now trigger is Conviction's `POST conviction/imq_trigger` (see features/conviction/api).
 */
import { CALLS } from "@/features/founder-calls/api";
import { PIPELINE, useImqTrigger } from "@/features/conviction/api";
import { useAction, useApi } from "@/lib/hooks";
import type { ActionResult, EvaluationDetail, EvaluationsWorkspace, EvidenceBody, StartSubject } from "./model/types";

export const SESSIONS = "evaluator/sessions";
export const SESSION = "evaluator/session";
export const START = "evaluator/start";
export const DECK = "evaluator/deck";
export const NEXT = "evaluator/next";
export const SKIP = "evaluator/skip";
export const ANSWER = "evaluator/answer";
export const EVIDENCE = "evaluator/evidence";
export const RESOLVE = "evaluator/resolve";
export const END = "evaluator/end";

/** What every evaluator write makes stale: the strip, the open session and Today (it reads the sessions for the
 *  human-outcome hold and the founder-call follow-ups, review 030a). */
export const EVAL_KEYS = [SESSIONS, SESSION, "today"];
/** Ending a session also writes a founder call and the linked Conviction fields. */
export const END_KEYS = [...EVAL_KEYS, CALLS, PIPELINE];
/** A why-now trigger changes the Conviction record, and the session's IMQ panel reads it. */
export const TRIGGER_KEYS = [...EVAL_KEYS, PIPELINE];

/** The old action labels (Background activity and the "✓ … — done" / "✕ … failed" toasts): only start had its own. */
export const LABEL = { start: "Starting the evaluator", action: "Working" } as const;

export function useSessions() {
  return useApi<EvaluationsWorkspace>(SESSIONS);
}

/** One session; an unknown id (404) is shown in place, never retried. */
export function useSession(id: string) {
  return useApi<EvaluationDetail>(SESSION, { id }, { retry: false });
}

export function useStart() {
  return useAction<{ subject: StartSubject }, ActionResult & { id: string }>(START, { invalidates: EVAL_KEYS, label: LABEL.start });
}

function useEvalAction<TBody extends object>(path: string, invalidates = EVAL_KEYS) {
  return useAction<TBody, ActionResult>(path, { invalidates, label: LABEL.action });
}

export const useDeck = () => useEvalAction<{ id: string; text: string }>(DECK);
export const useAnswer = () => useEvalAction<{ id: string; qid: string; text: string }>(ANSWER);
export const useSkip = () => useEvalAction<{ id: string; qid: string }>(SKIP);
export const useEvidence = () => useEvalAction<EvidenceBody>(EVIDENCE);
export const useResolve = () => useEvalAction<{ id: string; claim_id: string; note: string }>(RESOLVE);
export const useEnd = () => useEvalAction<{ id: string }>(END, END_KEYS);

/** The evaluator's "Record dated why-now trigger": Conviction's endpoint, refreshing the session too. */
export const useEvaluatorTrigger = () => useImqTrigger(TRIGGER_KEYS);
