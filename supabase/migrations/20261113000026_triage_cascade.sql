-- Review 035b: machine triage, part 2 — the cascade's runs, the post-scan auto-triage records, the per-candidate
-- dispositions and the retry state.
--
-- The old app wrote `triage_proposals.json` (`proposals{}` and a `runs[]` summary per runner run),
-- `shadow_triage/auto_runs.json` (the last 30 automatic runs) and `shadow_triage/retry_state.json` (per candidate:
-- attempts, reason, when it may be retried). The imported files stay the base (documents / legacy_documents); nothing
-- is backfilled. The readers OVERLAY these rows on them:
--
-- * triage_proposals (core schema) gains writers: each candidate's result is ONE transaction that clears the
--   previous current row, then inserts the new current one (the partial unique index holds at every statement).
-- * triage_runs: ONE row per runner run, append-only (UPDATE and DELETE refused). `summary` is the old `runs[]`
--   entry, kept as `json` (not jsonb) so its key order survives. Read after the imported `#rest` runs.
-- * triage_auto_runs: ONE row per automatic run (after a scan, the hourly retry, Retry now). `record` is the old
--   auto-run record (`json`, key order kept), written while the run goes and frozen once it is finished (a finished
--   row refuses UPDATE; no row is ever deleted). `selection` is the run's selected ids with each one's SELECTION MARK
--   (the highest `triage_decisions.seq` of that survivor at selection, 0 without one), in selection order. At most
--   one row is `running`. Read after the imported `auto_runs.json` runs (the last 30 together).
-- * triage_run_items: ONE row per selected candidate and run: its disposition (proposed / needs_human / error /
--   decided_meanwhile / changed_meanwhile / unchanged_skipped), written in the SAME transaction as that candidate's
--   locked eligibility check and its effect; append-only. Recovery of an interrupted run reads these.
-- * triage_retry_state: ONE row per candidate (the old entry as `json`, plus `cleared`: the old `rs.pop`), written
--   in the same transaction as the result that set or cleared it. `ord` is the old dict order (a re-added entry
--   moves to the end, `moved`).
-- The triage run lock key is derived from the schema name at run time; no lock or setting here names the schema.
create table pz.triage_runs (
  id                bigint generated always as identity primary key,
  run_id            text not null unique check (run_id ~ '^triage-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$'),
  finished_at       timestamptz not null,
  summary           json not null check (json_typeof(summary) = 'object'),
  created_at        timestamptz not null default now()
);
create trigger triage_runs_no_update before update on pz.triage_runs
  for each row execute function pz.forbid_mutation();
create trigger triage_runs_no_delete before delete on pz.triage_runs
  for each row execute function pz.forbid_mutation();

create table pz.triage_auto_runs (
  id                bigint generated always as identity primary key,
  scan_run_id       text not null,                        -- the old key: the scan's run id, or 'retry <ts>' / 'retry-now <ts>'
  kind              text not null check (kind in ('scan', 'retry', 'retry_now')),
  triage_run_id     text unique check (triage_run_id ~ '^triage-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$'),
  state             text not null check (state in ('running', 'done', 'partial', 'failed')),
  selection         json not null default '[]' check (json_typeof(selection) = 'array'),
  record            json not null check (json_typeof(record) = 'object'),
  started_at        timestamptz not null,
  finished_at       timestamptz,
  updated_at        timestamptz not null default now(),
  constraint triage_auto_runs_finished_check check ((state = 'running') = (finished_at is null))
);
create unique index triage_auto_runs_one_running on pz.triage_auto_runs ((true)) where state = 'running';

create or replace function pz.triage_auto_run_frozen() returns trigger language plpgsql as $$
begin
  if old.state <> 'running' then
    raise exception 'pz.%: a finished automatic triage run is frozen (% refused)', tg_table_name, tg_op;
  end if;
  if new.scan_run_id <> old.scan_run_id or new.kind <> old.kind or new.started_at <> old.started_at
     or new.selection::text <> old.selection::text
     or new.triage_run_id is distinct from old.triage_run_id then
    raise exception 'pz.%: the run''s identity and selection never change (% refused)', tg_table_name, tg_op;
  end if;
  new.updated_at := now();
  return new;
end $$;
create trigger triage_auto_runs_frozen before update on pz.triage_auto_runs
  for each row execute function pz.triage_auto_run_frozen();
create trigger triage_auto_runs_no_delete before delete on pz.triage_auto_runs
  for each row execute function pz.forbid_mutation();

create table pz.triage_run_items (
  id                bigint generated always as identity primary key,
  triage_run_id     text not null references pz.triage_auto_runs (triage_run_id),
  candidate_id      text not null references pz.candidates (id),
  disposition       text not null check (disposition in ('proposed', 'needs_human', 'error', 'decided_meanwhile',
                                                         'changed_meanwhile', 'unchanged_skipped')),
  detail            json not null default '{}' check (json_typeof(detail) = 'object'),
  at                timestamptz not null default now(),
  constraint triage_run_items_once unique (triage_run_id, candidate_id)
);
create trigger triage_run_items_no_update before update on pz.triage_run_items
  for each row execute function pz.forbid_mutation();
create trigger triage_run_items_no_delete before delete on pz.triage_run_items
  for each row execute function pz.forbid_mutation();

create table pz.triage_retry_state (
  candidate_id      text primary key references pz.candidates (id),
  ord               bigint generated by default as identity, -- the old dict order (re-added after a clear: a new value)
  entry             json not null check (json_typeof(entry) = 'object'),
  cleared           boolean not null default false,
  moved             boolean not null default false,       -- re-added after a clear (it went to the end of the dict)
  updated_at        timestamptz not null default now()
);
create trigger triage_retry_state_no_delete before delete on pz.triage_retry_state
  for each row execute function pz.forbid_mutation();

alter table pz.triage_runs enable row level security;
alter table pz.triage_auto_runs enable row level security;
alter table pz.triage_run_items enable row level security;
alter table pz.triage_retry_state enable row level security;
revoke all on pz.triage_runs, pz.triage_auto_runs, pz.triage_run_items, pz.triage_retry_state
  from public, anon, authenticated;
