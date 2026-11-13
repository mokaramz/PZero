/** The WATCH view (review 037a) — the old `GET /api/watch` shapes, unchanged. */

export type TriggerStatus = "new" | "reviewed" | "dismissed";

export type Trigger = {
  id: string;
  name: string;
  candidate_id: string;
  predicate: string;
  label: string;
  high_value: boolean;
  source: string;
  /** `scan_rehit` (a later scan found a new source) or a page / news trigger */
  source_kind: string;
  url: string;
  source_date: string;
  first_observed: string;
  evidence: string;
  status: TriggerStatus;
  /** when the last status line was written ("" while new) */
  status_at?: string;
};

/** The per-URL page-check state (written by the sensors, review 037b; 037a only shows it). */
export type PageCheck = { last_checked?: string; last_state?: string; last_ok?: string; failures_in_row?: number; last_error?: string };

export type WatchedCompany = {
  key: string;
  name: string;
  candidate_id: string;
  urls: string[];
  checks: Record<string, PageCheck>;
  /** the 10 newest */
  triggers: Trigger[];
  open: number;
  triage_predates_evidence: boolean;
  machine_proposal: string | null;
};

export type WatchPayload = { companies: WatchedCompany[]; labels: Record<string, string>; note: string };

/** `POST watch_target` — the old `{name, urls[], candidate_id?, active?}`; a 400 names the refused field. */
export type WatchTargetBody = { name: string; urls: string[]; candidate_id: string };
export type WatchTargetAnswer = { ok: boolean; target: Record<string, unknown> };

/** `POST watch_ack` — appends a status line; the trigger stays on record. */
export type AckStatus = Exclude<TriggerStatus, "new">;
export type WatchAckBody = { id: string; status: AckStatus };
export type WatchAckAnswer = { ok: boolean; kind: "status"; trigger_id: string; status: AckStatus; at: string; note: string };
