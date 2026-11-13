/** A small Deal Flow: enough candidates to exercise the top-15 cut, every workspace and every decision. */
import type { TriagePayload, TriageSummary } from "../model/triage";
import type { AutoStatus, RetryAnswer } from "../model/triageAuto";
import type { Candidate, FindStart, FindStatus, InboxPayload, ScanHistory } from "../model/types";
import findAnswersJson from "./scan/find_answers.json";
import findStatusJson from "./scan/find_status.json";
import scanInboxJson from "./scan/inbox.json";
import scanHistoryJson from "./scan/scan_history.json";
import triageAnswersJson from "./triage/answers.json";
import triageInboxJson from "./triage/inbox.json";
import triagePayloadJson from "./triage/triage.json";
import autoRetryJson from "./triage_auto/retry.json";
import autoStatusJson from "./triage_auto/status.json";
import autoTriageJson from "./triage_auto/triage.json";

const DAY = 864e5;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString().slice(0, 10);

const STATUS: Record<Candidate["decision"], string> = { new: "new", research: "reviewing", watch: "watch", kept: "kept", rejected: "rejected", baseline: "baseline" };

export function cand(id: string, extra: Partial<Candidate> = {}): Candidate {
  const decision = extra.decision ?? "new";
  return {
    id,
    name: `Company ${id}`,
    decision,
    pz_status: STATUS[decision],
    source: "src-a",
    location: "Berlin, Germany",
    description: `What ${id} does.`,
    run_id: "r1",
    ...extra,
  };
}

/** 17 undecided European candidates with different signals (more than the queue's 15), plus the special cases. */
export function inbox(): InboxPayload {
  const eu = Array.from({ length: 17 }, (_, i) =>
    cand(`e${i + 1}`, {
      source_date: iso(i % 4 === 0 ? 3 : i % 4 === 1 ? 20 : 200),
      archetype_hits: i % 3 === 0 ? [1, 2] : [],
      discovery_tier: i % 5 === 0 ? "pre_company" : "announcement",
      priority: i % 2,
      source: i % 2 ? "src-a" : "src-b",
      themes: i % 4 === 0 ? ["climate"] : [],
    }),
  );
  return {
    candidates: [
      ...eu,
      cand("gated", { attention_v2: { gated: "noise", score: 1 }, source_date: iso(1) }),
      cand("ns", { source_date: iso(1), archetype_hits: [1, 2], also_seen: [{ source: "x" }, { source: "y" }] }),
      cand("tri1", { name: "Grant to Real Name GmbH", source_date: iso(2), archetype_hits: [1], analysis_state: "ANALYZED" }),
      cand("r1", { decision: "research" }),
      cand("w1", { decision: "watch" }),
      cand("k1", { decision: "kept" }),
      cand("x1", { decision: "rejected" }),
      cand("b1", { decision: "baseline" }),
      cand("us1", { location: "Austin, TX" }),
      cand("ca1", { location: "Toronto" }),
      cand("u1", { location: undefined, geo_scope: "global" }),
    ],
    last_run: "r1",
    last_summary: { new: 3, run_id: "r1" },
    report: [],
    themes: { climate: "Climate" },
    feedback_cap: 3,
    feedback_min_reviewed: 5,
    ws_geos: { eu: ["DACH"], na: ["US", "CA"], un: [] },
  };
}

export function proposal(id: string, extra: Partial<TriageSummary> = {}): TriageSummary {
  return {
    candidate_id: id,
    proposal: "KEEP",
    display_proposal: "KEEP",
    status: "ok",
    stage: "stage1",
    confidence: "high",
    reasons: ["Strong founder signal"],
    missing: [],
    flags: [],
    flash: { proposal: "KEEP" },
    veto: null,
    edge: "PRE_FUNDING_EDGE",
    themes: [],
    routing: { queue: "operating", reason: "European startup" },
    entity: { display_name: "Real Name GmbH", broken: "grant title", entities: [{ name: "Real Name GmbH", evidence: "awarded to Real Name GmbH", method: "regex" }] },
    portfolio: { status: "NONE", route_to_omar: false, evidence: [], twins: [], record: null },
    stale: false,
    obvious_reject: false,
    mohamed: null,
    queue: { state: "NEEDS_MOHAMED", reason: "high-value", priority: 9, priority_why: ["keep"] },
    ...extra,
  };
}

export function triage(): TriagePayload {
  return {
    architecture: { prompt_version: "v3" },
    proposals: {
      tri1: proposal("tri1"),
      ns: proposal("ns", { proposal: "REJECT", display_proposal: "REJECT", routing: { queue: "non_startup", reason: "university" }, queue: null, entity: { display_name: "Company ns", broken: "", entities: [] } }),
    },
    counts: {},
    calibration: { decisions: 0, agreement: null, machine_rejects_reviewed: 0, machine_rejects_overturned_to_keep_or_research: 0 },
    note: "Proposals only.",
  };
}

/* ------------------------------------------------------------------ the scan (review 034a)
 * Kept as JSON in `scan/` (invented names only) so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/scan/`, byte-identical copies):
 * - `inbox.json`: five candidates and the last scan — a report of seven sources (a watcher, two structured registries
 *   in Europe, a failed UK feed, an all-geography wire, a US registry and a disabled Canadian feed; one row with an
 *   intake refusal) and its full summary (three new companies, two pipeline names, one refusal);
 * - `find_status.json`: `GET find_status` idle, running (2 / 7), running further (5 / 7), done (its result with one
 *   refusal) and stopped (an error);
 * - `find_answers.json`: `POST find` started, and already running;
 * - `scan_history.json`: two scans of 14 recorded. */

export type FindCase = keyof typeof findStatusJson;
export const scanInbox = (): InboxPayload => structuredClone(scanInboxJson) as unknown as InboxPayload;
export const findStatus = (c: FindCase = "idle"): FindStatus => structuredClone(findStatusJson[c]) as unknown as FindStatus;
export const findAnswer = (c: keyof typeof findAnswersJson = "started"): FindStart => structuredClone(findAnswersJson[c]);
export const scanHistory = (): ScanHistory => structuredClone(scanHistoryJson) as unknown as ScanHistory;

/** The inbox a read finds after the `done` scan: its run, summary and report, and its two new companies. */
export function afterScan(ib: InboxPayload = scanInbox()): InboxPayload {
  const done = findStatus("done");
  const r = done.result!;
  const fresh = (r.new_companies ?? []).map((n) =>
    cand(n.id!, { name: n.name, source: n.source, source_url: n.source_url, source_date: n.source_date, first_seen: n.first_seen, run_id: r.run_id }),
  );
  return { ...ib, candidates: [...fresh, ...ib.candidates], last_run: r.run_id ?? null, last_summary: r, report: done.rows };
}

/* ------------------------------------------------------------------ machine triage writes (review 035a)
 * Kept as JSON in `triage/` (invented names only), byte-identical copies in `e2e/tests/fixtures/triage/` for the mocked
 * Playwright spec:
 * - `inbox.json`: eight European and one US candidate — a KEEP, a RESEARCH, a WATCH, two obvious REJECTs (both models,
 *   Stage 0), a single-model REJECT, an obvious REJECT outside the operating queue and an obvious REJECT already decided;
 * - `triage.json`: their proposals (`obvious_reject` as the server derives it) and a calibration of 4 decisions;
 * - `answers.json`: `POST triage/decide` answers (accept REJECT / KEEP / RESEARCH, override WATCH, the 409 and the 400) and
 *   `POST triage/batch_reject` answers (the previews, the applied batches, the moved-company 409). */

export type TriageAnswer = keyof typeof triageAnswersJson;
export const triageInbox = (): InboxPayload => structuredClone(triageInboxJson) as unknown as InboxPayload;
export const triageWorld = (): TriagePayload => structuredClone(triagePayloadJson) as unknown as TriagePayload;
export const triageAnswer = <T = Record<string, unknown>>(name: TriageAnswer): T => structuredClone(triageAnswersJson[name]) as unknown as T;

/* ------------------------------------------------------------------ machine triage after a scan (review 035b)
 * Kept as JSON in `triage_auto/` (invented names only), byte-identical copies in `e2e/tests/fixtures/triage_auto/` for
 * the mocked Playwright spec. The world is the scan's (`scan/inbox.json`): its last scan selected Quillon Robotics,
 * Fennmoor Grid and Tamberlane Optics.
 * - `status.json`: `GET triage_auto` — no run yet, switched off, running, done, partial (two kept for an automatic
 *   retry, Retry now (2)), failed (one needs a manual retry), and a Retry now run going, then done;
 * - `retry.json`: `POST triage_retry` — started, and the two old refusals;
 * - `triage.json`: the triage view after the partial run — a KEEP for Quillon Robotics, the other two in `pending`. */

export type AutoCase = keyof typeof autoStatusJson;
export const autoStatus = (c: AutoCase = "done"): AutoStatus => structuredClone(autoStatusJson[c]) as unknown as AutoStatus;
export const retryAnswer = (c: keyof typeof autoRetryJson = "started"): RetryAnswer => structuredClone(autoRetryJson[c]) as RetryAnswer;
export const autoTriageView = (): TriagePayload => structuredClone(autoTriageJson) as unknown as TriagePayload;
