-- Review 037a: WATCH, part 1 — the watched companies' official pages and the trigger log.
--
-- The old app kept `watch/targets.json` (`{"targets": {<norm_company(name)>: record}}`) and appended one line per fired
-- trigger and per acknowledgement to `watch/triggers.jsonl` (`json.dumps(row, sort_keys=True)`). The imported files
-- stay the base (`documents` / `legacy_documents`); nothing is backfilled. The readers OVERLAY these rows on them:
--
-- * watch_targets: ONE row per company key (the old dict key, `norm_company(name)`), holding the WHOLE old record as
--   `json` (key order kept: name, added_at, checks, urls, candidate_id, active, updated_at). A row wins over the
--   imported target of the same key; keys only in rows follow the imported ones in `ord` order (the old dict order).
--   A save rewrites the record (the old merge, done by the app under its one write lock); a row is never deleted
--   (`active: false` stops watching, as before).
-- * watch_events: append-only (UPDATE and DELETE refused). ONE row per old line: `kind` trigger | status, `line` the
--   old line as `json` (sorted keys, byte-kept), `trigger_id` the trigger's own id or the acknowledged one.
--   `dedupe_key` is the trigger's content key, UNIQUE among the trigger rows (a status row has none); the archived
--   lines' keys are checked by the writer (037b). Read after the archived lines, `order by seq`.
-- The write lock key is derived from the schema name at run time; no lock or setting here names the schema.
create table pz.watch_targets (
  key               text primary key check (key <> ''),
  record            json not null check (json_typeof(record) = 'object'),
  ord               bigint generated always as identity,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create trigger watch_targets_no_delete before delete on pz.watch_targets
  for each row execute function pz.forbid_mutation();

create table pz.watch_events (
  seq               bigint generated always as identity primary key,
  kind              text not null check (kind in ('trigger', 'status')),
  trigger_id        text not null check (trigger_id <> ''),
  dedupe_key        text,
  line              json not null check (json_typeof(line) = 'object'),
  recorded_at       timestamptz not null default now(),
  constraint watch_events_dedupe_check check ((kind = 'trigger') = (dedupe_key is not null and dedupe_key <> ''))
);
create unique index watch_events_one_trigger_per_dedupe on pz.watch_events (dedupe_key) where kind = 'trigger';
create index watch_events_trigger_idx on pz.watch_events (trigger_id, seq);
create trigger watch_events_no_update before update on pz.watch_events
  for each row execute function pz.forbid_mutation();
create trigger watch_events_no_delete before delete on pz.watch_events
  for each row execute function pz.forbid_mutation();

alter table pz.watch_targets enable row level security;
alter table pz.watch_events enable row level security;
revoke all on pz.watch_targets from public, anon, authenticated;
revoke all on pz.watch_events from public, anon, authenticated;
