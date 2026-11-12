/** The Active Evaluator payloads (review 024) — the old `/api/evaluations`, `/api/evaluation?id=` and `eval_*` bodies,
 *  unchanged, under new paths (see ../api). */

export type Subject = { kind: string; name: string; founder: string; slug?: string };

/** One sessions-strip row (the old `session_row`). */
export type SessionRow = {
  id: string;
  created: string;
  status: string;
  subject: Subject;
  claims: number;
  ledger_items?: number;
  questions: number;
  answers?: number;
  founder_reported?: number;
  deck_claims?: number;
  unknowns?: number;
  contradictions?: number;
};

export type Family = { id: string; label: string; dimension: string };

/** `GET evaluator/sessions` (the old `GET evaluations`). */
export type EvaluationsWorkspace = {
  sessions: SessionRow[];
  states: string[];
  families: Family[];
  deck_label: string;
  founder_label: string;
};

export type Evidence = { kind?: string; url?: string; label?: string; note?: string; on?: string };

export type Claim = {
  id: string;
  family: string;
  text: string;
  state: string;
  source?: string;
  created: string;
  resolved: boolean;
  resolution?: { note: string; on?: string };
  evidence: Evidence[];
  related?: string[];
  label?: string;
};

export type Question = {
  id: string;
  family: string;
  text: string;
  kind: string;
  reason?: string;
  verification_hint?: string;
  asked_at?: string;
  answer?: string | null;
  answered_at?: string;
};

export type Ended = {
  on: string;
  call_id?: string;
  call_error?: string;
  founder_reported: number;
  deck_claims: number;
  unknowns: number;
  answers?: number;
  ledger_items?: number;
  canonical_answered?: number;
  canonical_sections?: number;
  count_note?: string;
  contradictions: number;
  tasks: number;
  followups: string[];
  imq: { state: string; blockers: string[] };
};

/** Scout 00 evidence staged on a claim (written by the Scout Bridge, which the rewrite does not have: read-only). */
export type StagedEvidence = { claim_id: string; url: string; label?: string; note?: string; supports: string; date?: string; job_id: string; state: string };

export type Context = {
  kind?: string;
  name?: string;
  founder?: string;
  slug?: string;
  provisional?: number | null;
  verified_score?: number | null;
  verified?: { founders?: boolean; traction?: boolean; funding?: boolean };
  conflict?: string;
  adjacent?: Array<{ name: string }>;
  research_facts?: Record<string, { claim?: string }>;
};

export type Task = { id: string; text: string; how: string; state: string };

export type Session = {
  id: string;
  created: string;
  updated: string;
  status: string;
  subject: Subject;
  context: Context;
  deck?: { text?: string; imported_at?: string; claims?: string[] };
  ledger: Claim[];
  questions: Question[];
  queue: Array<{ kind: string; text: string }>;
  tasks: Task[];
  memo_deltas: string[];
  ended: Ended | null;
  plan: Array<{ family: string; label: string; priority: number }>;
  staged_evidence?: StagedEvidence[];
};

export type Group = { claims: number; states: Record<string, number>; covered: boolean; latest: string[] };

export type Panel = {
  groups: Record<string, Group>;
  evidence_gaps: string[];
  contradictions: Array<{ id: string; text: string }>;
  provisional_movement: Array<{ dimension: string; current: number | null; verified_flag: boolean | null; provisional_direction: string }>;
  imq: { state: string; blockers: string[] };
};

/** `GET evaluator/session?id=` (the old `GET evaluation`); 404 `{error: "unknown session"}`. */
export type EvaluationDetail = { session: Session; panel: Panel; next: Question | null };

export type StartSubject = { kind: "company"; slug: string; name: string; founder: string } | { kind: "external"; name: string; founder: string };

/** Every `POST evaluator/<action>` answer: the old body, with the fresh session, panel and strip row. A refusal is
 *  HTTP 200 `{ok: false, error, …}` — `lib/api` turns it into a failure. */
export type ActionResult = { ok: boolean; error?: string; id?: string; session?: Session; panel?: Panel; row?: SessionRow; next?: Question | null };

export type EvidenceBody =
  | { id: string; claim_id: string; url: string; label: string; note: string; kind: "public" }
  | { id: string; claim_id: string; kind: "operator"; confirm: true; note: string };
