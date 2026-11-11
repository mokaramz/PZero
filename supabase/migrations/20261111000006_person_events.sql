-- Review 013: every Network people write (add, edit / follow-up / log contact / judgment, the "3 most talented"
-- ritual, the Watchlist signal log) is one append-only event row: who, what, and the fields it changed
-- (before -> after). It is written in the SAME transaction as the person's current record (`people.attrs.record`),
-- its typed columns and its `person_identifiers`, so a refused or failed write leaves no event behind.
--
-- A dedicated table (not Conviction's): `conviction_events` references a UUID entry and has its own actions, while a
-- person's key is the text id kept from the old app ('p-<slug>').
create table pz.person_events (
  id                bigint generated always as identity primary key,
  person_id         text not null references pz.people (id) on delete cascade,
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('create', 'save', 'talented', 'watch_log')),
  before            jsonb,                                -- changed fields before the write (null on create)
  after             jsonb not null,                       -- the same fields after it (the whole record on create)
  detail            jsonb not null default '{}',          -- request fields, the ritual's introducer, ...
  at                timestamptz not null default now()
);
create index person_events_person_idx on pz.person_events (person_id, at desc);
create trigger person_events_append_only before update or delete on pz.person_events
  for each row execute function pz.forbid_mutation();

alter table pz.person_events enable row level security;
revoke all on pz.person_events from public, anon, authenticated;
