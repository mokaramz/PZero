-- Review 011: every Conviction write (create, save / checklist, status) is one append-only event row: who, what, and
-- the fields it changed (before -> after). A Keep also writes its candidate status event to pz.candidate_events (with
-- the feedback snapshot the ledger replays, review 008); this table is for the entry itself, which candidate_events
-- can't hold (legacy entries have no candidate, and an entry's own fields are not candidate history).
create table pz.conviction_events (
  id                bigint generated always as identity primary key,
  entry_id          uuid not null references pz.conviction_entries (id) on delete cascade,
  slug              text not null,                        -- the entry's slug when the event was written
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('create', 'save', 'status')),
  before            jsonb,                                -- changed fields before the write (null on create)
  after             jsonb not null,                       -- the same fields after it (the whole record on create)
  detail            jsonb not null default '{}',          -- request fields, Keep link, IMQ transition, ...
  at                timestamptz not null default now()
);
create index conviction_events_entry_idx on pz.conviction_events (entry_id, at desc);
create trigger conviction_events_append_only before update or delete on pz.conviction_events
  for each row execute function pz.forbid_mutation();

alter table pz.conviction_events enable row level security;
revoke all on pz.conviction_events from public, anon, authenticated;
