-- Review 024: the Active Evaluator (the old evaluations.json {sessions: {<id>: session}}, an id-keyed OBJECT) as one
-- ORDERED record table and one append-only event table. pos is the session's position in the object, from the
-- BYTE-EXACT archive (json keeps key order, JSONB does not; Codex H-183), exactly as 0014. The current record is
-- attrs.record; legacy keeps the imported one. Ending a session also writes Conviction: its two new event actions.
create table pz.eval_sessions (
  id                text primary key check (id <> ''),
  pos               integer not null unique,
  status            text,                                 -- open | ended (as recorded)
  subject_kind      text,                                 -- company | external
  subject_name      text,
  attrs             jsonb not null default '{}',          -- {record: the current session}
  legacy            jsonb,
  created_at        timestamptz not null default now()
);
create table pz.eval_events (
  id                bigint generated always as identity primary key,
  session_id        text not null references pz.eval_sessions (id),
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('start', 'deck', 'next', 'skip', 'answer', 'evidence', 'resolve', 'end')),
  before            jsonb,                                -- the session before (null on start)
  after             jsonb not null,                       -- the session after
  detail            jsonb not null default '{}',          -- the request (ids), refused flag
  at                timestamptz not null default now()
);
create index eval_events_session_idx on pz.eval_events (session_id, at desc);
create trigger eval_events_append_only before update or delete on pz.eval_events
  for each row execute function pz.forbid_mutation();
alter table pz.eval_sessions enable row level security;
alter table pz.eval_events enable row level security;
revoke all on pz.eval_sessions, pz.eval_events from public, anon, authenticated;

alter table pz.conviction_events drop constraint conviction_events_action_check;
alter table pz.conviction_events add constraint conviction_events_action_check
  check (action in ('create', 'save', 'status', 'radar_milestone', 'evaluator_end', 'imq_trigger'));

-- A database that applied 0014 as first committed (3470852) has neither the BOM-tolerant archive reader nor the
-- founder-calls backfill that uses it (Codex H-197): install / refresh both here; on a chain that ran the
-- corrected 0014 this replaces them with identical definitions.
-- The byte-exact archive as json (key order kept), with the optional leading UTF-8 BOM the importer accepts
-- (`utf-8-sig`) skipped, so the preview, the backfills and the readers agree (Codex H-192). The archived bytes are
-- never changed. NULL when the path is not archived.
create or replace function pz.archived_json(archive_path text) returns json
language sql stable as $$
  select convert_from(case when substring(d.raw from 1 for 3) = '\xefbbbf'::bytea then substring(d.raw from 4)
                           else d.raw end, 'UTF8')::json
  from pz.legacy_documents d where d.path = archive_path
$$;
revoke all on function pz.archived_json(text) from public, anon, authenticated;

create or replace function pz.backfill_founder_calls() returns integer
language plpgsql as $$
declare
  doc json;
  bad text;
  coll text;
  written integer := 0;
  n integer;
begin
  doc := pz.archived_json('founder_calls.json');
  if doc is null then
    return 0;
  end if;
  if json_typeof(doc) <> 'object' then
    raise exception 'founder_calls.json: the top level must be an object';
  end if;
  foreach coll in array array['companies', 'founders', 'calls'] loop
    if doc -> coll is not null and json_typeof(doc -> coll) <> 'object' then
      raise exception 'founder_calls.json: "%" must be an object keyed by id', coll;
    end if;
    select string_agg(e.key, ', ') into bad from json_each(coalesce(doc -> coll, '{}'::json)) as e(key, value)
    where e.key = '' or json_typeof(e.value) <> 'object'
       or (e.value -> 'id' is not null and (json_typeof(e.value -> 'id') <> 'string' or e.value ->> 'id' <> e.key));
    if bad is not null then
      raise exception 'founder_calls.json: % records % are not records keyed by their own id', coll, bad;
    end if;
    select string_agg(k, ', ') into bad from (select e.key as k from json_each(coalesce(doc -> coll, '{}'::json)) as e(key, value)
                                              group by 1 having count(*) > 1) as dup;
    if bad is not null then
      raise exception 'founder_calls.json: % ids repeated: %', coll, bad;
    end if;
  end loop;
  insert into pz.fc_companies (id, pos, name, attrs, legacy)
  select e.key, (e.ord - 1)::integer,
         case when json_typeof(e.value -> 'name') = 'string' then e.value ->> 'name' end,
         jsonb_build_object('record', e.value::jsonb), e.value::jsonb
  from json_each(coalesce(doc -> 'companies', '{}'::json)) with ordinality as e(key, value, ord)
  on conflict (id) do nothing;
  get diagnostics n = row_count; written := written + n;
  insert into pz.fc_founders (id, pos, name, company_id, attrs, legacy)
  select e.key, (e.ord - 1)::integer,
         case when json_typeof(e.value -> 'name') = 'string' then e.value ->> 'name' end,
         case when json_typeof(e.value -> 'company_id') = 'string' then e.value ->> 'company_id' end,
         jsonb_build_object('record', e.value::jsonb), e.value::jsonb
  from json_each(coalesce(doc -> 'founders', '{}'::json)) with ordinality as e(key, value, ord)
  on conflict (id) do nothing;
  get diagnostics n = row_count; written := written + n;
  insert into pz.fc_calls (id, pos, founder_id, company_id, call_date, attrs, legacy)
  select e.key, (e.ord - 1)::integer,
         case when json_typeof(e.value -> 'founder_id') = 'string' then e.value ->> 'founder_id' end,
         case when json_typeof(e.value -> 'company_id') = 'string' then e.value ->> 'company_id' end,
         case when json_typeof(e.value -> 'date') = 'string' then e.value ->> 'date' end,
         jsonb_build_object('record', e.value::jsonb), e.value::jsonb
  from json_each(coalesce(doc -> 'calls', '{}'::json)) with ordinality as e(key, value, ord)
  on conflict (id) do nothing;
  get diagnostics n = row_count; written := written + n;
  return written;
end;
$$;
revoke all on function pz.backfill_founder_calls() from public, anon, authenticated;

-- The one mapping, shared by this migration (schemas imported before 0015) and the importer (right after the archive
-- is written). Validates EVERYTHING first and raises without writing when malformed; idempotent.
create function pz.backfill_evaluations() returns integer
language plpgsql as $$
declare
  doc json;
  bad text;
  written integer;
begin
  doc := pz.archived_json('evaluations.json');
  if doc is null then
    return 0;
  end if;
  if json_typeof(doc) <> 'object' then
    raise exception 'evaluations.json: the top level must be an object';
  end if;
  if doc -> 'sessions' is not null and json_typeof(doc -> 'sessions') <> 'object' then
    raise exception 'evaluations.json: "sessions" must be an object keyed by id';
  end if;
  select string_agg(e.key, ', ') into bad from json_each(coalesce(doc -> 'sessions', '{}'::json)) as e(key, value)
  where e.key = '' or json_typeof(e.value) <> 'object'
     or (e.value -> 'id' is not null and (json_typeof(e.value -> 'id') <> 'string' or e.value ->> 'id' <> e.key));
  if bad is not null then
    raise exception 'evaluations.json: sessions % are not records keyed by their own id', bad;
  end if;
  select string_agg(k, ', ') into bad from (select e.key as k from json_each(coalesce(doc -> 'sessions', '{}'::json)) as e(key, value)
                                            group by 1 having count(*) > 1) as dup;
  if bad is not null then
    raise exception 'evaluations.json: session ids repeated: %', bad;
  end if;
  insert into pz.eval_sessions (id, pos, status, subject_kind, subject_name, attrs, legacy)
  select e.key, (e.ord - 1)::integer,
         case when json_typeof(e.value -> 'status') = 'string' then e.value ->> 'status' end,
         case when json_typeof(e.value -> 'subject' -> 'kind') = 'string' then e.value -> 'subject' ->> 'kind' end,
         case when json_typeof(e.value -> 'subject' -> 'name') = 'string' then e.value -> 'subject' ->> 'name' end,
         jsonb_build_object('record', e.value::jsonb), e.value::jsonb
  from json_each(coalesce(doc -> 'sessions', '{}'::json)) with ordinality as e(key, value, ord)
  on conflict (id) do nothing;
  get diagnostics written = row_count;
  return written;
end;
$$;
revoke all on function pz.backfill_evaluations() from public, anon, authenticated;

select pz.backfill_evaluations();
