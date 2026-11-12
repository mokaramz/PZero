-- Review 028b: News & Learning, part 2 (the writes, no network). The old news/events.json and news/actions.jsonl as
-- tables, plus an append-only history of every change to an event.
--
-- * news_events: one row per event. `pos` is the event's position in the archived `events` object, the order that
--   decides merges and ties; `record` is the current event, stored as `json` (not JSONB) so its own key order is kept;
--   `legacy` is the imported record.
-- * news_events_rest: the events document without its events (the `seeded` list and any other top-level key), as
--   `json` in the archived key order, with `events` kept as a null placeholder at its original position.
-- * news_actions: the old action lines, append-only, exactly as 0018's validation_log (an archived line as it was, a
--   new one as the old code wrote it; a line text cannot hold is NULL at its position; imports precede live rows).
-- * news_event_history: one append-only row per change to an event (a curated case seeded, a backcast signal).
create table pz.news_events (
  event_id          text primary key check (event_id <> ''),
  pos               integer not null unique,
  record            json not null,
  legacy            json,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create table pz.news_events_rest (
  singleton         boolean primary key default true check (singleton),
  body              json not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create table pz.news_actions (
  seq               bigint generated always as identity primary key,
  line              text,                                 -- NULL: an archived line text cannot hold (a NUL byte)
  source            text not null check (source in ('import', 'app')),
  archive_line      integer,
  created_at        timestamptz not null default now(),
  constraint news_actions_archive_line_check check (
    (source = 'import' and archive_line is not null and archive_line > 0)
    or (source = 'app' and archive_line is null)
  ),
  constraint news_actions_line_check check (line is not null or source = 'import')
);
create unique index news_actions_import_idx on pz.news_actions (archive_line) where source = 'import';
create table pz.news_event_history (
  id                bigint generated always as identity primary key,
  event_id          text not null,
  action            text not null check (action in ('seed', 'backcast')),
  before            json,                                 -- the record before (null when new)
  after             json not null,
  detail            jsonb not null default '{}',
  at                timestamptz not null default now()
);
create index news_event_history_event_idx on pz.news_event_history (event_id, id);
create trigger news_actions_append_only before update or delete on pz.news_actions
  for each row execute function pz.forbid_mutation();
create trigger news_event_history_append_only before update or delete on pz.news_event_history
  for each row execute function pz.forbid_mutation();
alter table pz.news_events enable row level security;
alter table pz.news_events_rest enable row level security;
alter table pz.news_actions enable row level security;
alter table pz.news_event_history enable row level security;
revoke all on pz.news_events, pz.news_events_rest, pz.news_actions, pz.news_event_history
  from public, anon, authenticated;

-- The one mapping, shared by this migration (schemas imported before 0019) and the importer (right after the
-- archives). The events come from the byte-exact archive first (pz.archived_json: an optional BOM skipped), else from
-- the imported `documents['news/events.json']` row (whose key order is JSONB's: the order those installations already
-- read). A malformed document raises and writes nothing. Repeatable: events and the rest row are inserted only when
-- absent, so a rerun keeps an edited event, the persisted `seeded` list and the history; action lines follow 0018's
-- rules (identity by archive line; a rerun adds nothing; once a live row exists, a missing archived line is refused).
create function pz.backfill_news() returns integer
language plpgsql as $$
declare
  doc json;
  bad text;
  written integer := 0;
  n integer;
  missing integer;
  first_missing integer;
  last_imported integer;
begin
  doc := pz.archived_json('news/events.json');
  if doc is null then
    select d.body::json into doc from pz.documents d where d.key = 'news/events.json';
  end if;
  if doc is not null then
    if json_typeof(doc) <> 'object' then
      raise exception 'news/events.json: the top level must be an object';
    end if;
    if doc -> 'events' is not null and json_typeof(doc -> 'events') <> 'object' then
      raise exception 'news/events.json: "events" must be an object keyed by event id';
    end if;
    select string_agg(e.key, ', ') into bad from json_each(coalesce(doc -> 'events', '{}'::json)) as e(key, value)
    where e.key = '' or json_typeof(e.value) <> 'object';
    if bad is not null then
      raise exception 'news/events.json: events % are not records keyed by a non-empty id', bad;
    end if;
    select string_agg(k, ', ') into bad from (select e.key as k from json_each(coalesce(doc -> 'events', '{}'::json))
                                              as e(key, value) group by 1 having count(*) > 1) as dup;
    if bad is not null then
      raise exception 'news/events.json: event ids repeated: %', bad;
    end if;
    insert into pz.news_events (event_id, pos, record, legacy)
    select e.key, (e.ord - 1)::integer, e.value, e.value
    from json_each(coalesce(doc -> 'events', '{}'::json)) with ordinality as e(key, value, ord)
    on conflict (event_id) do nothing;
    get diagnostics n = row_count; written := written + n;
    insert into pz.news_events_rest (body)
    select coalesce(json_object_agg(t.key, case when t.key = 'events' then null else t.value end order by t.ord),
                    '{}'::json)
    from json_each(doc) with ordinality as t(key, value, ord)
    on conflict (singleton) do nothing;
  end if;

  select count(*), min(a.pos) into missing, first_missing
  from pz.archived_lines('news/actions.jsonl') a
  where not exists (select 1 from pz.news_actions l where l.source = 'import' and l.archive_line = a.pos);
  if missing > 0 then
    if exists (select 1 from pz.news_actions l where l.source = 'app') then
      raise exception 'news/actions.jsonl: % archived line(s) are not imported and the log already has live rows', missing;
    end if;
    select max(l.archive_line) into last_imported from pz.news_actions l where l.source = 'import';
    if last_imported is not null and first_missing < last_imported then
      raise exception 'news/actions.jsonl: archived line % is missing before imported line %', first_missing, last_imported;
    end if;
    insert into pz.news_actions (line, source, archive_line)
    select a.line, 'import', a.pos
    from pz.archived_lines('news/actions.jsonl') a
    where not exists (select 1 from pz.news_actions l where l.source = 'import' and l.archive_line = a.pos)
    order by a.pos;
    get diagnostics n = row_count; written := written + n;
  end if;
  return written;
end;
$$;
revoke all on function pz.backfill_news() from public, anon, authenticated;

select pz.backfill_news();
