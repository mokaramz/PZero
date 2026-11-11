-- Review 014: an event's dates as the old app read them, and the event leads.
--
-- The old app stored `start` / `end` as text and read them with `parse_when` (a calendar date, an optional 'HH:MM'
-- Berlin wall-clock time) and `event_span` (a date-only event covers its whole day; the end is EXCLUSIVE). The importer
-- had squeezed both into `starts_at` / `ends_at`, so a date-only end read as the midnight that STARTS that day and a
-- stated time could not be told from midnight. Now:
--   * `start_date` / `end_date` (date) and `start_time` / `end_time` ('HH:MM', NULL = no time stated) are the dates as
--     stated (Berlin wall clock; an offset time is converted, as the old app did);
--   * `starts_at` / `ends_at` stay as the derived instants: `starts_at` = the start (Berlin midnight for a date-only
--     start), `ends_at` = the exclusive end of the old `event_span` (a date-only end -> the next Berlin midnight; no
--     end -> the end of the start day). There is a span exactly when there is a start date.
-- `pz.event_leads` holds the old `events.json` leads (until now an un-modelled `events.json#rest` document).
--
-- ONE statement, so it is atomic however the runner wraps it (like 0003 / 0005): the ACCESS EXCLUSIVE lock is taken
-- BEFORE the emptiness check and held through the change. The new columns can't be derived in SQL from rows written
-- under the old meaning of `ends_at`, so the migration refuses to run over existing events rather than invent dates.
-- The live table is empty (the import has not run).
do $$
begin
  lock table pz.events in access exclusive mode;
  if exists (select 1 from pz.events) then
    raise exception 'events is not empty: re-import the events (their dates cannot be derived here) before applying this migration';
  end if;

  alter table pz.events
    add column start_date date,
    add column start_time text,
    add column end_date   date,
    add column end_time   text,
    add constraint events_start_time_is_hhmm check (start_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
    add constraint events_end_time_is_hhmm check (end_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'),
    add constraint events_time_needs_a_date check ((start_time is null or start_date is not null)
                                                   and (end_time is null or end_date is not null)),
    add constraint events_span_iff_start check ((start_date is null) = (starts_at is null)
                                                and (starts_at is null) = (ends_at is null)),
    add constraint events_span_is_forward check (ends_at > starts_at);
  create index events_start_date_idx on pz.events (start_date);

  create table pz.event_leads (
    id                text primary key,                     -- legacy 'evlead-…' kept
    title             text,
    source            text,
    url               text,
    city              text,
    type              text,
    lead_date         date,                                 -- the old parse_when of `date_raw`
    date_raw          text,                                 -- the date as stated
    confidence        text,
    detected_on       date,
    decision          text not null default 'new' check (decision in ('new', 'dismissed', 'converted')),
    note              text,
    attrs             jsonb not null default '{}',
    legacy            jsonb,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
  );
  create index event_leads_open_idx on pz.event_leads (lead_date) where decision = 'new';
  create trigger event_leads_touch before update on pz.event_leads
    for each row execute function pz.touch_updated_at();
  alter table pz.event_leads enable row level security;
  revoke all on pz.event_leads from public, anon, authenticated;
end $$;

comment on column pz.events.starts_at is
  'derived: the start instant (Berlin midnight for a date-only start); NULL exactly when start_date is NULL';
comment on column pz.events.ends_at is
  'derived, EXCLUSIVE: the old event_span end (date-only end -> next Berlin midnight; no end -> end of the start day)';
comment on column pz.events.start_time is 'HH:MM Berlin wall clock as stated; NULL = no time stated';
comment on column pz.events.end_time is 'HH:MM Berlin wall clock as stated; NULL = no time stated';
