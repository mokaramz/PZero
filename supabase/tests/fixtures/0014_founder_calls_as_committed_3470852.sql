-- Review 023: Founder Calls (the old founder_calls.json {version, label, companies{}, founders{}, calls{}}) as three
-- ORDERED record tables and one append-only event table. The current record is attrs.record; legacy keeps the imported
-- one; pos is the record's position in its object, from the BYTE-EXACT archive (Codex H-175): JSONB does not keep
-- object key order, so the backfill parses legacy_documents.raw as json (which keeps the text) and takes positions
-- from json_each ... with ordinality. The top-level version / label stay in the archived document.
create table pz.fc_companies (
  id                text primary key check (id <> ''),
  pos               integer not null unique,
  name              text,
  attrs             jsonb not null default '{}',          -- {record: the current company}
  legacy            jsonb,
  created_at        timestamptz not null default now()
);
create table pz.fc_founders (
  id                text primary key check (id <> ''),
  pos               integer not null unique,
  name              text,
  company_id        text,                                 -- as recorded (no FK: the old file allowed dangling ids)
  attrs             jsonb not null default '{}',
  legacy            jsonb,
  created_at        timestamptz not null default now()
);
create table pz.fc_calls (
  id                text primary key check (id <> ''),
  pos               integer not null unique,
  founder_id        text,
  company_id        text,
  call_date         text,                                 -- the old 'date' string, as recorded
  attrs             jsonb not null default '{}',
  legacy            jsonb,
  created_at        timestamptz not null default now()
);
create table pz.fc_events (
  id                bigint generated always as identity primary key,
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('save', 'followup', 'link')),
  before            jsonb not null,                       -- {companies: {id: record|null}, founders: ..., calls: ...}
  after             jsonb not null,                       -- the same ids after the write
  detail            jsonb not null default '{}',          -- the request (ids), changed / merged flags
  at                timestamptz not null default now()
);
create index fc_events_at_idx on pz.fc_events (at desc);
create trigger fc_events_append_only before update or delete on pz.fc_events
  for each row execute function pz.forbid_mutation();
alter table pz.fc_companies enable row level security;
alter table pz.fc_founders enable row level security;
alter table pz.fc_calls enable row level security;
alter table pz.fc_events enable row level security;
revoke all on pz.fc_companies, pz.fc_founders, pz.fc_calls, pz.fc_events from public, anon, authenticated;

-- The one mapping, shared by this migration (schemas imported before 0014) and the importer (right after the archive
-- is written). Validates EVERYTHING first and raises without writing when the archive is malformed; then inserts each
-- record that has no row yet, at its original position (on conflict do nothing: a retry keeps later edits).
create function pz.backfill_founder_calls() returns integer
language plpgsql as $$
declare
  doc json;
  bad text;
  coll text;
  written integer := 0;
  n integer;
begin
  select convert_from(d.raw, 'UTF8')::json into doc from pz.legacy_documents d where d.path = 'founder_calls.json';
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

select pz.backfill_founder_calls();
