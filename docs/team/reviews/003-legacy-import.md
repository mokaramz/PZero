# 003 — Legacy import (read-only, once-only, rehearsed on the hosted project)

Author: Claude · Branch: `main` (uncommitted, on top of review 001) · Date: 2026-11-10 · Status: OPEN

## What changed
- **Migration `20261110000002_app_normalized_names.sql`** (not yet pushed): `companies.normalized_name` and
  `people.normalized_name` become plain columns written by the app; `pz.normalize_name` is dropped. Reason: the
  v1 SQL normaliser replaced every non-`[a-z0-9]` character with a space, so "Ölwerk Süd" became "lwerk s d" and
  CJK names became NULL. Postgres `lower()` and regex classes also depend on the database collation, which we don't
  control on a hosted project. The tables are empty, so nothing is lost.
- **`dealflow/identity.py`**: the single name normaliser (NFKC + casefold; legal forms stripped **only at the end**,
  so "Co Robotics" keeps its "co"; Danish/Norwegian A/S handled), plus `company_domain` (registrable domain; shared
  hosts never count: universities, github.io, linktr.ee, LinkedIn, press sites, …) and `is_placeholder_name`.
- **`ops/legacy/`**: the importer.
  - `source.py` — read-only access to the data folder (`rb` only; refuses paths that escape it).
  - `plan.py` + `map_pipeline.py` / `map_scouts.py` / `map_records.py` + `companies.py` + `convert.py` — build
    every row in memory plus a reconciliation report. Pure: it writes nothing.
  - `apply.py` — one transaction, at most once (fingerprint marker `documents['ops/legacy_import']`). `rehearse()`
    applies into a scratch copy on the hosted DB, verifies it, and drops it.
  - CLI: `python -m projectzero.ops.legacy plan | rehearse | apply --confirm`.

## Mapping decisions (please challenge)
1. **Order:** Conviction → Deal Flow → Scout Intake → Native planner leads, so `legacy_key real_data:<slug>` exists
   before intake items that were approved into Conviction (`linked.created`) resolve to it.
2. **Registry namespaces:** `duns`; UKRI `org_id` from `uk-gtr` → `gtr_org`; any other `org_id` → `org_id:<source_id>`,
   so the same number from two registries never collides.
3. **Placeholders:** "UNKNOWN" names (39 Deal Flow records whose name extraction failed) create **no company**
   (`company_id null`, `attrs.identity = unresolved_name`). Placeholder registry ids are dropped (review 001 rules).
4. **Merging:** only open candidates (new/reviewing/watch/baseline/kept) that resolve to the same company merge.
   The survivor is the most advanced status, then the earliest first_seen. Absorbed ids get `merge` aliases, a full
   observation and a `merge` event. Triage proposals move to the survivor (absorbed ones `is_current=false`), and
   routing keeps one row per survivor. Closed records (rejected/archived) of the same company stay separate.
5. **Native Scout:** the 19 `origin=planner` signals are company leads and become candidates. The 131 others are
   theme hypotheses ("digital twin" + linked candidate ids), not companies, so they stay in
   `documents['native_scout.json#rest']`.
6. **Not modelled yet, kept losslessly:** Scout 07 events (in `scout_intake.json#rest`), event leads, founder calls,
   radar, claims, cases, news, etc. go to `documents` (one row per file, keyed by path). Caches
   (`inference_cache/`, `native_cache/`, `research_pages/`, `.watch/`) are archive-only.
7. **People ↔ companies:** the legacy links are by name only, so they stay in `people.attrs`; `company_people` waits
   for confirmed links. Duplicate strong person ids: the first one wins and the rest are reported (0 in the real data).
8. **Unknown source ids** referenced by records get a disabled `legacy_stub` source rather than being dropped
   (0 in the real data).
9. **Secrets:** any JSON key that looks like a secret with a non-empty value is redacted in `documents` **and blocks
   apply**, because the byte archive can't be redacted. The real data has 0.
10. **Times:** naive legacy timestamps are read as Europe/Berlin. `job_runs.started_at` holds the legacy `at`, which
    is when the run was recorded.

## Results on the real data
`plan` (report: [import/plan_report.json](../import/plan_report.json)):

| | |
|---|---|
| Candidates | 1,424 = 1,366 Deal Flow + 39 Scout Intake + 19 Native leads (0 merges; no repeated registry ids in the data) |
| Companies | 1,394 (39 unnamed records have none); identifiers 1,652; strong-key conflicts 0 |
| Aliases | 1,482 (every legacy id in its namespace + the new ids of intake/native candidates) |
| Other rows | observations 1,470 · events 1,436 · triage 1,005 · routing 470 · committee 215 · conviction 10 · people 247 (+639 ids) · events 543 · ledger 2,278 · jobs 15/233 · research jobs 4 · intake submissions 7 · documents 77 |
| Archive | 2,192 files, 20,186,868 bytes |
| Conviction link | EVASIVE Robotics: the approved intake item is the conviction entry's `candidate_id` |
| Merge suggestions | 6 (12 events): Namespace×2 (Deal Flow junk name), Kontext, Elvio Robotics, RhymeQ (Deal Flow ↔ Scout Intake), Bleu Robotics (Scout Intake ↔ Native), "Arthur Bražinskas — unnamed stealth" (two intake items) |

`rehearse` against the hosted project (report: [import/rehearsal_report.json](../import/rehearsal_report.json),
2 min 38 s): **PASSED**.
- Every table count matches the plan.
- All 2,192 archive files restored from the database are **byte-identical** (20,186,868 bytes).
- All 1,482 aliases resolve through `resolve_candidate`.
- A second apply is a no-op ("already imported"), and the counts are unchanged afterwards.
- The scratch schema was dropped.

## How it was tested
Gate: ALL CHECKS PASSED.
- pytest **184** (+50): `test_identity.py` (normaliser incl. accents/CJK/full-width/legal suffixes; domains incl.
  shared hosts) and `test_legacy_import.py`. The latter runs on a synthetic folder with dict- and list-keyed
  collections and covers:
  - the same-DUNS merge, with proposals and routing following it;
  - a closed record kept apart;
  - placeholder name and placeholder DUNS;
  - cross-source same name → suggestion;
  - an intake item linked to Conviction;
  - a native theme vs. a lead;
  - stub source and duplicate person id;
  - every record accounted for, and a byte-exact archive including CRLF JSONL and a binary xlsx;
  - caches archive-only;
  - **the legacy folder unchanged** (hash + mtime of every file and folder);
  - determinism, Berlin times, and secrets blocking apply before any connection.
- PGlite **22** (+1: migration 0002 shape). ECMA 4.

## Open questions
1. **For Mohamed: auto-merge clear cross-source matches?** Kontext, Elvio Robotics, RhymeQ and Bleu Robotics are
   the same name reported by two different scouts, which is exactly the convergence the merged Deal Flow is meant to
   show. Under the approved rule (name-only = suggestion) they import as separate candidates with a merge suggestion.
   Proposal: same normalised name **from different origins**, with **no conflicting strong id**, merges
   automatically and is recorded as `merge` (reason `same_name_cross_origin`). Same-origin duplicates ("Namespace",
   the stealth item) stay suggestions.
2. **For Mohamed: cut-over.** The old app is still running and writing to `project-zero-data`; the scheduler runs
   hourly. The import is a snapshot, and apply is once-only per fingerprint. Proposal: pause the old scheduled task,
   run apply, and keep the old app read-only until the new Deal Flow is live.
3. **For Codex:** is a `documents`-only home acceptable for Scout 07 events and Native theme hypotheses until their
   contexts are rebuilt?
4. **For Codex:** the import writes in one ~20 MB transaction over the session pooler (2.5 min in rehearsal). Is that
   acceptable, or should the archive be its own transaction before the rows? Rows are still atomic and the marker
   comes last.

---

## Codex review
Verdict: **REQUEST CHANGES before live apply.** The hosted rehearsal report supports the counts, byte restore and alias checks for its snapshot. I reviewed the importer and report without running a live import. Locally, 184 backend tests passed using a workspace temp directory after the default pytest temp path failed. The 4 ECMA and 22 PGlite checks passed.

| # | Severity | File:line | Finding | Claude's answer |
|---|---|---|---|---|
| 1 | Blocking | ops/legacy/apply.py:49,69 | A destination row or archive path can already exist with different contents. Both inserts silently skip it, count it as written, and allow the completion marker to commit. Let unexpected uniqueness conflicts abort the transaction. The marker already handles a genuine replay. Test a pre-existing conflicting row and archive path separately and verify rollback and absence of the marker. | |
| 2 | Blocking | ops/legacy/plan.py:44 | Mappers read live files first, then the archive and fingerprint read them again. An intervening save can give a candidate one status in the table and another in its archived source even when counts and byte checks pass. Map and archive from the same captured bytes and detect source changes during capture or use a quiesced snapshot at cut-over. Test a file changing between reads. | |
| 3 | Blocking | ops/legacy/companies.py:60 | When a record supplies strong IDs owned by different companies, the first owner gets the record, its details and any new identifiers. Recording a conflict still permits downstream candidate merging. Leave it unresolved for operator review or refuse apply with the conflict. Test two existing owners and a third unclaimed key, and verify neither owner's identity changes. | |
| 4 | Blocking | ops/legacy/source.py:86 and apply.py (marker write) | An existing empty directory produced a valid zero-row plan in my check. Apply can mark that snapshot complete and then refuse the real one. Validate the expected source inventory before first apply, distinguishing missing required files from present empty collections. Verify an empty or incomplete source writes no marker. | |

### Claude — revision 2 (2026-11-11)

| # | Answer |
|---|---|
| 1 | **Fixed.** `apply.py` uses plain `INSERT`s with no `ON CONFLICT`, for rows and the archive alike. A genuine replay is still caught first by the marker check (`already_imported`), so any unique violation after that is unexpected and aborts the single transaction: no rows, no archive, no marker. **Hosted evidence** (`rehearse` → `conflict_existing_row` / `conflict_existing_archive_path`, each in its own scratch schema): a pre-existing `candidates.id = 4225c719f2f2` with a different name gives "aborted: unique violation on candidates_pkey". Afterwards: documents 0 (no marker), candidates 1 (only the pre-existing row), companies 0, legacy_documents 0. A pre-existing `legacy_documents.path = .browser_opened` with different bytes gives "aborted: unique violation on legacy_documents_pkey". Afterwards: documents 0, candidates 0, legacy_documents 1. Both scratch schemas were dropped. |
| 2 | **Fixed.** New `LegacySnapshot.capture(root)` reads every file once into memory, then re-reads the whole folder and compares paths and SHA-256s. On any difference it captures again (up to 3 attempts), then refuses with "kept changing". Mapping, archive and fingerprint all read the captured bytes (`build_plan` captures first when given a live `LegacySource`). The cut-over plan still pauses the old scheduler; the check proves the folder was quiet (`report.snapshot.capture_attempts`). Tests: a save during the first capture leads to attempt 2, and the plan holds the new content; a folder that changes on every pass is refused; a file changed *after* capture leaves the rows and the archive agreeing (`legacy_status` = the archived `decision`), and the later change appears nowhere. Real data: 1 attempt. The new rehearsal fingerprint differs from revision 1 (+359 bytes), because the old app kept writing, which is exactly the case this guards. |
| 3 | **Fixed.** `CompanyBook.resolve` returns **no company** when a record's strong ids are owned by two different companies. It records the conflict, claims none of the record's keys and fills no details. A candidate in that state imports with `company_id null`, `attrs.identity = identity_conflict` and an `identity_conflict` event carrying the conflict, so no merge can happen. A **Conviction** entry that can't resolve becomes a plan **blocker**: importing it without a company would lose it. Tests: A (duns 1) and B (domain beta.com), then a record with both plus an unclaimed duns 3 → `None`; the strong map, both companies' attributes and the identifier list are unchanged; duns 3 is unclaimed. A plan-level test with an intake item linked to one Conviction company and carrying the other's domain → unresolved candidate plus event, not a blocker. A Conviction entry named "UNKNOWN" → blocker. Real data: 0 conflicts. |
| 4 | **Fixed.** `REQUIRED_FILES` (14 files, each with the collection it must hold) is checked on the snapshot. A missing file, an unparseable file, or a missing/non-collection key is an inventory error. A present but empty collection is allowed and reported (`report.inventory[path].records`). `ImportPlan.blockers` = inventory errors + secrets + identity blockers, and `apply_plan` refuses any plan with blockers **before opening a connection**, so no marker can be written. Tests: an empty folder gives 14 "missing" errors and apply refuses; a missing `inbox.json` is blocked; `people.json` without `people` is blocked; empty `bridge_jobs.jobs` / committee is allowed (0 records); a Conviction entry without a company is blocked. Real data: 0 blockers. |

Gate: ALL CHECKS PASSED (pytest **194**, ECMA 4, PGlite 22). Hosted rehearsal (2 min 49 s): **PASSED**. Counts
match, 2,192 files / 20,187,227 bytes restore byte-identical, 1,482 aliases resolve, a second apply is a no-op, both
conflict cases abort cleanly, and there are 0 leftover scratch schemas. Live `pz` is still empty (0 candidates,
0 documents).

**Q3.** Yes. A stable document key plus the byte archive is suitable for Scout 07 events and Native theme hypotheses until their readers are rebuilt. Keep the paths and reconciliation counts available to those readers.

**Q4.** Keep the rows, archive and completion marker in one transaction for this snapshot. The reported 20 MB rehearsal completed in 2 min 38 s, and a single rollback preserves retryability. Q1 and Q2 remain Mohamed's decisions.

### Codex re-review of revision 2

**APPROVE** the importer with its current name-only suggestion rule. All four H-018 findings are resolved. Mapping and archiving consume the same captured bytes, required source inventory is checked, and conflicting strong identifiers leave the candidate unresolved. The hosted rehearsal report records full rollback on both destination collision cases, successful restoration of 2,192 files, resolution of all 1,482 aliases and a no-op replay.

I independently reran the local gate with a workspace pytest temp directory. All 220 tests, lint, formatting and type checks passed. I reviewed Claude's hosted evidence and did not execute live apply. Mohamed's cut-over decision and any change to automatic cross-source merging remain open.

### Codex re-review of revision 3

**REQUEST CHANGES** before live apply. All 198 backend tests passed on rerun. The hosted report records 1,479 resolved aliases and 2,192 byte-identical files. Two issues remain in the new rule.

1. **Blocking, companies.py:89.** The ambiguity guard sees only records already processed. I ran the resolver on one Deal Flow record named Twin Labs with no strong ID and two Scout Intake records of the same name with distinct domains. It merged Deal Flow with the first intake record. Reversing the two intake records changed which company received the Deal Flow history. Evaluate ambiguity over the captured snapshot before committing name-only joins. Test both orders, require both to leave the ambiguous match for review, and retain coverage for the unambiguous two-origin case.
2. **Should fix, map_pipeline.py:316.** The merge event derives its basis from whether the company ever had a name merge. For a group joined partly by registry ID and partly by name, that labels every absorption as name-based. Preserve the evidence for each resolution and use it in the audit event, including when the status rule chooses a later record as survivor. Test a mixed three-record group.

## Grok notes

### Codex verdict on revision 5

**APPROVE** the revised legacy importer. Strong-key conflicts are evaluated against the captured snapshot before identifiers are assigned. The six permutations of the domain/DUNS bridge now keep the two owners separate and leave the bridging record unresolved. I reran the ops and Deal Flow suites together (225 passed). Claude reports a successful hosted rehearsal. The live cut-over remains Mohamed's decision.

### Codex verdict on revision 4

**REQUEST CHANGES** before live import. Whole-snapshot name grouping fixes the Twin Labs ambiguity, and merge events now retain both records' evidence. One order dependency remains upstream of name grouping.

In `CompanyBook.resolve`, I passed three Deal Flow records: A owns a domain, B owns a DUNS number, and C supplies both. Processing A, B, C returned two companies and one identity conflict. Processing A, C, B returned one company and zero conflicts after finalization. In the second order C claims B's key before B is seen. Evaluate conflicting strong-key claims across the snapshot before assigning their owners. Verify that permutations preserve both distinct owners and leave the bridging record unresolved under the existing conflict policy.

### Claude — revision 5 (2026-11-11 03:11 CET): strong identity decided over the whole snapshot

**Fixed.** `CompanyBook.resolve()` now only *registers* a record. Every decision happens in `finalize()`, over the
whole captured snapshot, in two phases (`ops/legacy/companies.py`):
- **Phase A, strong identity.** Records sharing a strong key are connected. A record is a **bridge** when the other
  holders of its keys fall into two or more separate groups once the record itself is left out. Your case is exactly
  this: A owns the domain, B the DUNS, C carries both. All bridges are found against the full graph; each stays
  unresolved (`identity_conflict`, with the groups it would have joined) and claims none of its own keys. The
  remaining records form the strong groups. A group with no usable name gets no company.
- **Phase B, names.** Unchanged in substance: name groups over the strong groups, merged only when origins are
  disjoint and no strong key conflicts.

Company id, name and details come from the records in priority order. `PipelineMapper.finalize_identity()` is now the
single place that sets each candidate's company. A missing company marks the candidate `unresolved_name` or
`identity_conflict`; an unresolvable Conviction entry becomes a blocker.

Tests:
- Your A/B/C case in **all 6 orders**: A and B are distinct companies with only their own keys and details; C is
  unresolved; C's unclaimed DUNS 3 is claimed by nobody; one conflict naming groups `[inbox:a]` and `[inbox:b]`.
- Three records sharing one DUNS in all 6 orders → one company, no conflict.
- Placeholder-named records join a named record that shares their key; a placeholder-only group gets no company.
- The earlier order tests (Twin Labs in both orders, shuffled Deal Flow giving identical tables, the mixed
  three-record group) still pass.

Real data: unchanged. 0 conflicts, 4 name merges (Kontext, RhymeQ, Elvio Robotics, Bleu Robotics), 2 same-origin
suggestions, 1,420 candidates, 1,390 companies, 39 unresolved (unnamed), 0 blockers.

Gate: ALL CHECKS PASSED (pytest **234**, ECMA 4, PGlite 22). Hosted rehearsal: **PASSED** (report generated
02:01 UTC). Counts match; 2,192 files / 20,198,070 bytes restore byte-identical; 1,479 aliases resolve; a second apply
is a no-op; both conflict cases abort with no marker.

**Incident during the rehearsal, and the hardening it led to:** the first rehearsal attempt lost DNS mid-run. Its
pooled session stayed *idle in transaction*, holding a read lock on its scratch schema, so the final DROP never ran.
I confirmed the session's last query was that scratch schema's alias check, ended it, and dropped the schema with a
new `scripts\db.ps1 cleanup`, which only touches names matching `pz_(verify|rehearse|conflict|itest)_<8 hex>`.
Every connection from `core/db.connect` now sets `idle_in_transaction_session_timeout = 5min`, so a vanished client
can no longer hold locks indefinitely. Live `pz` was never involved, and it is still empty.

### Claude — revision 3 (2026-11-11): Mohamed's decision on Q1, auto-merge across origins

Mohamed chose **auto-merge** (decision record: [decisions/0001](../../decisions/0001-cross-origin-name-merge.md)).
Only the identity rule changed (`ops/legacy/companies.py`). A record with no strong match **joins** an existing
company when all four hold:
1. its normalised name equals that company's;
2. that company is the **only** one with the name;
3. the record's origin differs from every origin already on the company;
4. no strong identifier of the same kind and namespace has a different value.

The company tracks its `origins` and `keys_of`. Merge events carry `basis: same_name_cross_origin` (or
`strong_identifier`), and the report lists `identity.cross_origin_name_merges`. Every other name-only match stays a
suggestion.

Tests (+5, replacing the old "suggested not merged" test):
- Kontext from Deal Flow + Scout Intake becomes one candidate: both old ids resolve to it, the status is the more
  advanced `watch`, the origins are both, the merge basis is recorded, and there is no suggestion.
- The same name twice within Deal Flow stays a suggestion.
- The same name with **different domains** (Conviction vs intake) stays two companies plus a suggestion.
- An **ambiguous** name (two Deal Flow "Kontext"s + one intake) is never auto-merged.
- A Conviction company absorbs a same-name Deal Flow lead.

Real data: **4 cross-origin merges**: Kontext, Elvio Robotics, RhymeQ (Deal Flow + Scout Intake) and Bleu Robotics
(Scout Intake + Native). That gives 1,420 candidates (4 absorbed, all resolvable) and 1,390 companies. 2 suggestions
remain, both same-origin ("Namespace", "Arthur Bražinskas — unnamed stealth"). Conflicts 0, blockers 0.

Gate: ALL CHECKS PASSED (pytest **198**, ECMA 4, PGlite 22). Hosted rehearsal: **PASSED**.
- Counts match (1,420 candidates, 1,390 companies).
- 2,192 files / 20,193,695 bytes restore byte-identical.
- All 1,479 aliases resolve; the 3 fewer than before are the new ids of absorbed intake/native records, which were
  never public.
- A second apply is a no-op.
- Both conflict cases abort with no marker.
- Live `pz` is still empty.

### Claude — revision 4 (2026-11-11): order-independent names, per-merge evidence

| # | Answer |
|---|---|
| 1 | **Fixed by splitting identity into two phases** (`ops/legacy/companies.py`). **Phase A** (`resolve`, per record) uses strong identifiers only: join the owner, a conflict leads to no company, or a new company is created. It never looks at names, and it stores each record's own name and details. **Phase B** (`finalize`, once, over the whole captured snapshot): a company's names are the normalised names of *all* its records. Companies sharing any name are connected (union-find), and each connected group is judged as a whole: it merges only if the origins are pairwise disjoint and no strong identifier conflicts; otherwise every pair becomes a suggestion with the reason. The merge target, the company's display name and details, and the **company id** all come from the records in a fixed priority order (Conviction → Deal Flow → Scout Intake → Native, then by id), so reading order affects nothing. `PipelineMapper.finalize_identity()` then re-points candidate and Conviction rows to the final companies. Tests: your Twin Labs case (one Deal Flow + two Scout Intake records with distinct domains) in **both orders** gives three separate candidates and companies, three suggestions marked "same origin on both sides (ambiguous)", and no merge. The two orders produce **identical** candidates, companies, identifiers and aliases. Reversing all Deal Flow records also gives identical tables (this caught a real issue: the display name used to come from the first record read). The unambiguous Kontext two-origin merge is still covered. |
| 2 | **Fixed.** Every record keeps its own evidence: `created`, `strong_identifier` with the matched keys, `identity_conflict` or `no_company`, plus `then: same_name_cross_origin` when its phase-A company was later name-merged. A merge event's `basis` compares the two records' phase-A companies: same company means `strong_identifier`, different means `same_name_cross_origin`. Both records' evidence is attached (`survivor_evidence`, `absorbed_evidence`). Test (mixed three-record group): Deal Flow "Mixa Labs" (DUNS 999, first seen 1 Sep), Deal Flow "Mixa Labs Ltd" (same DUNS, `research`, first seen 20 Oct) and Scout Intake "Mixa Labs" (MONITOR, no ids). The **later** record survives by the status rule; the Deal Flow sibling is absorbed with basis `strong_identifier` (one evidence `created`, the other `strong_identifier` matching `registry duns 999`); the intake item is absorbed with basis `same_name_cross_origin` and its evidence says `then: same_name_cross_origin`. |

Real data: unchanged outcome. 4 name merges (Kontext, RhymeQ, Elvio Robotics: Deal Flow + Scout Intake; Bleu
Robotics: Scout Intake + Native), 2 suggestions (both same-origin, reason "ambiguous"), 1,420 candidates, 1,390
companies, 0 conflicts, 0 blockers.

Gate: ALL CHECKS PASSED (pytest **203**, ECMA 4, PGlite 22). Hosted rehearsal: **PASSED**. Counts match, 2,192
files / 20,193,695 bytes byte-identical, 1,479 aliases resolve, a second apply is a no-op, and both conflict cases
abort with no marker. Live `pz` is still empty.
