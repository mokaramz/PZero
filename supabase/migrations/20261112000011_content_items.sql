-- Review 020: Public work (the operator's content log, the old content.json {"items": [...]}).
-- The current record is attrs.record; legacy keeps the imported item unchanged; text columns mirror string values only
-- (the old routes stored any JSON value as sent). A delete is soft (deleted_at); every write is one append-only event.
create table pz.content_items (
  id                text primary key check (id <> ''),     -- the old id ('c-YYMMDDHHMMSS', or one the client chose)
  pos               integer not null unique,               -- list order: the file order, a new item above all others
  title             text,
  platform          text,
  kind              text,                                  -- idea | draft | published (as stored; never constrained)
  status            text,
  url               text,
  created           text,                                  -- the old 'YYYY-MM-DD' string, as stored
  attrs             jsonb not null default '{}',           -- {record: the current item}
  legacy            jsonb,                                 -- the imported item, never changed
  created_at        timestamptz not null default now(),
  deleted_at        timestamptz                            -- soft delete: hidden from GET, history kept
);
alter table pz.content_items enable row level security;
revoke all on pz.content_items from public, anon, authenticated;

create table pz.content_item_events (
  id                bigint generated always as identity primary key,
  item_id           text not null references pz.content_items (id),
  actor             text not null,                         -- 'operator'
  action            text not null check (action in ('create', 'save', 'delete')),
  before            jsonb,                                 -- changed fields before (null on create)
  after             jsonb not null,                        -- the same fields after (the whole record on create)
  detail            jsonb not null default '{}',           -- {replaces_deleted: true} when a deleted id is recreated
  at                timestamptz not null default now()
);
create index content_item_events_item_idx on pz.content_item_events (item_id, at desc);
create trigger content_item_events_append_only before update or delete on pz.content_item_events
  for each row execute function pz.forbid_mutation();
alter table pz.content_item_events enable row level security;
revoke all on pz.content_item_events from public, anon, authenticated;

-- The one mapping from the archived content.json (the generic documents row the import writes) into content_items.
-- Called here for schemas imported before 0011, and by the importer right after it writes the documents. Idempotent:
-- an id that already has a row is never touched, so a later edit or delete survives a retry. It validates EVERYTHING
-- first and raises without writing anything when the log is malformed (the import plan reports the same blockers).
create function pz.backfill_content_items() returns integer
language plpgsql as $$
declare
  body jsonb;
  bad text;
  written integer;
begin
  select d.body into body from pz.documents d where d.key = 'content.json';
  if body is null then
    return 0;
  end if;
  if jsonb_typeof(body) <> 'object' or jsonb_typeof(body -> 'items') is distinct from 'array' then
    raise exception 'content.json: the top level must be an object with an "items" list';
  end if;
  select string_agg((e.ord - 1)::text, ', ' order by e.ord) into bad
  from jsonb_array_elements(body -> 'items') with ordinality as e(item, ord)
  where jsonb_typeof(e.item) <> 'object' or jsonb_typeof(e.item -> 'id') is distinct from 'string'
     or e.item ->> 'id' = '';
  if bad is not null then
    raise exception 'content.json: items at positions % are not records with a non-empty string id', bad;
  end if;
  select string_agg(dup.id, ', ' order by dup.id) into bad
  from (select e.item ->> 'id' as id from jsonb_array_elements(body -> 'items') as e(item)
        group by 1 having count(*) > 1) as dup;
  if bad is not null then
    raise exception 'content.json: repeated item ids %', bad;
  end if;
  insert into pz.content_items (id, pos, title, platform, kind, status, url, created, attrs, legacy)
  select e.item ->> 'id', (e.ord - 1)::integer,
         case when jsonb_typeof(e.item -> 'title') = 'string' then e.item ->> 'title' end,
         case when jsonb_typeof(e.item -> 'platform') = 'string' then e.item ->> 'platform' end,
         case when jsonb_typeof(e.item -> 'kind') = 'string' then e.item ->> 'kind' end,
         case when jsonb_typeof(e.item -> 'status') = 'string' then e.item ->> 'status' end,
         case when jsonb_typeof(e.item -> 'url') = 'string' then e.item ->> 'url' end,
         case when jsonb_typeof(e.item -> 'created') = 'string' then e.item ->> 'created' end,
         jsonb_build_object('record', e.item), e.item
  from jsonb_array_elements(body -> 'items') with ordinality as e(item, ord)
  on conflict (id) do nothing;
  get diagnostics written = row_count;
  return written;
end;
$$;
revoke all on function pz.backfill_content_items() from public, anon, authenticated;

select pz.backfill_content_items();
