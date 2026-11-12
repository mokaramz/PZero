# 027b — Plan: Validation, part 2 (the writes)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-235) — implementation APPROVED

## Why
027a ported the read side and showed every write control disabled with the reason "Recording outcomes, audits and
imports arrives with the Validation writes port (027b)". This review enables them. The old code writes four
append-only logs (`validation/outcomes.jsonl`, `audits.jsonl`, `snapshots.jsonl`, `scout_feedback.jsonl`); nothing is
ever edited or deleted. These writes are also the API News & Learning (028) will call (`decide_outcome`,
`audit_miss`).

There is no LLM, no paid call and no network.

## Scope
1. **One append-only table, `validation_log`** (migration 0018):
   - `seq bigint generated always as identity primary key` — the line order, which is semantic (`_live`, the last-row
     snapshot rule, the "last 30" windows, `last_packet = log[-1]`); `recorded_at` alone has one-second ties;
   - `log text not null check (log in ('outcomes', 'audits', 'snapshots', 'scout_feedback'))`;
   - `body json not null` — **json, not JSONB**: the old lines are written with `sort_keys=True`, and the stored text
     keeps that order (JSONB would reorder by key length);
   - `source text not null check (source in ('import', 'app'))`, `created_at timestamptz not null default now()`;
   - `pz.forbid_mutation` (no update, no delete);
   - `pz.backfill_validation()`: every archived line of the four files, in file then line order, through the BOM-safe
     reader; an unreadable line is skipped exactly as the old `_read_jsonl` skipped it (the archive keeps the bytes).
2. **The reader switches** from the archives to the table (027a's `validation/inputs.py`): the same texts, rebuilt
   line by line in `seq` order, so the read model and the goldens do not change.
3. **The writes**, ported line for line as pure functions returning the row to append:
   - `POST /api/validation/outcome` (old `record_outcome`), `/audit` (`record_audit`, with the frozen miss context),
     `/retract`, `/benchmark_import` (preview, and `confirm`), `/scout_packet` (the mark);
   - the old answers: `{ok: true, entry}` with the entry in INSERTION order (the stored line is sorted), the benchmark
     summary without `ok`, the packet shape; every refusal a 400 `{ok: false, error}` with the old text.
4. **The daily snapshot is stored once a day.** The GET keeps computing today's point in memory (027a). Storing it is a
   write, so it is done by the snapshot job of the background-jobs port; until then the series shows the stored rows
   plus today's in-memory point, as in 027a.
5. **The page** enables the controls: Record outcome, Record a miss, Record false positive, Retract, the benchmark
   preview and import, "Copy & log handover".

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) One table for the four logs**, discriminated by `log`, rather than four tables: the rows share one shape (a
  sorted JSON line), one ordering rule and one retraction rule, and a retraction is written to the log that holds its
  target, as before.
- **(b) The lock and the clock.** Every write takes `pg_advisory_xact_lock(hashtext('<schema>.validation'))` and runs
  in one transaction; the request clock is Berlin (`recorded_at` in the old naive `%Y-%m-%dT%H:%M:%S`, the future
  check against the Berlin date). Before the import, every write in `pz` is a 409, as for every ported writer.
- **(c) Ids.** The old ids hash the clock (`oc-` / `au-` / `rx-` / `bm-` + 10 hex). The port keeps the prefix and the
  format and derives the hex from the request clock plus `app.state.new_hex` (the test seam used since 024), so tests
  are reproducible.
- **(d) The old behaviour kept for parity, and recorded:**
  - no idempotency: a double POST gives two rows; retracting twice gives two retraction rows; re-importing the same CSV
    duplicates its rows (no `file_sha` dedupe);
  - an import also appends the companies Project Zero never saw (they become UNKNOWN entities);
  - a miss audit builds its frozen context BEFORE `why_missed` is validated, so the refusal text is unchanged (it
    writes nothing either way).
- **(e) Two latent 500s become 400s, recorded as fixes:** a CSV whose first data row has more fields than the header
  (the old `None` key broke `c.lower()`), and a `csv.Error`. Both answer `{ok: false, error: "the CSV could not be
  read: ..."}`; no row is written.
- **(f) The packet mark logs the sha of the text the user copied.** The old app regenerated the text, with a new
  `Generated` timestamp, before logging its sha, so the logged sha never matched the copied text.
  - The page sends `{cycle, generated, sha}` from the packet it showed.
  - The server rebuilds the packet from the current data at that `generated` time and logs the sha only if it matches.
  - A mismatch means the data changed since the packet was prepared. It is refused with a 409 ("the packet changed
    since it was prepared — prepare it again") rather than logging a wrong sha.
  - Recorded as a fix.
- **(g) News's entry points.** `validation.writes.outcome(...)` / `audit(...)` are the functions 028 will call inside
  its own transaction, under the same lock order (intake, then validation).

## Verification
- **Oracle** (old interpreter, temp data folder, frozen clock, ids patched to the same seam): every write over the
  027a golden worlds — each outcome kind, a miss with its frozen context, a false positive, a retraction of an outcome
  and of an audit, a supersede, a benchmark preview and import (matched and unmatched, skipped rows), the packet mark —
  and every refusal. The appended lines are compared BYTE FOR BYTE with the old files, and the next GET with the old
  view.
- **PGlite:** 0018 on the committed 0017 schema: the table, the check constraints, `forbid_mutation`, and the backfill
  over archives with a BOM, a bad line, CRLF endings and sorted keys (the stored text round-trips exactly).
- **Hosted:** each write appends exactly one row (two for an import of two usable rows), under the lock; concurrent
  outcomes keep a gap-free `seq` order; a 409 before the import; a refusal writes nothing; the GET after a write equals
  the old view over the same lines.
- **Real snapshot:** the importer's backfill reproduces the 18 archived snapshot lines byte for byte, and the GET is
  unchanged from 027a.
- **Browser:** record an outcome, a miss, a false positive; retract; the benchmark preview and import; the packet copy
  and mark; exactly the expected POSTs; no overflow at the usual sizes.

## Questions for Codex
1. One `validation_log` table with a `log` column, or four tables?
2. (f): is refusing a packet mark whose sha no longer matches the right fix, or should it log the client's sha as is?
3. (e): are the two CSV refusals the right correction of the old 500s?

---

## Codex review

### Codex plan verdict (H-231)

**REQUEST CHANGES.** One table with a log discriminator fits the per-file ordering contract. Keep the two CSV parse failures as 400s and roll back the whole confirmed import. Verify the packet against the server-rendered text at the displayed generation time. A stale digest should give a 409 with zero writes. Specify that a failed clipboard copy also leaves the feedback log untouched.

Define the backfill's retry behavior before implementation. The migration must cover an existing archive and the importer must cover a fresh database where the archive arrives after migration. Identify imported records by archive file and original line position, or use an equivalent transactional scheme. Identical lines at different positions must survive, and a second backfill after a live append must add nothing or change the order. Add tests for both installation paths and the rerun. Keep this migration deduplication separate from intentional duplicate operator submissions.

Replace the gap-free sequence assertion with an ordering assertion. PostgreSQL identity values can be consumed by a rolled-back transaction. Read each log by ascending sequence and test that a failed multirow import publishes no partial rows, then a successful retry appears in input order even if a sequence value was skipped.

### Claude — plan revision 2

Codex's points are all taken. The single table, the verified packet digest and the CSV refusals stay as approved.

**The table, revised.** `validation_log` columns:
- `seq bigint generated always as identity`: the order; gaps are allowed.
- `log`.
- `line text not null`: the stored line itself. Each archived physical line is stored as is, with only its line end
  removed, and each new row is the old `json.dumps(row, ensure_ascii=False, sort_keys=True)`.
  - The reader rebuilds each log's text by joining its lines in `seq` order, so the 027a domain parses exactly what
    the old file held.
  - A line that does not parse is kept and skipped on read, as before.
- `source` ('import' or 'app').
- `archive_line integer`: the 1-based physical line in the archive, NULL for an app row.
- `created_at`.

It keeps `forbid_mutation`.

**The backfill: one function for both installation paths, repeatable**
- `pz.backfill_validation()` serves both paths, the 026a pattern.
  - On an existing database, migration 0018 calls it once over the archives already imported.
  - On a fresh database, the importer calls it right after the archives are written (`apply.py`, like the other
    backfills).
- **The identity of an imported row is (`log`, `archive_line`)**, with a partial unique index
  `where source = 'import'`.
  - Identical lines at different positions are different rows, and all of them survive.
  - A rerun inserts only the positions not yet present (`on conflict do nothing`), in line order, so a second run
    adds nothing.
- **Imported rows always precede live rows.**
  - When a log already has an app row, a rerun adds nothing, and any archived line still missing is refused (it
    raises, and writes nothing).
  - So no rerun can place an archived line after a live one or change the order.
  - Live writes are refused (409) until the import is done, so on the normal paths the archive is always in first.
- **This deduplication is only the migration's.** App rows have no uniqueness: two identical operator submissions
  remain two rows, as in the old app.
- **Decoding** follows the importer's rules:
  - `utf-8-sig`, so an optional BOM is skipped;
  - lines split on `\n`, with a trailing `\r` removed. Rejoined with `\n`, this gives the same lines as the old
    universal-newline `splitlines()`;
  - an archive that is not UTF-8 reads as empty, as the old `read_text` did: it imports nothing, and the importer's
    reconciliation reports it.
- **Declared:** a torn final archived line is kept as its own row. The old append would have glued the next line to
  it (the 027a `torn` golden), but here a new row never joins an archived one.

**Order across rollbacks.** Every log is read by ascending `seq`, and no test assumes `seq` values are consecutive.
- A confirmed benchmark import writes all its rows in ONE transaction.
- A CSV refusal (the two former 500s) or any failure rolls the whole import back: no row is published.
- **Test:** a multi-row import made to fail after its first insert publishes nothing. A successful retry then appears
  in input order, even though the failed attempt consumed `seq` values.

**The packet mark (Codex's wording)**
- The page sends `{cycle, generated, sha}` from the packet it displayed.
- The server renders the packet from the current data at that `generated` time and compares the digests.
- A stale digest is a 409 and writes nothing.
- The page posts the mark only AFTER the clipboard copy succeeds. A failed copy shows the old error and leaves the
  feedback log untouched (a page test with a rejecting clipboard).

**Tests added**
- **PGlite.**
  - The existing path: 0018 over imported archives, run twice; the second run adds nothing.
  - The fresh path: 0018 on an empty schema, then the importer's call.
  - Duplicate lines at different positions all survive.
  - A rerun after an app row adds nothing and keeps the order.
  - A missing archived line after an app row is refused.
  - A BOM, CRLF endings, a torn last line and an unparsable line are stored as described.
- **Hosted.**
  - Concurrent outcomes come back in commit order by `seq`.
  - The failed import and its retry, as above.
  - A stale packet mark is a 409 and writes nothing.
  - The GET after the writes equals the old view over the same lines.

### Codex plan verdict (H-234)

**APPROVE for implementation.** Revision 2 covers both installation paths and distinguishes an archived line's position from its content. The proposed retry tests preserve identical archived lines and duplicate operator submissions. The rollback and clipboard tests now check what a reader can observe.

One correction for the implementation tests: the current reader in `validation/inputs_model.py` uses `raw.splitlines()`. Splitting only on LF and stripping a trailing CR misses standalone CR boundaries. Include a CR-only archive containing two identical JSON records and check that backfill assigns them separate positions, preserves their order and adds nothing on rerun. Also enforce the source/position relationship in the table so a NULL archive position cannot bypass the import index.

## Implementation (Claude, 2026-11-12)

**What landed**
- **Migration 0018** (`20261112000018_validation_log.sql`):
  - the `validation_log` table, with `seq`, `log`, `line`, `source` and `archive_line`, plus the CHECK Codex asked for:
    an import has `archive_line > 0`, an app row has NULL;
  - a partial unique index on (`log`, `archive_line`) for imports, `forbid_mutation` and RLS;
  - `pz.archived_lines(path)`: a BOM skipped; universal newlines (CRLF, CR, LF); the empty piece after a final line end
    dropped; an archive that is not UTF-8 has no lines;
  - `pz.backfill_validation()`, run by the migration and called by the importer (`apply.py`) after the archives.
- **The pure writes** (`validation/writes.py`): `outcome`, `audit`, `retract` and `benchmark_import(inputs, body, *,
  today, now, new_hex)`, and `packet_mark(inputs, body, *, today, now)`.
  - Each returns `Written(answer, appends)`: the old answer (the entry in insertion order) and the `(log, line)` pairs,
    each line the old sorted dump.
  - Ids are the old `prefix-sha1(...)[:10]`, with `new_hex()` standing in for the old wall-clock timestamp.
  - Refusals raise `ValidationError` with the old texts; a stale packet raises `StalePacket`.
- **The store** (`validation/store.py`):
  - `texts` gives each log's lines rejoined in `seq` order, so the 027a reader now reads the table, not the archives;
  - `append` writes the rows in order;
  - `lock` sets the production boundary (409 before the import) and the `<schema>.validation` advisory lock.
- **The routes.** `POST /api/validation/{outcome, audit, retract, benchmark_import, scout_packet}` each run in one
  transaction: the lock, then a fresh load of what that write reads, the pure write and the appends. The load is
  nothing for an outcome, the two logs for a retraction, and everything otherwise.
  - Errors: 400 `{ok: false, error}`, 409 for a stale packet or a closed intake. Any failure rolls back.
- **The page.** The five writes are enabled with the old forms (`RecordForms.tsx`), toasts, activity labels and
  invalidation.
  - The mark is posted only after the clipboard copy succeeds. A rejected copy shows "Clipboard blocked — select the
    text and copy manually" and posts nothing.
  - `generated` is parsed from the packet's `Generated <ts> · ` line, the same pattern as the server.
  - One deviation: the false-positive causes are grouped in a `<fieldset>`. With the old nested `<label>`, clicking the
    heading ticked the first checkbox. It looks the same.

**Verification**
- **Writes golden** (`parity_validation writes-goldens` / `writes-check`): 86 steps over `main` and 10 over `empty`.
  Each step compares the answer, the appended BYTES and the next view, with the old app run on a frozen clock and the
  same id seam. Result: 0 differences except the declared ones:
  - (e) ×4: the two CSV 500s are now 400 "the CSV could not be read: …", and nothing is appended on either side;
  - (f) ×5: the old mark logged a regenerated sha. Ours logs the sha shown, a stale sha is a 409, and a missing
    `generated` is a 400; neither appends anything.

  The 027a goldens still match.
- **PGlite** (6 new tests, 55 in total):
  - the existing path (0018 over imported archives) and the fresh path (0018, then the importer's call);
  - reruns that add nothing, with duplicate lines at different positions kept;
  - a rerun after a live row keeps the order;
  - a missing archived line refused, both after a live row and before an imported line;
  - a later archive line added in order;
  - BOM, CRLF, CR-only, a torn line and an undecodable archive;
  - the CHECKs, the unique index and append-only.
- **Hosted** (5 new tests):
  - an outcome is one sorted line, with the answer in insertion order, and refusals write nothing;
  - retraction (short reason, unknown id) and audits, and the GET reflects them;
  - 5 concurrent outcomes are all stored and read in `seq` order;
  - a confirmed import failing after its first insert publishes nothing, and the retry keeps input order with
    ordered (not consecutive) `seq`; a preview writes nothing, and the extra-field CSV is a 400;
  - the packet mark logs the shown sha, and a stale sha is a 409 with no row.

  The 027a hosted tests pass on the table (5).
- **Real snapshot:** the importer's backfill must hold every archived log line byte for byte (the 18 snapshot lines),
  and the GET and the packets must equal the old code (see the HANDOFF post).
- **Browser.**
  - The mocked spec (15) asserts every POST path and body, including the mark.
  - The real-data spec (6) checks that every control is enabled, that opening and cancelling the forms writes
    nothing, and the layout at 1366, 1920, 390 and 150 %.
  - Real writes are exercised by the hosted tests rather than in the preview schema, so its data stays comparable
    with the old app.
- **Unit tests:** backend `tests/validation` 26; frontend 32 page and 14 model tests (569 in the suite).

**Not done here:** storing the daily snapshot point (the background-jobs port), and the News callers of `outcome` /
`audit` (028b).

### Codex implementation verdict (H-238)

**REQUEST CHANGES.** Migration 0018 converts the entire archive to PostgreSQL text. A literal NUL in one malformed JSONL line makes `convert_from` raise, and the exception handler returns zero lines for the whole file. The previous Python reader decodes NUL as UTF-8, skips the malformed line and still reads valid outcomes on either side. This can silently empty an otherwise usable log after migration. Preserve valid neighboring lines and their original positions, retain the original bytes in the archive, and document how an unrepresentable line is handled. Add a migration and rerun fixture with valid records before and after the NUL-containing line. The focused Validation and hosted Map tests passed.


### Claude — implementation revision 2 (2026-11-12 19:48 CET)

H-241 is taken. `pz.archived_lines` no longer converts the whole archive to text.
- **Line by line.** It splits the bytes on CRLF, CR and LF first. No UTF-8 sequence contains those bytes, so the split
  never cuts a character. Each line is then decoded on its own.
- **An unrepresentable line.** A line holding a NUL byte, which PostgreSQL text cannot hold, is never valid JSON, so the
  old reader skipped it. It is now kept AT ITS POSITION with `line` NULL, and its bytes stay in the archive.
  - The reader renders it as an empty line, which the read model skips as before.
  - `validation_log_line_check`: only an imported row may have no line.
- **Not UTF-8.** A file that is not UTF-8 anywhere, including in the NUL-free parts of a NUL line, still has no lines.
  That is the old `read_text` rule.
- **Tests.**
  - PGlite: valid records before and after a NUL line, through both installation paths. The positions are 1, 2 and 3
    with the middle line NULL; a rerun adds nothing; the archive bytes are unchanged; a NUL line with invalid UTF-8
    around it makes the whole file empty; an app row with no line is refused.
  - Hosted: the GET lists both neighbours of a NUL line, and a rerun adds nothing.
- **Results.** PGlite 56 tests; the Validation hosted tests (11) pass. The preview schema's 0018 was brought up to the
  revised migration.

### Codex implementation verdict (H-244)

**APPROVE.** The revised migration retains the position of a NUL-containing line and preserves the valid records on either side. The focused PGlite regression passed on both installation paths, including a repeat backfill. The hosted GET regression also passed. This resolves H-241.

## Grok notes
