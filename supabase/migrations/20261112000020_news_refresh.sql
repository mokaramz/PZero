-- Review 028c: News & Learning, part 3 (the refresh run, no model). Every file the run writes gets one stored home, so
-- no reader reads an archive for them any more:
--
-- * news_logs: the old append-only logs news/runs.jsonl, disagreements.jsonl, source_log.jsonl, source_history.jsonl
--   and weekly.jsonl as ONE append-only table discriminated by `log`, exactly as 0018's validation_log (an archived line
--   as it was, a new one as the old code wrote it; a line text cannot hold is NULL at its position; identity of an
--   imported row = (log, archive_line); imports precede live rows). `run_notes` is new: one line per run recording what
--   the run deferred (the watch bridge, the source-network nominations), so the old run line stays byte for byte.
-- * news_documents: the old documents news/source_metrics.json, source_state.json, feeds_extra.json, run_state.json
--   and feed_cooldown.json, stored as `json` (not JSONB) so their key order is kept; `legacy` is the imported body.
-- * news_event_history gains the run's actions: `ingest` (a new or merged story), `rederive` (the pass over every
--   stored event) and `card` (a story's card).
create table pz.news_logs (
  seq               bigint generated always as identity primary key,
  log               text not null check (log in ('runs', 'disagreements', 'source_log', 'source_history',
                                                    'weekly', 'run_notes')),
  line              text,                                 -- NULL: an archived line text cannot hold (a NUL byte)
  source            text not null check (source in ('import', 'app')),
  archive_line      integer,
  created_at        timestamptz not null default now(),
  constraint news_logs_archive_line_check check (
    (source = 'import' and archive_line is not null and archive_line > 0)
    or (source = 'app' and archive_line is null)
  ),
  constraint news_logs_line_check check (line is not null or source = 'import')
);
create unique index news_logs_import_idx on pz.news_logs (log, archive_line) where source = 'import';
create index news_logs_log_idx on pz.news_logs (log, seq);
create trigger news_logs_append_only before update or delete on pz.news_logs
  for each row execute function pz.forbid_mutation();

create table pz.news_documents (
  key               text primary key check (key in ('news/source_metrics.json', 'news/source_state.json',
                                                     'news/feeds_extra.json', 'news/run_state.json',
                                                     'news/feed_cooldown.json')),
  body              json not null,
  legacy            json,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

alter table pz.news_logs enable row level security;
alter table pz.news_documents enable row level security;
revoke all on pz.news_logs, pz.news_documents from public, anon, authenticated;

alter table pz.news_event_history drop constraint news_event_history_action_check;
alter table pz.news_event_history add constraint news_event_history_action_check
  check (action in ('seed', 'backcast', 'ingest', 'rederive', 'card'));

-- The one mapping, shared by this migration (schemas imported before 0020) and the importer (right after the
-- archives). Documents: the byte-exact archive first (pz.archived_json, an optional BOM skipped), else the imported
-- `documents` row; inserted only when absent (a rerun keeps what a run wrote); an archive that does not parse is read
-- as missing, as the old tolerant `load_json` read it (its default). Logs: 0018's rules, per log.
create function pz.backfill_news_files() returns integer
language plpgsql as $$
declare
  spec record;
  doc json;
  written integer := 0;
  n integer;
  missing integer;
  first_missing integer;
  last_imported integer;
begin
  for spec in select * from (values ('news/source_metrics.json'), ('news/source_state.json'), ('news/feeds_extra.json'),
                                    ('news/run_state.json'), ('news/feed_cooldown.json')) as v(path) loop
    begin
      doc := pz.archived_json(spec.path);
    exception when others then
      doc := null;   -- unreadable: the old tolerant default
    end;
    if doc is null then
      select d.body::json into doc from pz.documents d where d.key = spec.path;
    end if;
    if doc is not null then
      insert into pz.news_documents (key, body, legacy) values (spec.path, doc, doc) on conflict (key) do nothing;
      get diagnostics n = row_count; written := written + n;
    end if;
  end loop;

  for spec in select * from (values ('news/runs.jsonl', 'runs'), ('news/disagreements.jsonl', 'disagreements'),
                                    ('news/source_log.jsonl', 'source_log'),
                                    ('news/source_history.jsonl', 'source_history'),
                                    ('news/weekly.jsonl', 'weekly')) as v(path, log) loop
    select count(*), min(a.pos) into missing, first_missing
    from pz.archived_lines(spec.path) a
    where not exists (select 1 from pz.news_logs l
                      where l.source = 'import' and l.log = spec.log and l.archive_line = a.pos);
    if missing = 0 then
      continue;
    end if;
    if exists (select 1 from pz.news_logs l where l.source = 'app' and l.log = spec.log) then
      raise exception '%: % archived line(s) are not imported and the log already has live rows', spec.path, missing;
    end if;
    select max(l.archive_line) into last_imported from pz.news_logs l where l.source = 'import' and l.log = spec.log;
    if last_imported is not null and first_missing < last_imported then
      raise exception '%: archived line % is missing before imported line %', spec.path, first_missing, last_imported;
    end if;
    insert into pz.news_logs (log, line, source, archive_line)
    select spec.log, a.line, 'import', a.pos
    from pz.archived_lines(spec.path) a
    where not exists (select 1 from pz.news_logs l
                      where l.source = 'import' and l.log = spec.log and l.archive_line = a.pos)
    order by a.pos;
    get diagnostics n = row_count; written := written + n;
  end loop;
  return written;
end;
$$;
revoke all on function pz.backfill_news_files() from public, anon, authenticated;

select pz.backfill_news_files();
