/**
 * The News & Learning payloads (review 028a) — the old bodies under new paths (see ../api):
 * - `GET news` = the old `GET /api/news` (`services/news.py::view`);
 * - `GET news/weekly` = the old `GET /api/news_weekly` (`weekly_review(record=False)`);
 * - `GET news/sources?window=` = the old `GET /api/news_sources` (`services/news_sources.py::view`);
 * - `GET news/refresh_status` = the old `GET /api/news_refresh_status` (`refresh_status`).
 * Keys and their order are the old ones. Fields the page does not read (`date`, `state_labels`, `round`, `amount_m`,
 * `materiality_why`, `my_company`, `check.stages`, `backcast.before_pz`, …) are typed for completeness and kept by the
 * server (028a decision d).
 */

/* ------------------------------------------------------------------ GET news */
export type Independence = "primary" | "independent" | "syndicated";
export type Source = { publisher: string; url: string; published: string; headline: string; text_sha?: string; independence: Independence };
export type SignalKind = "known_early_signal" | "in_retrospect";
export type Signal = { date: string; precision: string; text: string; family: string; url: string; kind: SignalKind; sources?: string[] };
export type Materiality = "HIGH" | "MEDIUM" | "LOW" | "NOISE";
export type StoryState = "CAUGHT_EARLY" | "KNOWN_LATE" | "MISSED" | "HISTORICAL" | "NOT_RELEVANT" | "UNKNOWN";
export type Card = { what_happened: string; why_it_matters: string; the_company: string; vc_lesson: string; watch_next: string[]; generated_by: string };
export type Check = {
  known: boolean;
  pz_first_seen?: string | null;
  lead_days?: number;
  first_source?: string;
  first_tier?: string;
  stages?: string[];
  machine?: string | null;
  mohamed?: string | null;
  capital_stage?: string | null;
  state?: StoryState;
  possible_miss?: boolean;
  miss_window_signals?: Signal[];
};
export type Backcast = { timeline: Signal[]; earliest_plausible_signal: Signal | null; best_sensor: string; before_pz: boolean; learning: string };
export type Concept = { id: string; title: string; text: string };
export type Disagreement = {
  event_id?: string;
  company?: string | null;
  field: "amount_m" | "round" | string;
  values: Record<string, number | string>;
  event_date?: string;
  status: "AGREE" | "RESOLVED" | "OPEN" | string;
  basis?: string;
  agree?: string[];
  contradicted?: string[];
};
export type Story = {
  event_id: string;
  company: string;
  headline: string;
  summary: string;
  event_type: string;
  round?: string | null;
  amount_m?: number | null;
  event_date: string;
  geo: string[];
  themes: string[];
  materiality: Materiality;
  materiality_why?: string[];
  card: Card | null;
  type_label: string;
  sources: Source[];
  independent_sources: number;
  check: Check;
  state: StoryState | string;
  state_label: string;
  backcast: Backcast | null;
  concepts: Concept[];
  my_company?: boolean;
  in_deal_flow: boolean;
  outcome_proposal: { kind: string; effect: string } | null;
  outcome_decision: string | null;
  audit_id: string | null;
  source_notes?: string[];
  disagreements?: Disagreement[];
};
export type Theme = {
  theme: string;
  geo: string;
  companies: number;
  confidence: string;
  observation: string;
  why_it_matters: string;
  stories: Array<{ event_id: string; headline: string }>;
  pz_related: number;
};
export type NewsPayload = {
  date: string;
  pz_start: string;
  today: Story[];
  stories: Story[];
  caught_early: Story[];
  known_late: Story[];
  misses: Story[];
  historical: Story[];
  my_companies: Story[];
  themes: Theme[];
  counts: Record<string, number>;
  metrics: { median_lead_days: number | null; caught_early: number };
  concept_of_the_day: Concept;
  notice_earlier: string | null;
  last_run: NewsRun | null;
  state_labels: Record<string, string>;
  signal_families: string[];
  note: string;
};

/* ------------------------------------------------------------------ GET news/weekly */
export type Weekly = {
  week_ending: string;
  /** `state` is the state LABEL ("Caught early"), as before */
  top: Array<{ event_id: string; headline: string; state: string }>;
  caught_early: string[];
  missed: string[];
  pattern: string;
  sourcing_lesson: string;
  /** a concept without its id, or the concept of the day with it (two shapes, as before) */
  vc_lesson: { id?: string; title: string; text: string };
};

/* ------------------------------------------------------------------ GET news/refresh_status */
export type Feed = { ok: boolean; items?: number; error?: string; rate_limited?: boolean; reused?: string; latest?: string; cooldown_until?: string };
/** One `news/runs.jsonl` line (stored with sorted keys). Older lines lack the later fields. */
export type NewsRun = {
  run_id?: string;
  at: string;
  completed_at?: string;
  status?: "ok" | "partial" | "failed" | "interrupted";
  trigger?: string;
  feeds_checked?: number;
  sources_ok: number;
  sources_failed: string[];
  items: number;
  new: number;
  merged: number;
  duplicates_skipped: number;
  material_new?: number;
  noise_new?: number;
  reclassified?: number;
  events_total?: number;
  duration_s?: number;
  latest_published?: string;
  stale_feeds?: string[];
  cooldown?: string[];
  per_feed?: Record<string, Feed>;
  note?: string;
};
/** No refresh runs in 028a (it arrives with 028c), so `job` is always idle: `{running: false, …}` with the old keys. */
export type RefreshJob = {
  running: boolean;
  run_id?: string | null;
  stage?: string | null;
  trigger?: string | null;
  started_at?: string | null;
  feeds_done?: number | null;
  feeds_total?: number | null;
  ingested?: boolean | null;
  new?: number | null;
  merged?: number | null;
  elapsed_s?: number | null;
};
export type RefreshStatus = { job: RefreshJob; last: NewsRun | null; last_ok: NewsRun | null; events_total: number };

/* ------------------------------------------------------------------ GET news/sources?window= */
export type Window = "30" | "90" | "180" | "all";
export type Rate = { k: number; n: number; rate: number | null; lb: number | null; label: string };
export type Role = { role: string; basis: string; evidence: string };
export type SourceKind = "feed" | "deal_flow_reuse" | "external";
export type Technical = {
  state: string;
  basis: string;
  runs: number | null;
  ok?: number | null;
  ok_share: number | null;
  streak: number;
  lb?: number | null;
  label?: string;
  last_ok?: string | null;
  last_error?: string;
};
export type SourceRow = {
  name: string;
  kind: SourceKind;
  geo: string;
  home_scope: string;
  lifecycle: string;
  domain: string;
  articles: { n: number; digests?: number; precision: Rate; noise: Rate } & Record<string, unknown>;
  recall: Record<string, Rate>;
  speed: { n: number; label: string; precision: string; median_h?: number; p25_h?: number | null; p75_h?: number | null; within_24h?: Rate; within_72h?: Rate; first?: Rate };
  earliness: {
    companies: number;
    median_lead_days: number | null;
    pre_funding: number;
    precursor_types?: Record<string, number>;
    share_of_important?: Rate;
    examples: Array<{ company: string; lead_days: number; first_mention: string; precursor?: string; pre_funding?: boolean; event?: string }>;
    deal_flow?: Record<string, number | null> | null;
  };
  originality: { n: number; syndicated: Rate; press_release: Rate; original: Rate; confidence: string };
  unique: { events: number; companies: number; early_companies: number; by_scope?: Record<string, number>; of_covered?: Rate };
  authority: { prior: string; agree: number; contradicted: number; open: number; observed?: Rate; basis: string };
  technical: Technical;
  independent?: { outcomes: number; covered: number };
  hypothesis: string;
  sample: string;
  roles: Role[];
  best_use: string;
  not_for: string;
  limitations: string[];
  status: string;
  status_reasons: string[];
};
export type Best = {
  id: string;
  label: string;
  state: "RANKED" | "COLLECTING DATA";
  leader?: { source: string; why: string; n: number };
  runner_up?: { source: string; why: string } | null;
  confidence?: string;
  need?: string;
  warning?: string;
};
export type Missing = {
  domain: string;
  name: string;
  events?: Array<{ event_id: string; company: string | null; date: string; headline: string; how: string }>;
  how: Record<string, number>;
  n: number;
  database: boolean;
  ready: boolean;
};
export type SourcesPayload = {
  window: Window | string;
  start: string;
  today: string;
  benchmark_events: number;
  bias: {
    events: number;
    multi_source: number;
    origin_top?: { source: string; events: number };
    warnings: string[];
    independent_outcomes: number;
    concentrated?: boolean;
    overlap_ok?: boolean;
  };
  best: Best[];
  disagreements: Disagreement[];
  sources: SourceRow[];
  declining: Array<{ name: string; reasons: string[] }>;
  missing: Missing[];
  candidates: Array<{ id: string; name: string; url: string; state: string }>;
  windows: string[];
  scopes: Record<string, string>;
  note: string;
  evaluated_at: string | null;
};
