-- Review 017: the event source scan.
--
-- 1. A page watcher compares a source page's visible lines with its last successful baseline. The old app kept the
--    baselines as files (`.watch/ev-<uid(url)>.json`, archived byte-exact in legacy_documents by the import, decision
--    014 G12). They are live state now: one row per watcher source, keyed by the stable source id. A source with no
--    row is seeded ONCE from its archived file (when there is one); an empty baseline is a baseline; a failed fetch
--    never replaces the last good one (Codex H-113).
-- 2. The scan writes through the Events write model: its history rows get their own actions.
create table pz.event_watch_snapshots (
  source_id         text primary key,                     -- the registry's stable source id ('ev-stationf', ...)
  url               text not null,                        -- the page the baseline was taken from
  lines             jsonb not null check (jsonb_typeof(lines) = 'array'),
  seeded_from       text,                                 -- the archived .watch/ path it was first taken from, if any
  updated_at        timestamptz not null default now()
);
alter table pz.event_watch_snapshots enable row level security;
revoke all on pz.event_watch_snapshots from public, anon, authenticated;

alter table pz.event_history drop constraint event_history_action_check;
alter table pz.event_history add constraint event_history_action_check
  check (action in ('create', 'save', 'merge', 'verify', 'lead_decision', 'convert', 'debrief', 'scout_add',
                    'scan_create', 'scan_merge', 'scan_lead'));
