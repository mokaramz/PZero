-- Review 037b: WATCH, part 2 — the official-page checks' baselines and the scheduled check's resume point.
--
-- * watch_page_snapshots: the last seen lines of each watched page, keyed by the old snapshot id
--   `wt-<sha1(entity_key|url)[:12]>` (the old `.watch/wt-<id>.json`). Nothing is backfilled: a check resolves a page's
--   baseline AT CHECK TIME from its row, else from the archived `.watch/wt-<id>.json` in legacy_documents, else none
--   (a first check, which only records the baseline); so the order of migration and import never matters. A row is
--   written only by a check's write phase, together with that page's triggers and check record (one transaction).
-- * watch_check_state: ONE row (id = true), the page the next scheduled check starts at (the company key and the
--   URL; both null: start at the first page). A check that ends at its deadline sets it to the page AFTER the last
--   page it reached; a check that reaches every page clears it. `job_runs` counts the scheduled checks that finished
--   (the background-jobs runner's occurrence of `watch_checks`).
-- The check's lock keys are derived from the schema name at run time; no lock or setting here names the schema.
create table pz.watch_page_snapshots (
  id                text primary key check (id ~ '^wt-[0-9a-f]{12}$'),  -- the old `.watch/<id>.json` stem
  entity_key        text not null check (entity_key <> ''),             -- the watched company's key
  url               text not null check (url <> ''),                    -- the page the lines were read from
  lines             jsonb not null check (jsonb_typeof(lines) = 'array'),
  updated_at        timestamptz not null default now()
);

create table pz.watch_check_state (
  id                boolean primary key default true check (id),
  resume_key        text,
  resume_url        text,
  job_runs          bigint not null default 0 check (job_runs >= 0),
  updated_at        timestamptz not null default now(),
  constraint watch_check_state_resume_check check ((resume_key is null) = (resume_url is null))
);
create trigger watch_check_state_no_delete before delete on pz.watch_check_state
  for each row execute function pz.forbid_mutation();

alter table pz.watch_page_snapshots enable row level security;
alter table pz.watch_check_state enable row level security;
revoke all on pz.watch_page_snapshots, pz.watch_check_state from public, anon, authenticated;
