/**
 * Deal Flow payload types: `GET /api/deal-flow/inbox` (the old `/api/inbox` shape, review 009) and the decision call.
 * Field names are the old ones on purpose — the protected client rules in this folder read them as they are.
 */

export type Decision = "new" | "research" | "watch" | "kept" | "rejected" | "baseline";
export type AnalysisState = "UNANALYZED" | "ANALYZING" | "ANALYZED" | "FAILED";

export type Feedback = {
  label?: string;
  adjustment?: number;
  active?: boolean;
  reason?: string;
  reviewed?: number;
  not_ml?: string;
};

export type AttentionV2 = {
  score?: number;
  applied?: unknown[];
  explain?: string;
  gated?: string | null;
  lens?: number;
  final?: number | null;
  diff?: number;
  diff_explain?: string;
  entity?: { type?: string; label?: string; penalty?: number; reason?: string };
};

/** What the old scan stored per lead (location, provenance, ingest tags). */
type Provenance = {
  source: string;
  source_id?: string;
  discovery_tier?: string;
  source_url?: string;
  date?: string;
  date_kind?: string;
  detected_on?: string;
  source_date?: string | null;
  src_quality?: number | null;
  quality_source_id?: string;
  also_seen?: Array<{ source: string; url?: string }>;
  run_id?: string;
  first_seen?: string;
  first_seen_run?: string;
  last_observed?: string;
  seen_runs?: number;
};

type Location = { location?: string; country?: string; geo?: string[]; geo_scope?: string };

type Tags = {
  description?: string;
  why?: string[];
  archetype_hits?: number[];
  twins?: string[];
  priority?: number;
  opportunistic?: boolean;
};

/** Computed by the server on every read, never stored. */
type Ranking = {
  themes?: string[];
  lens?: { score: number; signals: string[] };
  attention_v2?: AttentionV2;
  feedback?: Feedback;
};

/** Machine analysis state (its panels arrive with the analysis port). */
type AnalysisMarks = {
  analysis_state?: AnalysisState;
  analysis_error?: string;
  analysis_level?: string;
  analysis_started_at?: string;
  deep_state?: string;
};

export type RevisitKind = "funding_round" | "registry_event" | "founder_or_key_hire" | "independent_corroboration";

/** A material change since the rejection (review 018, decision 0004): set by the server only on a candidate whose
 *  stored status is `rejected`, cleared by any later status decision. Read by `revisit.ts` only. */
export type Revisit = {
  kind: RevisitKind | string;
  since: string;
  date_source?: string;
  rejected_on?: string | null;
  evidence_url: string;
  evidence?: Array<{ url: string; [k: string]: unknown }>;
  note?: string | null;
  submission_id?: string;
  flagged_at: string; // UTC, for ordering
  flagged_on?: string; // its Berlin day, for display
  /** independent_corroboration only (Codex H-129 / H-131): every supporting reference, this report's evidence_url last. */
  corroboration?: Array<{ evidence_url: string; submission_id?: string | null }>;
};

/** `pz_status` is the stored status (new in 009), sent back as `expected_status` so a stale click is refused.
 *  `revisit` is new in 018. */
export type Candidate = { id: string; name: string; decision: Decision; notes?: string; pz_status?: string; revisit?: Revisit | null } & Provenance &
  Location &
  Tags &
  Ranking &
  AnalysisMarks;

export type ReportRow = {
  source: string;
  tier?: string;
  status: string;
  note?: string;
  geo?: string[];
  source_id?: string;
  url?: string;
  raw?: number | null;
  count?: number | null;
  baseline?: number | null;
};

export type NamedCompany = {
  id?: string;
  name: string;
  source?: string;
  source_url?: string;
  source_date?: string;
  first_seen?: string;
};

export type ScanSummary = {
  new?: number;
  baseline?: number;
  noise?: number;
  pre_company_new?: number;
  run_id?: string;
  scan_started?: string;
  scan_finished?: string;
  sources_attempted?: number;
  sources_ok?: number;
  sources_failed?: number;
  sources_off?: number;
  raw_records?: number;
  merged_cross_source?: number;
  merged_into_existing?: number;
  known_skipped?: number;
  known_pipeline?: number;
  known_pipeline_names?: string[];
  pipeline_label?: string;
  new_companies?: NamedCompany[];
  sources?: ReportRow[];
};

export type WsGeos = { eu: string[]; na: string[]; un?: string[] };

export type InboxPayload = {
  candidates: Candidate[];
  last_run: string | null;
  report?: ReportRow[];
  last_summary?: ScanSummary;
  themes: Record<string, string>;
  feedback_label?: string;
  feedback_min_reviewed?: number;
  feedback_cap?: number;
  pipeline_label?: string;
  ws_geos?: WsGeos;
  /** the candidates with a current `revisit` flag (review 018) */
  revisit_count?: number;
};

/** `POST /api/deal-flow/candidates/{id}/decision` → the old decide answer plus the new fields. */
export type DecisionResult = {
  ok: boolean;
  id: string;
  status: string;
  previous_status: string;
  changed: boolean;
  feedback: Feedback | null;
  resolved_from?: { namespace: string; id: string };
};
