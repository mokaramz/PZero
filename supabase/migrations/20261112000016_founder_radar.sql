-- Review 026a: Founder Radar, part 1. The old radar_companies.json {companies: {<key>: company}} and
-- radar_research.json {domains: {<key>: research}} as ORDERED record tables, plus one append-only event table, and the
-- person tombstone of a merge.
--
-- The records are stored as `json`, not JSONB: a research record's proposals / pages / pairings / failed maps are
-- order-sensitive (they decide grouping ties, recommended order and what the page lists first), and JSONB would sort
-- their keys. pos is the record's position in the archived object (json_each ... with ordinality over the byte-exact
-- archive, through pz.archived_json: the optional UTF-8 BOM skipped), exactly as 0014 / 0015.
create table pz.radar_companies (
  key               text primary key check (key <> ''),
  pos               integer not null unique,
  record            json not null,                        -- the current company record (its own key order kept)
  legacy            json,                                 -- the imported record
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create table pz.radar_research (
  key               text primary key check (key <> ''),
  pos               integer not null unique,
  record            json not null,                        -- the current research record (proposals / pages order kept)
  legacy            json,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create table pz.radar_events (
  id                bigint generated always as identity primary key,
  entity            text not null check (entity in ('company', 'research', 'metrics')),
  key               text not null,
  actor             text not null,                        -- 'operator'
  action            text not null check (action in ('action', 'import', 'company', 'promote', 'boardy', 'pair',
                                                        'review', 'refs', 'snapshot')),
  before            jsonb,                                -- the record before (null when new)
  after             jsonb not null,                       -- the record after
  detail            jsonb not null default '{}',          -- the request
  at                timestamptz not null default now()
);
create index radar_events_key_idx on pz.radar_events (entity, key, at desc);
create trigger radar_events_append_only before update or delete on pz.radar_events
  for each row execute function pz.forbid_mutation();
alter table pz.radar_companies enable row level security;
alter table pz.radar_research enable row level security;
alter table pz.radar_events enable row level security;
revoke all on pz.radar_companies, pz.radar_research, pz.radar_events from public, anon, authenticated;

-- The merge tombstone (plan revisions 2 / 3): the merged person's row stays, pointing at the survivor; the one people
-- reader and every writer's row lock leave it out, and its id stays reserved.
alter table pz.people add column merged_into text references pz.people (id);
create index people_merged_into_idx on pz.people (merged_into) where merged_into is not null;
alter table pz.people add constraint people_not_merged_into_itself check (merged_into is null or merged_into <> id);

alter table pz.person_events drop constraint person_events_action_check;
alter table pz.person_events add constraint person_events_action_check
  check (action in ('create', 'save', 'talented', 'watch_log', 'radar', 'merge', 'merged'));

-- The one mapping, shared by this migration (schemas imported before 0016) and the importer (right after the archive
-- is written). Validates EVERYTHING first and raises without writing when malformed; idempotent.
create function pz.backfill_founder_radar() returns integer
language plpgsql as $$
declare
  spec record;
  doc json;
  bad text;
  written integer := 0;
  n integer;
begin
  for spec in select * from (values ('radar_companies.json', 'companies'), ('radar_research.json', 'domains')) as v(path, coll) loop
    doc := pz.archived_json(spec.path);
    if doc is null then
      continue;
    end if;
    if json_typeof(doc) <> 'object' then
      raise exception '%: the top level must be an object', spec.path;
    end if;
    if doc -> spec.coll is not null and json_typeof(doc -> spec.coll) <> 'object' then
      raise exception '%: "%" must be an object keyed by id', spec.path, spec.coll;
    end if;
    select string_agg(e.key, ', ') into bad from json_each(coalesce(doc -> spec.coll, '{}'::json)) as e(key, value)
    where e.key = '' or json_typeof(e.value) <> 'object';
    if bad is not null then
      raise exception '%: % records % are not records keyed by a non-empty key', spec.path, spec.coll, bad;
    end if;
    select string_agg(k, ', ') into bad from (select e.key as k from json_each(coalesce(doc -> spec.coll, '{}'::json)) as e(key, value)
                                              group by 1 having count(*) > 1) as dup;
    if bad is not null then
      raise exception '%: % keys repeated: %', spec.path, spec.coll, bad;
    end if;
  end loop;

  doc := pz.archived_json('radar_companies.json');
  if doc is not null then
    insert into pz.radar_companies (key, pos, record, legacy)
    select e.key, (e.ord - 1)::integer, e.value, e.value
    from json_each(coalesce(doc -> 'companies', '{}'::json)) with ordinality as e(key, value, ord)
    on conflict (key) do nothing;
    get diagnostics n = row_count; written := written + n;
  end if;
  doc := pz.archived_json('radar_research.json');
  if doc is not null then
    insert into pz.radar_research (key, pos, record, legacy)
    select e.key, (e.ord - 1)::integer, e.value, e.value
    from json_each(coalesce(doc -> 'domains', '{}'::json)) with ordinality as e(key, value, ord)
    on conflict (key) do nothing;
    get diagnostics n = row_count; written := written + n;
  end if;
  return written;
end;
$$;
revoke all on function pz.backfill_founder_radar() from public, anon, authenticated;

select pz.backfill_founder_radar();
