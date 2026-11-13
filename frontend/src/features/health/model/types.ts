/**
 * Payloads for System health (review 032a): `GET system_health` (the verdict, status, issues and diagnostics) and the
 * read-only `GET system_health_overview` (job history, models and spend, the pipeline counts). Both are the old
 * answers key for key, with these changes:
 * - (c) retired and removed: the overview's `search_bridge`, `scout00` and `native`, `pipeline.intake`, and
 *   `sources[].repair.bridge_job`;
 * - (d) sent as `{"deferred": "<reason>"}` (./deferred): `selfcheck`, `job_runner.lock`, `build`, `source_discovery`,
 *   `watch.failing_checks`; in the overview `backups`, `integrity` and `releases`;
 * - (e) `jobs`, `job_runner.runners` and the overview `jobs` are the imported snapshot (no runner until 032c);
 * - (k) the issue texts and the status sentence come from the server, already reworded.
 */
import type { Maybe } from "./deferred";

export type IssueGroup = "need" | "auto" | "ext" | "info";
export type Issue = { level: "warn" | "info"; what: string; do: string; group?: IssueGroup };
export type StatusKey = "ok" | "limited" | "action" | "degraded" | "unknown";
export type OverallStatus = { key: StatusKey; label: string; sentence: string; groups: Record<IssueGroup, number>; last_job_report: string; report_age_h: number | null };

export type Src = {
  id: string;
  name: string;
  url: string;
  state: string;
  last_ok: string | null;
  failures_in_row: number;
  last_useful_discovery: string;
  candidates: number;
  noise_rate: number | null;
  early_share: number | null;
  last_error: string;
  /** the diagnosis (`diagnose`); the old `bridge_job` is retired (c) */
  repair?: { cause: string; suggestion: string; external?: boolean };
};
export type NewsSrcHealth = {
  evaluated_at?: string | null;
  benchmark_events?: number | null;
  feeds_healthy?: number;
  feeds_failing?: string[];
  degraded?: string[];
  probation?: string[];
  candidates?: string[];
  sources?: number;
  error?: string;
};
export type Job = {
  id: string;
  label: string;
  interval_h: number;
  last_ok: string | null;
  next_due: string;
  overdue: boolean;
  state: string;
  last_note: string;
  outcome?: string | null;
  outcome_label?: string;
  source?: string;
  seconds?: number | null;
  fails_in_row?: number;
  error?: string;
};
export type Runner = { at?: string; finished?: string | null; outcome?: string; note?: string; ran?: number; failed?: number; seconds?: number };
export type Lock = { held: boolean; alive?: boolean; source?: string; pid?: number; since?: string; age_h?: number | null; suspect?: boolean };
export type JobRunner = {
  /** a pid lock file in the old app: deferred (d) */
  lock: Maybe<Lock>;
  runners: Record<string, Runner>;
  outcomes?: Record<string, string>;
};
export type Build = { version: string; commit: string; started_at: string; ui_stale: boolean; note: string; frontend: { built_at?: string; commit?: string } };
export type SelfCheck = { at: string | null; running: boolean; ok: number; total: number; degraded: Array<{ name: string; why: string; impact: string; recovery: string }> };
export type Health = {
  at?: string;
  verdict: "HEALTHY" | "FYI — EXTERNAL LIMITATIONS" | "NEEDS ATTENTION" | "DEGRADED" | "UNHEALTHY";
  status?: OverallStatus;
  issues: Issue[];
  sources: { sources: Src[]; counts: Record<string, number>; rule: string; stale_days: number };
  coverage: {
    available: boolean;
    counts?: Record<string, number>;
    priority?: Array<{ city: string; overall: string; families: Record<string, string | null> }>;
    family_labels?: Record<string, string>;
  };
  triage_pending: number;
  research: Record<string, number>;
  /** the watch sensors are not ported: `failing_checks` is deferred (d) */
  watch: { companies: number; open_triggers: number; failing_checks: Maybe<number> };
  jobs: Job[];
  overdue: number;
  job_runner?: JobRunner;
  spend: { day: number; week: number; month: number; limits: Record<string, number>; kill_switch: string | null };
  providers: Array<{ role: string; provider: string; model: string; enabled: boolean; key: boolean | null }>;
  last_scan: string;
  news?: {
    last_run: { at: string; status?: string; completed_at?: string; sources_ok: number; sources_failed: string[]; new: number; merged: number; duplicates_skipped: number; usd: number } | null;
    events: number;
    backcasts_pending: number;
    usd_total: number;
    error?: string;
    sources?: NewsSrcHealth;
  };
  build?: Maybe<Build>;
  selfcheck?: Maybe<SelfCheck>;
  /** the source network (032b): deferred (d); the page never read it */
  source_discovery?: Maybe<Record<string, unknown>>;
  validation: { snapshots: number; last_snapshot: string | null; data_issues: number };
};

export type Run = { at: string; job: string; label: string; state: string; seconds: number | null; note: string; source: string };
export type ModelRow = {
  model: string;
  provider: string;
  roles: string[];
  calls: number;
  ok: number;
  errors: number;
  cache_hits: number;
  blocked: number;
  usd: number;
  last_ok: string;
  last_error: string;
  error_kinds: Record<string, number>;
  calls_7d: number;
  ok_7d: number;
  p50_ms_7d: number | null;
};
export type BackupItem = { name: string; bytes: number; at: string | null; checksum: boolean; restore_ok: boolean | null; restore_at: string | null };
export type Backups = { count: number; latest: BackupItem | null; last_verified: BackupItem | null; dir: string };
export type Integrity = { status: string; files_checked: number | null; checked_at: string | null; issues: number };
export type Release = { at: string; tag: string; commit: string };
export type Overview = {
  at: string;
  jobs: { days: number; runs: Run[]; outcomes_recorded_since: string | null };
  models: { rows: ModelRow[]; spend_by_day: Record<string, Record<string, number>> };
  /** without the retired `intake` count (c) */
  pipeline: { inbox: Record<string, number>; routing: { counts: Record<string, number>; at: string | null }; conviction: Record<string, number>; manager_sent: number };
  /** 032b: deferred (d) */
  backups: Maybe<Backups>;
  integrity: Maybe<Integrity>;
  releases: Maybe<Release[]>;
};
