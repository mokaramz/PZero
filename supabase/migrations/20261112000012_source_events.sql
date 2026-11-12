-- Review 021: the Deal Flow source registry's on/off toggle is one append-only event per change (before -> after).
-- The current record of a source is attrs.record once written (else the imported legacy record); it holds only the
-- imported counter baseline: the counters since the import are derived from candidate and Conviction events on read.
create table pz.source_events (
  id                bigint generated always as identity primary key,
  source_id         text not null references pz.sources (id),
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('toggle')),
  before            jsonb not null,                       -- {enabled}
  after             jsonb not null,                       -- {enabled}
  detail            jsonb not null default '{}',
  at                timestamptz not null default now()
);
create index source_events_source_idx on pz.source_events (source_id, at desc);
create trigger source_events_append_only before update or delete on pz.source_events
  for each row execute function pz.forbid_mutation();
alter table pz.source_events enable row level security;
revoke all on pz.source_events from public, anon, authenticated;
