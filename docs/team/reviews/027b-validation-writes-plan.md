# 027b — Plan: Validation, part 2 (the writes)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-235) — implementation next

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

## Grok notes
