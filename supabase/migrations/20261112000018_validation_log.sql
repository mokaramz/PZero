-- Review 027b: Validation, part 2 (the writes). The four old append-only logs (validation/outcomes.jsonl,
-- audits.jsonl, snapshots.jsonl, scout_feedback.jsonl) as ONE append-only table, discriminated by `log`.
--
-- `line` is the stored line itself: an archived physical line as it was (only its line end removed), or a new row as
-- the old `json.dumps(row, ensure_ascii=False, sort_keys=True)`. The reader rejoins each log's lines in `seq` order,
-- so the read model parses exactly what the old file held (a line that does not parse is kept and skipped on read, as
-- before). `seq` gives the order; gaps (a rolled-back insert) are allowed and nothing assumes consecutive values.
--
-- An archived line PostgreSQL text cannot hold (a NUL byte; never valid JSON, so the old reader skipped it) is kept at
-- its position with `line` NULL; its bytes stay in the archive, and the reader renders it as an empty line, which is
-- skipped as before. Only imported rows may have no line.
--
-- Imported rows are identified by (log, archive_line): identical lines at different positions are different rows. App
-- rows have no archive line and no uniqueness (two identical operator submissions stay two rows, as in the old app).
create table pz.validation_log (
  seq               bigint generated always as identity primary key,
  log               text not null check (log in ('outcomes', 'audits', 'snapshots', 'scout_feedback')),
  line              text,                                 -- NULL: an archived line text cannot hold (a NUL byte)
  source            text not null check (source in ('import', 'app')),
  archive_line      integer,                              -- the 1-based physical line in the archive (imports only)
  created_at        timestamptz not null default now(),
  constraint validation_log_archive_line_check check (
    (source = 'import' and archive_line is not null and archive_line > 0)
    or (source = 'app' and archive_line is null)
  ),
  constraint validation_log_line_check check (line is not null or source = 'import')
);
create unique index validation_log_import_idx on pz.validation_log (log, archive_line) where source = 'import';
create index validation_log_log_idx on pz.validation_log (log, seq);
create trigger validation_log_append_only before update or delete on pz.validation_log
  for each row execute function pz.forbid_mutation();
alter table pz.validation_log enable row level security;
revoke all on pz.validation_log from public, anon, authenticated;

-- An archived text file as its physical lines, read as the old reader read it (Codex H-241: line by line, so one bad
-- line never hides its neighbours): an optional BOM skipped; split on universal newlines (CRLF, CR, LF) at the BYTE
-- level (no UTF-8 sequence contains those bytes), as the old text-mode read did; the empty piece after a final line end
-- is not a line. Each line is then decoded on its own; a line holding a NUL byte (which text cannot hold) is NULL at its
-- position. A file that is not UTF-8 anywhere has no lines at all (the old `read_text` read it as "").
create function pz.archived_lines(archive_path text) returns table (pos integer, line text)
language plpgsql stable as $$
declare
  raw bytea;
  n integer;
  start integer := 1;         -- 1-based byte position where the current line begins
  cr integer;
  lf integer;
  stop integer;
  seg bytea;
  rest bytea;
  nul integer;
  segs bytea[] := '{}';
  lines text[] := '{}';
  piece text;
  i integer;
begin
  select d.raw into raw from pz.legacy_documents d where d.path = archive_path;
  if raw is null then
    return;
  end if;
  if substring(raw from 1 for 3) = '\xefbbbf'::bytea then
    raw := substring(raw from 4);
  end if;
  n := length(raw);
  while start <= n loop
    rest := substring(raw from start);
    cr := position('\x0d'::bytea in rest);
    lf := position('\x0a'::bytea in rest);
    if cr = 0 and lf = 0 then
      segs := segs || substring(raw from start);
      exit;
    end if;
    stop := case when cr = 0 then lf when lf = 0 then cr else least(cr, lf) end;
    segs := segs || substring(raw from start for stop - 1);
    start := start + stop;
    if stop = cr and lf = cr + 1 then
      start := start + 1;   -- CRLF is one line end
    end if;
  end loop;
  for i in 1 .. coalesce(array_length(segs, 1), 0) loop
    seg := segs[i];
    if position('\x00'::bytea in seg) = 0 then
      begin
        lines := lines || convert_from(seg, 'UTF8');
      exception when others then
        return;   -- not UTF-8: the whole file reads as "" (the old rule)
      end;
    else
      rest := seg;   -- every NUL-free part must still be UTF-8; the line itself cannot be text
      loop
        nul := position('\x00'::bytea in rest);
        begin
          piece := convert_from(case when nul = 0 then rest else substring(rest from 1 for nul - 1) end, 'UTF8');
        exception when others then
          return;
        end;
        exit when nul = 0;
        rest := substring(rest from nul + 1);
      end loop;
      lines := lines || null::text;
    end if;
  end loop;
  return query select o.ord::integer, o.line from unnest(lines) with ordinality as o(line, ord);
end;
$$;
revoke all on function pz.archived_lines(text) from public, anon, authenticated;

-- The one mapping, shared by this migration (schemas imported before 0018) and the importer (right after the archives
-- are written). Repeatable: a rerun inserts only the archive positions not yet present, in line order, so a second run
-- adds nothing. Imported rows always precede live rows: once a log has an app row, a rerun adds nothing, and an
-- archived line still missing is refused (it raises, writing nothing), as is a missing line before an imported one.
create function pz.backfill_validation() returns integer
language plpgsql as $$
declare
  spec record;
  written integer := 0;
  n integer;
  missing integer;
  first_missing integer;
  last_imported integer;
begin
  for spec in select * from (values ('validation/outcomes.jsonl', 'outcomes'), ('validation/audits.jsonl', 'audits'),
                                    ('validation/snapshots.jsonl', 'snapshots'),
                                    ('validation/scout_feedback.jsonl', 'scout_feedback')) as v(path, log) loop
    select count(*), min(a.pos) into missing, first_missing
    from pz.archived_lines(spec.path) a
    where not exists (select 1 from pz.validation_log l
                      where l.source = 'import' and l.log = spec.log and l.archive_line = a.pos);
    if missing = 0 then
      continue;
    end if;
    if exists (select 1 from pz.validation_log l where l.source = 'app' and l.log = spec.log) then
      raise exception '%: % archived line(s) are not imported and the log already has live rows', spec.path, missing;
    end if;
    select max(l.archive_line) into last_imported from pz.validation_log l
    where l.source = 'import' and l.log = spec.log;
    if last_imported is not null and first_missing < last_imported then
      raise exception '%: archived line % is missing before imported line %', spec.path, first_missing, last_imported;
    end if;
    insert into pz.validation_log (log, line, source, archive_line)
    select spec.log, a.line, 'import', a.pos
    from pz.archived_lines(spec.path) a
    where not exists (select 1 from pz.validation_log l
                      where l.source = 'import' and l.log = spec.log and l.archive_line = a.pos)
    order by a.pos;
    get diagnostics n = row_count; written := written + n;
  end loop;
  return written;
end;
$$;
revoke all on function pz.backfill_validation() from public, anon, authenticated;

select pz.backfill_validation();
