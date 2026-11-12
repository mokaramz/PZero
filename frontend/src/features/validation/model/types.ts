/**
 * The Validation payloads (review 027a) — the old `GET /api/validation` and `GET /api/validation_scout_packet` bodies,
 * now `GET validation` and `GET validation/scout_packet?cycle=`. Keys and their order are the old ones (see the old
 * `services/validation.py::view`). Fields the page does not read (`lead_times`, `routing`, the calibration matrix,
 * `vocab.evidence_class`, …) are typed for completeness and kept by the server.
 */
export type Stage = "discovered" | "machine_keep_research" | "mohamed_accepted" | "conviction" | "verified" | "radar" | "imq" | "omar";
/** The conversion table's columns, in the old order. */
export const STAGES: Stage[] = ["discovered", "machine_keep_research", "mohamed_accepted", "conviction", "verified", "radar", "imq", "omar"];

export type Headline = {
  found_this_month: number;
  pre_funding_share: number | null;
  pre_funding_this_month: number;
  median_lead_days: number | null;
  lead_n: number;
  found_at_announcement: number;
  strong_cases: number;
  strong_found_early: number;
  strong_found_late: number;
  exceptional_recall: number | null;
  strong_universe: number;
  strong_found_and_kept: number;
  false_negatives: number;
  never_seen: number;
  unique_source_this_month: number;
  conviction: number;
};

export type SourceRow = {
  source_id: string;
  source: string;
  discoveries: number;
  unique: number;
  pre_company: number;
  pre_funding: number;
  machine_keep_research: number;
  mohamed_accepted: number;
  conviction: number;
  strong: number;
  review_min: number;
  at_announcement: number;
  duplicate_rate: number | null;
  pre_funding_share: number | null;
  keep_research_rate: number | null;
  median_lead_days: number | null;
  lead_n: number;
  value_per_discovery: number;
  lifecycle?: string;
};

export type Audit = {
  id: string;
  type: "miss" | "false_positive";
  company: string;
  recorded_at: string;
  note?: string;
  earliest_signal?: string;
  earliest_signal_date?: string;
  signal_source?: string;
  should_have_found?: string;
  why_missed?: string;
  preventable?: string;
  improvement?: string;
  causes?: string[];
  miss_type?: string;
  lesson?: string;
};

export type Outcome = { id: string; company: string; kind: string; event_date: string; evidence_url: string; recorded_at: string; note: string };

export type Calibration = {
  decisions: number;
  agreed: number;
  agreement: number | null;
  machine_rejects_overturned: number;
  machine_keeps_rejected: number;
  matrix: Record<string, Record<string, number>>;
  who_was_right: Record<string, number>;
  disagreements: Array<{ name: string; machine: string; mohamed: string; outcome: string; right: string }>;
  review_minutes_est: number;
  note: string;
};

export type ConversionRow = { group: string } & Record<Stage, number>;

export type Measurement = { metric: string; meaning: string; state: string; n: number; needs: string };

export type Snapshot = Record<string, number | string | null>;

export type BenchmarkSystem = { system: string; companies: number; pz_earlier: number; pz_later_or_same: number; median_days: number | null; examples: string[] };

/** `available: false` until News & Learning is ported (decision b); `reason` says why. */
export type NewsMetrics = {
  available: boolean;
  reason?: string;
  reviewed?: number;
  caught_early?: number;
  known_late?: number;
  operational_misses?: number;
  historical_cases?: number;
  not_yet_reviewed?: number;
  median_lead_days?: number | null;
  preventable_misses?: number;
  most_common_miss_cause?: string | null;
  early_discovery_sources?: string[];
};

export type Alpha = { key: string; found: number; investigate: number; contact_yes: number };

/** The native search bridge pilot's metrics (the old shape). The rewrite never sends them (decision d: the pilot depends
 *  on the Scout search bridge, which is never ported): `native_bridge` is `{available: false, reason}` (or null, the
 *  old answer when the pilot could not be read). */
export type NativeBridgeMetrics = {
  label: string;
  status: { state: string; day_usd: number; month_usd: number; daily_cap: number; monthly_cap: number; x_hunts_this_week: number; x_hunts_per_week: number };
  spend_usd: number;
  convergence: number;
  funnel: Record<string, number>;
  cost_per: Record<string, number | null>;
  alpha: Record<"lane" | "geography" | "query" | "web_vs_x" | "source", Alpha[]>;
  note: string;
};
export type NativeBridgeDeferred = { available: false; reason?: string };
export type NativeBridge = NativeBridgeMetrics | NativeBridgeDeferred | null;
export type Vocab = { kinds: Record<string, string>; miss_reasons: string[]; fp_causes: string[]; evidence_class: Record<string, string>; min_n: number };

export type ValidationPayload = {
  date: string;
  headline: Headline;
  sources: SourceRow[];
  conversion: Record<string, ConversionRow[]>;
  stage_labels: Record<Stage, string>;
  lead_times: Array<{ name: string; days: number | null; event: string; event_date?: string; kind: string }>;
  strength: Record<string, number>;
  horizon: Record<string, number>;
  calibration: Calibration;
  patterns: string[];
  misses: Audit[];
  false_positive_audits: Audit[];
  false_positive_watch: Array<{ name: string; stages: Stage[]; strength: string }>;
  outcomes: Outcome[];
  scout: { cycles: string[]; items: number; classification: Record<string, number>; last_packet: { at: string; cycle: string; companies: number } | null };
  snapshots: Snapshot[];
  measurement: Measurement[];
  benchmarks: { systems: BenchmarkSystem[]; note: string };
  news: NewsMetrics;
  verification_calibration: Record<string, { accepted: number; rejected: number }>;
  data_issues: string[];
  cost: { month: string; ai_usd_this_month: number; validation_usd: number };
  routing?: Record<string, unknown> | null;
  native_bridge?: NativeBridge;
  vocab: Vocab;
};

/** The Scout 00 feedback packet (a read: `cycle` is "all" when none was asked). */
export type Packet = { cycle: string; companies: number; text: string; sha: string; counts?: { successful: number; weak: number; misses: number; pending: number } };
