-- Review 034a: the Deal Flow scan (Find New Candidates, the scan report, the scan history).
--
-- The old scan wrote `inbox.json` (`report`, `last_run`, `last_summary`), `scan_history.json` (the last 60 scans) and
-- the page-watcher baselines `.watch/<uid(url)>.json`. Candidates go through the intake (decision a); here:
--
-- * scan_runs: ONE row per run, append-only (UPDATE and DELETE refused). `summary` is the old `last_summary`,
--   `report` the old `inbox.report` (the per-source rows and the system rows) and `sources` the old history entry's
--   per-source rows, kept as `json` (not jsonb) so the old key order survives. The readers OVERLAY these rows on the
--   imported `scan_history.json` / `inbox.json#rest`; nothing is backfilled (the archive stays the base).
-- * scan_watch_snapshots: the last seen lines of each watched URL, keyed by the old file's stem `uid(url)`. Nothing is
--   backfilled either (revision 2): the scan resolves a URL's baseline AT SCAN TIME from its row, else from the
--   archived `.watch/<uid>.json` in legacy_documents, else none (a first run); so the order of migration and import
--   never matters. A row is written only by a scan's write phase.
-- The scan's lock keys are derived from the schema name at run time; no string here names the schema.
create table pz.scan_runs (
  id                bigint generated always as identity primary key,
  run_id            text not null unique,                 -- the old run id ('2026-11-13 09:00:00', ' #2' on a clash)
  started_at        timestamptz not null,                 -- the old `scan_started` (the write phase's start)
  finished_at       timestamptz not null,
  days              integer,                              -- the `days` asked for (the old `/api/find {days}`)
  trigger           text not null default 'app' check (trigger ~ '^[a-z][a-z_]{0,31}$'),
  summary           json not null check (json_typeof(summary) = 'object'),
  report            json not null check (json_typeof(report) = 'array'),
  sources           json not null check (json_typeof(sources) = 'array'),
  created_at        timestamptz not null default now(),
  constraint scan_runs_finished_check check (finished_at >= started_at)
);
create trigger scan_runs_no_update before update on pz.scan_runs
  for each row execute function pz.forbid_mutation();
create trigger scan_runs_no_delete before delete on pz.scan_runs
  for each row execute function pz.forbid_mutation();

create table pz.scan_watch_snapshots (
  uid               text primary key check (uid ~ '^[0-9a-f]{12}$'),  -- the old `.watch/<uid>.json` stem
  url               text not null,                        -- the page the lines were read from
  source_id         text,                                 -- the source that last scanned it
  lines             jsonb not null check (jsonb_typeof(lines) = 'array'),
  seeded_from       text,                                 -- the archived `.watch/` path the first baseline came from
  run_id            text,                                 -- the run that wrote it
  updated_at        timestamptz not null default now()
);

alter table pz.scan_runs enable row level security;
alter table pz.scan_watch_snapshots enable row level security;
revoke all on pz.scan_runs, pz.scan_watch_snapshots from public, anon, authenticated;
