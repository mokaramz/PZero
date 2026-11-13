/**
 * The machine-triage write side on the page (review 035a): Mohamed accepts or overrides one proposal, or batch-accepts
 * the obvious REJECTs of the view. Pure — the bodies, the answers, the eligible ids, the toasts and the cache patch;
 * `hooks/useTriageDecide.ts` sends them.
 *
 * - `POST /api/deal-flow/triage/decide` `{id, verdict, mode, note?, expected_status?}` →
 *   `{ok, verdict, agreed, inbox_decision, open_keep}` (the old `triage_decide`). `expected_status` is the stored status
 *   the panel showed, so a decision on a candidate that changed meanwhile is refused (409) instead of overwriting it.
 * - `POST /api/deal-flow/triage/batch_reject` `{ids}` previews `{ok, preview, eligible, skipped}`; `{ids, confirm: true}`
 *   applies, `{ok, applied, skipped}` (the old `triage_batch_reject`).
 */
import { STATUS_FOR } from "./decision";
import type { TriageScope, TriageSummary, Verdict } from "./triage";
import type { Candidate, InboxPayload } from "./types";

export type TriageMode = "accept" | "override";

export const TRIAGE_DECIDE = "deal-flow/triage/decide";
export const TRIAGE_BATCH_REJECT = "deal-flow/triage/batch_reject";

/** What Mohamed sees the instant he clicks (the old action label of a triage decision). */
export const TRIAGE_LABEL = "Saving your triage decision";
export const BATCH_PREVIEW_LABEL = "Checking the obvious REJECTs";

export type TriageDecideBody = { id: string; verdict: Verdict; mode: TriageMode; note?: string; expected_status?: string };

/** The decision the verdict applied, in the old inbox names (`research` = the stored `reviewing`); null for KEEP. */
export type InboxDecision = "rejected" | "watch" | "research";

export type TriageDecideAnswer = { ok: boolean; verdict: Verdict; agreed: boolean; inbox_decision: InboxDecision | null; open_keep: boolean };

export type BatchBody = { ids: string[]; confirm?: boolean };
export type BatchPreview = { ok: boolean; preview: true; eligible: number; skipped: Record<string, number> };
export type BatchApplied = { ok: boolean; applied: number; skipped: Record<string, number> };

export function triageDecideBody(c: Pick<Candidate, "id" | "pz_status">, verdict: Verdict, mode: TriageMode): TriageDecideBody {
  return { id: c.id, verdict, mode, ...(c.pz_status ? { expected_status: c.pz_status } : {}) };
}

/** The old toast after an accept / override that did not open the Keep form. */
export const decidedToast = (verdict: Verdict, mode: TriageMode) => `${mode === "accept" ? "Accepted" : "Overrode to"} ${verdict}`;

export const NO_OBVIOUS_REJECTS = "No obvious machine REJECTs in this view";

/** The candidates "Accept obvious REJECTs…" sends: undecided obvious REJECTs in the view's queue scope (the old page). */
export function obviousRejectIds(all: Candidate[], tri: Record<string, TriageSummary>, scope: TriageScope): string[] {
  return all.filter((c) => c.decision === "new" && tri[c.id]?.obvious_reject && (scope === "all" || tri[c.id].routing.queue === scope)).map((c) => c.id);
}

const total = (skipped: Record<string, number>) => Object.values(skipped).reduce((a, b) => a + b, 0);

/** The old toast after a confirmed batch: "Rejected N", plus " · skipped M" when anything was skipped. */
export const batchToast = (r: BatchApplied) => `Rejected ${r.applied ?? 0}${Object.keys(r.skipped ?? {}).length ? ` · skipped ${total(r.skipped)}` : ""}`;

/** The preview's skipped reasons as one line ("2 already decided · 1 no proposal"), empty when nothing is skipped. */
export const skippedLine = (skipped: Record<string, number>) =>
  Object.entries(skipped)
    .filter(([, n]) => n > 0)
    .map(([why, n]) => `${n} ${why}`)
    .join(" · ");

/** The cached inbox after a triage decision: the rows change in place (the view decision and the stored status). */
export function patchTriaged(ib: InboxPayload, ids: readonly string[], decision: InboxDecision): InboxPayload {
  const hit = new Set(ids);
  return { ...ib, candidates: ib.candidates.map((c) => (hit.has(c.id) ? { ...c, decision, pz_status: STATUS_FOR[decision] } : c)) };
}
