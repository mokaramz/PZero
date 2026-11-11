-- Review 016: the Events writes.
--
-- 1. Every Events write (save / merge / verify / lead decision / lead conversion / debrief / Scout 00 add) is one
--    append-only `event_history` row, written in the SAME transaction as the current record (`attrs.record`) and its
--    mirrored columns, so a refused or failed write leaves no row behind. Exactly one target: an event or a lead.
--    Exception (documented): a Scout 00 report marked Monitor / Ignore has neither; its audit is the locked report's
--    own `history` in documents['scout_intake.json#rest'], as in the old app.
-- 2. Debrief startup leads enter Deal Flow through intake as a trusted batch with the server-side origin
--    'event_debrief': the origin vocabulary of intake_submissions gains it (a superset: no stored row changes).
create table pz.event_history (
  id                bigint generated always as identity primary key,
  event_id          text references pz.events (id) on delete cascade,
  lead_id           text references pz.event_leads (id) on delete cascade,
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('create', 'save', 'merge', 'verify', 'lead_decision',
                                                    'convert', 'debrief', 'scout_add')),
  before            jsonb,                                -- changed fields before the write (null on create)
  after             jsonb not null,                       -- the same fields after it (the whole record on create)
  detail            jsonb not null default '{}',          -- request fields, merged-into, lead / report ids, ...
  at                timestamptz not null default now(),
  constraint event_history_one_target check ((event_id is null) <> (lead_id is null))
);
create index event_history_event_idx on pz.event_history (event_id, at desc) where event_id is not null;
create index event_history_lead_idx on pz.event_history (lead_id, at desc) where lead_id is not null;
create trigger event_history_append_only before update or delete on pz.event_history
  for each row execute function pz.forbid_mutation();

alter table pz.event_history enable row level security;
revoke all on pz.event_history from public, anon, authenticated;

alter table pz.intake_submissions drop constraint intake_submissions_origin_check;
alter table pz.intake_submissions add constraint intake_submissions_origin_check
  check (origin in ('grok', 'registry_scan', 'manual', 'research', 'event_debrief',
                    'legacy_scout00', 'legacy_native', 'legacy_dealflow'));
