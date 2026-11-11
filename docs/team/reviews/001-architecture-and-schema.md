# 001 — Architecture, data model and intake contract

Author: Claude · Branch: `main` (initial commit, docs + schema only) · Date: 2026-11-10 · Status: OPEN

## What changed
First design drop for the rewrite. No application code yet.
- `docs/ARCHITECTURE.md`: goals, merged Deal Flow pipeline, module layout, security, build order.
- `docs/DATA_MODEL.md`: how all existing data is migrated and kept, status mapping, identity resolution.
- `supabase/migrations/20261110000001_core_schema.sql`: schema v1 (schema `pz`, RLS on, no public grants).
- `contracts/intake_submission.schema.json`: the one contract every lead source (Grok first) submits through.

## Why
Mohamed's goals: Supabase instead of JSON; Deal Flow and Scout Intake as one section; Scout Bridge removed;
Grok as search/refine that delivers directly; same frontend; all existing data kept and better organized.

## Where to look (in reading order)
1. ARCHITECTURE.md §3 (pipeline + status table) and §4 (module rules).
2. The SQL: `candidates`, `observations`, `company_identifiers`, the partial unique index
   `candidates_one_open_per_company`, the append-only triggers, the lock-down block at the end.
3. DATA_MODEL.md "Identity resolution during import".
4. The intake contract: is it strict enough to keep junk out, loose enough for real Grok output?

## How it was tested
Intake schema checked with jsonschema 4.26 (Draft 2020-12): a valid Grok sample passes; an event without `event` and
an entity with empty `evidence` are refused. Note: `format` (date-time, uri) is only enforced when the validator runs
with a FormatChecker — the backend must enable it (a bad `submitted_at` passed without it). **The SQL has not been run yet** (no database connected);
it will be applied to a scratch Supabase branch/project before anything else is built on it.

## Open questions
1. psycopg 3 against the session pooler vs. supabase-py (PostgREST) for the backend — I chose psycopg for real
   transactions and advisory locks. Agree?
2. CHECK constraints instead of Postgres enums for status vocabularies — OK?
3. Is `pz.documents` (long-tail singleton state) an acceptable stepping stone, or should every context be modelled
   before import?
4. Keep the old 12-hex candidate ids as primary keys (deep links, Grok references) vs. uuid + `legacy_id`?

---

## Codex review
Verdict: **REQUEST CHANGES**. Static review of both design documents, the migration and the contract. Database execution remains unverified.

| # | Severity | File:line | Finding | Claude's answer |
|---|---|---|---|---|
| 1 | Blocking | Core migration, line 86 | Two companies with the same normalized name and different registries must be able to retain both name assertions pending review. The global identifier key rejects the second assertion. Give weak identifiers per-company uniqueness and retain global uniqueness for strong, namespaced identifiers. Test the two-company import and its replay. | **Fixed.** `company_identifiers` now has a surrogate key, `namespace` and a generated `strength`. Strong kinds (`domain`, `registry`, `legacy_key`, `submitter_key`) are globally unique per (kind, namespace, value); weak kinds (`normalized_name`, `alias`) are unique only per company. Registry/legacy/submitter keys must have a namespace. Same rule applied to `person_identifiers`. Tests: `supabase/tests/schema.test.mjs` "finding #1" — two companies "Nova Robotics GmbH"/"Ltd" with different DUNS both keep `nova robotics`; replay leaves counts unchanged; a domain or DUNS can't be given to the second company; the same number in another registry namespace is allowed. |
| 2 | Blocking | Core migration, line 351 | A parsed JSONB body cannot restore original JSON whitespace, key order or JSONL line endings. Keep recoverable source bytes for every archived file and verify a restore against the original SHA-256, including a small CRLF JSONL fixture. | **Fixed.** `legacy_documents.raw bytea not null` holds every file byte for byte (whole folder ~27 MB, so no Storage indirection); `parsed` is only a query convenience. CHECK constraints make the database refuse rows whose `sha256(raw)` or `octet_length(raw)` don't match; the table is append-only. Tests "finding #2": fixture `supabase/tests/fixtures/crlf_sample.jsonl` (UTF-8 BOM + CRLF + irregular whitespace and key order, protected by `.gitattributes -text`) is restored identical with the same SHA-256; mismatched hash/size refused; update/delete refused. |
| 3 | Blocking | Intake contract, line 11 and Architecture §3 | A registry connector following the documented single submission path fails validation on its origin. Specify which origins the external caller may assert and how trusted connectors and importers enter the shared service. **Fixed.** External envelope `origin` is now only `grok` or `manual`. Trusted callers use `IntakeService.submit_trusted(TrustedBatch)` with a server-set origin (`registry_scan`, `research`, `legacy_*`); every entity is validated against the same `#/$defs/entity`; a `TrustedBatch` with an external origin raises. External = all-or-nothing; trusted = per-entity (`partial`). Code: `backend/src/projectzero/dealflow/intake/{contract,service}.py`, `dealflow/sources/registry.py` (maps a real NIH record without inventing fields). Tests `backend/tests/dealflow/test_intake_contract.py`: each server-side origin refused externally with "server-side only" and nothing written; a registry batch with one good and one broken record → `partial`, 1 accepted, index 1 refused, replay → `duplicate`. ARCHITECTURE §3 updated. |
| 4 | Should-fix | Data Model, Identity resolution step 4 | Merging two legacy candidates leaves one canonical primary key. Define a lookup for each original ID, including its source namespace where needed. Verify both old links resolve to the same candidate after re-import. | **Fixed.** New `pz.candidate_aliases (namespace, alias_id) → candidate_id` with namespaces `candidate` (12-hex Deal Flow ids), `scout_intake` (`si-…`), `native_scout` (`sig-…`), and `pz.resolve_candidate(namespace, id)` as the single lookup. Every candidate gets an `own_id` row; absorbed ids get `merge`. Tests "finding #4": Deal Flow `4225c719f2f2` and intake `si-002-freda` both resolve to the survivor; re-import keeps 1 candidate / 2 aliases; unknown id → null. DATA_MODEL step 4 updated. |
| 5 | Should-fix | Intake contract, line 82 | URI format alone accepts a mailto URI as evidence, and a whitespace-only key fact satisfies minLength. Require a web URL with a host and meaningful text. Test both refusals through the submission validator. | **Fixed.** `$defs/web_url` = `format: uri` + pattern requiring `http(s)://` and a dotted host; used for evidence, website, profile and registration URLs. `$defs/statement` (key_fact, key_unknown, claim text) needs two words of ≥2 letters/digits; `$defs/name_text` needs a letter or digit. Patterns use explicit Latin/Greek/Cyrillic ranges, not `\p{…}`, so Python and ECMA engines agree. The validator always runs with `FormatChecker` (`jsonschema[format-nongpl]`). Tests: mailto/file/javascript/localhost/no-host/ftp/space/no-scheme URLs refused at `$/entities/0/evidence/0/url`; blank, whitespace-only, dots-only and single-letter key facts refused; accented names pass; `submitted_at: "yesterday"` refused. |

Keep psycopg 3 for the transaction boundary. Before signing off on the connection mode, use Grok's H-003 findings and demonstrate lock contention and release with two independent workers on the chosen route. CHECK constraints suit these status sets. Use pz.documents for singleton state with a stable key per document. Keep existing candidate primary keys for link compatibility and implement the merged-ID lookup in finding 4.

### Claude — revision 2 (2026-11-10 22:08 CET)

Evidence, all run locally:
- `cd backend && .venv\Scripts\python -m pytest` → **33 passed**; `ruff check`, `ruff format --check`, `mypy --strict` clean.
- `cd supabase/tests && npm test` → **17 passed** (PGlite 0.5.12 = Postgres in WASM, the migration applied from
  scratch, Supabase's `anon`/`authenticated` roles created first).
- Not yet verified: the migration on the hosted Supabase project, and the advisory-lock contention demo with two
  workers on the session pooler. Both need Mohamed's `.env`; they will be done before any import code lands.

Also changed after Grok's notes (below): additive optional entity fields `external_id` (stored as a strong
`submitter_key` identifier), `related_external_ids`, `flags`, `intent`, `source_scouts`, `scout_assessment`
(verbatim scout fields), `claims` with FACT/INFERENCE/UNKNOWN (FACT needs a URL), a `confidence` rubric, event
`starts_on` dates and EV/AX/P classes, envelope `cadence`, and `summary` up to 20,000 chars. The evidence-URL hard gate
stays until Mohamed decides (ARCHITECTURE §8 q2).

### Codex re-review of revision 2

**REQUEST CHANGES** on the intake implementation. The revised identifier indexes, byte archive and candidate aliases address the original database findings. I reran all 33 backend tests and 17 PGlite tests successfully. The hosted migration and session-pooler contention test remain pending.

1. **Blocking — registry.py, lines 40–42.** A JSON null DUNS value becomes the literal string `"None"`. It passes entity validation as a strong registry identifier. Two unrelated records with missing DUNS could therefore resolve to one company. Omit missing or structurally invalid values before conversion and test two such records.
2. **Blocking — intake/service.py, lines 87 and 113.** Two simultaneous deliveries can both pass the SHA lookup. The store's insert returns no indication of who won, so the loser can raise a unique violation or report acceptance twice. Use an atomic insert-if-absent returning its outcome for both entry points. Exercise an overlapping replay and verify one accepted result, one duplicate and one row.
3. **Should fix — intake_submission.schema.json, lines 43–57.** A real name such as 王小明 and a fact written entirely in Japanese fail the script-specific patterns. Preserve the nonblank requirement across writing systems and add coverage for a non-Latin name and fact.

The optional provenance, labeled claims and date-only event fields cover the gaps described by Grok. Verify the new linked-entity fields with the H-007 sample, including the handling of repeated external IDs and references to missing entities before resolution.

### Claude — revision 3 (2026-11-10 22:17 CET)

| # | Answer |
|---|---|
| 1 | **Fixed, in three layers.** (a) `registry.py` `_registry_value`: only `str`/`int` values; `None`, booleans, floats, lists and dicts are dropped, as are blanks and placeholders (`None`, `null`, `N/A`, `unknown`, `0`, `-`, `?`, …). (b) The contract refuses placeholder registry ids from **any** caller (`not` pattern on `registry_ids` values; must contain an ASCII alphanumeric). (c) DB constraint `company_identifiers_no_placeholder` refuses placeholders as any strong identifier (registry, domain, legacy/submitter key); weak aliases are unaffected. Tests: 14 missing/placeholder shapes dropped; two records without DUNS share no registry identifier; integer DUNS kept as text; 11 placeholder spellings refused by the contract; PGlite refuses 7 placeholders and a `none` domain. |
| 2 | **Fixed.** No more look-up-then-insert. `SubmissionStore` has a single method, `insert_if_absent(record) -> bool`, which both doors use. Postgres side: `pz.record_submission(...) returns (submission_id, inserted)` is `INSERT … ON CONFLICT (sha256) DO NOTHING RETURNING`, and on conflict it returns the winner's id with `inserted = false`, so there is never a unique violation. Execute is revoked from the API roles. Tests: 25× overlapping external replays (2 threads behind a barrier) → `[accepted, duplicate]` with 1 row; 25× overlapping trusted replays (3 threads) → `[accepted, duplicate, duplicate]` with 1 row; a store with *only* the atomic method proves the service never looks up first. PGlite: first call inserted, replay returns the same id with `inserted = false`; `Promise.all` of two calls → one true and one false, 1 row; `anon` can't execute. **Caveat:** PGlite is a single connection, so it serializes those calls. True two-connection contention can only run on the hosted project; it is pending together with the advisory-lock demo. |
| 3 | **Fixed.** Patterns are now script-neutral: a "meaningful character" is anything except whitespace, control characters and punctuation (ASCII, Latin-1, General Punctuation, CJK and full-width punctuation). `name_text` needs one. `statement` needs four with at least two adjacent, so `a b c d e f` is still refused while unspaced Chinese and Japanese pass. Tests (Python): 王小明, 株式会社テックラボ, Arabic, Greek, Korean and German names and facts pass; ideographic spaces, 。。。, em dashes, 、、、, ！？ and no-break spaces are refused. New `contracts/tests/patterns.test.mjs` runs the same cases on ECMA-262 (`u` flag) and agrees. |
| note | **Linked entities:** `cross_entity_issues()` (contract.py) refuses a repeated `external_id`, where the first one wins and later ones are refused with "already used by entity N". It also refuses a `related_external_ids` entry that names no entity in the delivery, and a self-reference. External deliveries are all-or-nothing; on the trusted path only the offending entity is refused. **H-007 sample:** Grok's real Cycle 008 delivery (13 entities, 2 with registry ids `che_uid` / `handelsregister`) validates with 0 issues, is accepted once and is a duplicate on replay. It is now a regression test. It has no `related_external_ids` yet, so the cross-entity rules are covered by synthetic tests only. |

Gate: `scripts/check.ps1` → ruff, format, mypy --strict, **pytest 129 passed**, ECMA pattern parity **4 passed**,
PGlite **21 passed** — ALL CHECKS PASSED. `tests/**` ignores RUF001 on purpose: the tests use look-alike Unicode
to prove it is refused.

### Codex re-review of revision 3

**REQUEST CHANGES** on trusted partial intake. The three H-008 fixes pass local review. I reran the gate successfully (129 Python, 4 ECMA and 21 PGlite tests, plus lint, formatting and typing). Independent database sessions and the hosted pooler lock remain unverified.

In `submit_trusted`, a valid A referencing B was counted as accepted even though B was refused for empty evidence. I confirmed the result through the service: partial, one accepted, only B refused. The reference check indexes all submitted IDs before considering refusals. It also attempts dictionary membership on invalid reference values, so an object inside the references array can raise TypeError and abort the batch. Validate the structure first, then propagate refusals through references until every accepted link resolves within the accepted set. Test A → B → invalid C alongside an unrelated valid entity, a malformed reference, and a valid mutually linked pair. Keep the unrelated entity and valid pair eligible.

### Claude — revision 4 (2026-11-10 22:24 CET)

**Fixed.** Your reproduction was right: references were checked against every submitted id, before any refusals were
applied. `cross_entity_issues(entities, already_refused)` now works like this:
1. **Structure first.** It only reads mappings, string `external_id`s and string references. Malformed values are
   skipped, never `in`-tested or hashed, because the schema already reports them on their own entity. No `TypeError`
   is possible.
2. **Unique ids.** The id-holder table is built only from entities that are *not* already refused for schema reasons;
   a repeated id held by a later entity is refused.
3. **Self-references** are refused.
4. **Propagation to a fixed point.** Any eligible entity with a reference whose target is missing, or held by a refused
   entity, is refused, and the loop repeats until nothing changes. Messages say which case applied: "which no entity
   in this delivery has" or "whose entity N was refused".

`submit_trusted` passes its schema refusals in, so the accepted set is closed: every link of every accepted entity
resolves inside it. The external path is unchanged (all-or-nothing).

New tests in `test_intake_contract.py`:
- Your exact case: A→B→C with C invalid, unrelated D, E with an object as a reference, and the pair F↔G. Result:
  `partial`, refused `[A, B, C, E]`, accepted 3 (D, F, G), with messages naming the refused target.
- A property check that the links of all accepted entities resolve within the accepted set.
- A repeated id plus a reference to that id: the reference resolves to the first holder, and only the repeat is
  refused.
- Junk entities (a string, `None`, an int id, non-list and non-string references): `{}` and no exception. Externally,
  an object reference is refused by the schema without raising.
- A 3-cycle with one invalid member: the whole cycle is refused and the unrelated entity is accepted.

Gate: ALL CHECKS PASSED (pytest **134**, ECMA 4, PGlite 21).

### Codex re-review of revision 4

**APPROVE** review 001. Trusted intake now excludes structurally invalid targets before resolving links and propagates refusals to dependent records. The regression tests cover chained refusals, malformed references and cycles, and confirm that unrelated records and valid mutual links survive. I reran the full quality gate successfully: 134 backend tests, 4 contract parity tests and 21 PGlite tests, plus lint, formatting and type checks. The hosted migration, independent-session contention and advisory-lock release through the chosen pooler remain integration checks for the database phase.

## Grok notes
Can a Monday hunt (full Operating Cycle, Scouts 01–07) and a Thursday pulse (Scouts 01, 02, 06, 07) be submitted as-is through `contracts/intake_submission.schema.json`? **Mostly, for leads that already have a public web URL, a clear name and a verifiable `key_fact`.** An empty `entities` array is valid, so a “nothing material” pulse is fine. It is **not** lossless, and some real scout findings cannot be submitted without inventing data or dropping fields the current Scout Intake Packet carries.

### Fields that cannot be filled reliably from public web / X research

- **`evidence` (required, minItems 1, each item requires `url` with `format: uri`).** This is the hard gate. Stealth / pre-company / social-only signals often have no stable official URL; Scout packets today may ship `evidence_urls: []`. Those entities will be refused. X/status URLs are usable when we have them; paywalled pages, LinkedIn URLs behind a login, and search-result links are poor or unusable evidence. I will not invent a URL to pass validation. `title`, `published_at` and `quote` are optional: title and a short quote are usually available once the page is open; a precise `published_at` often is not (omit rather than guess the day).
- **`website` (`format: uri`).** Optional, but identity resolution (DATA_MODEL.md) prefers domain. Many pre-company and stealth targets have no official site yet. I will omit it rather than guess.
- **`registry_ids`.** DUNS, Handelsregister and similar are rarely available from public web/X without a registry product. I should not invent them. When a public registry page is actually opened, I can fill it; that will be the exception.
- **`location.country` (`^[A-Z]{2}$`).** City is often known; country is usually inferable, but “DACH”, “EU”, “remote”, or a city-only string from a scout report cannot be forced into ISO 3166-1 alpha-2. I will omit `location` or omit `country` rather than guess. (If only `city` is sent, that is allowed by the schema.)
- **`stage` (enum).** Public sources often do not distinguish `pre_seed` vs `seed` vs “first funding.” I can fill this when a primary source states a round; otherwise `unknown` or omit. Do not infer a round from weak coverage.
- **`signal_date` (`format: date`).** Signals are often “this week” or “November 2026,” not a full YYYY-MM-DD. I will omit when the day is not evidenced, not invent `…-01`.
- **`founders[].profile_urls`.** X/personal sites can be filled when public. LinkedIn is often login-walled and is a weak identity source. I will only attach URLs I can actually open. Founder `role` is frequently unknown.
- **`thesis_fit`.** This is a reasoned note, not a public fact. I can carry a short qualitative Project A note when synthesis already has one; I will not invent fit.
- **`confidence` (`low` | `medium` | `high`).** Optional, but there is no rubric and it collapses the current FACT / INFERENCE / UNKNOWN labels. I cannot fill this “reliably” until the contract defines what each level means (or we map FACT→high, mixed/INFERENCE→medium, thin/UNKNOWN-heavy→low and write that down).
- **`recommended_action` (`review` | `watch` | `research` | `ignore`).** Does not match the living Scout vocabulary (CREATE NOW / UPDATE / MONITOR — DO NOT CREATE YET, plus attention states). Lossy map I can use until the contract is extended: CREATE NOW / IMMEDIATE DILIGENCE → `review`; MONITOR → `watch`; “needs more sourcing” → `research`; ARCHIVE would be `ignore` but those entities are not in the packet today. **UPDATE vs CREATE is not expressible** — which is acceptable if intake always creates `status=new` or attaches to an existing candidate, but the submitter cannot say which it intends.
- **`kind` vs current `recommended_object_type`.** Packet values include `person + pre-company opportunity` and `research spinout`, which are not in `{company, person, opportunity, event}`. A compound person+opportunity would need two entities (or one kind and lost structure). A spinout becomes `company` or `opportunity` and loses the spinout flag.
- **`event.starts_at` / `ends_at` (`date-time`).** Scout 07 usually has a calendar date, not a start time. I can set `kind=event` and put the city / registration URL in, but I will omit timestamps rather than invent `T00:00:00Z`. Official `registration_url` is often missing.

### What is missing that a research agent needs

These are present on today’s Monday/Thursday Scout Intake Packet (or in synthesis) and have **no field** in v1.0:

- **Provenance:** `source_scouts` (e.g. `["Scout 04", "Scout 06"]`). `origin` is only `grok` | `manual` | `research`, so every Grok delivery looks the same. Without scout ids, yield and convergence audits break.
- **Cycle / run identity at entity level.** `external_ref` is good for the whole delivery (`008`, `MW-2026-11-12`) but there is no per-entity run id or stable **dedupe key** (canonical company key, scout entity id). Whole-submission sha256 only dedupes an identical file. If identity resolution misses (no website, no registry, slightly different `name`), the same company will be offered twice. A submitter-side `external_id` / `dedupe_key` per entity would help the resolver.
- **Novelty and convergence:** `system_novelty`, `entity_convergence`, `independent_signal_convergence`, `duplicate_signal`. The backend cannot reconstruct these from name+URL alone.
- **Per-claim evidence quality:** no FACT / INFERENCE / UNKNOWN, no per-evidence confidence, no “this URL is secondary.” Only one optional entity-level `confidence`.
- **Event access classes:** `ev_class`, `ax_class`, `p_class`, and the short `why` / `action` lines. Only AX-0 / AX-1 events should be submitted; the contract cannot record why they were actionable.
- **Other packet fields with no home:** `venture_exposure`, `funding_visibility`, `company_status`, `attention_state`, `recommended_object_type`, cycle summary counts, and the Executive Brief / pulse text (only a 2000-character `summary`, which can hold a short pulse blurb but not a full Monday brief).
- **Sectors** have no controlled vocabulary; I can fill free strings when obvious, but they will be inconsistent unless we publish a list.

### Practical delivery rule (until the contract is extended)

I can produce a valid v1.0 JSON for both cadences by mapping packet → contract (`origin=grok`, `external_ref` = cycle id, entities with at least one real public URL, events as `kind=event`). I will drop or refuse entities that lack a public evidence URL rather than fabricate one, and I will put a one-line loss report (dropped fields / unsubmittable entities) in `summary` or in the handoff. Please consider additive, optional fields for `source_scouts`, an entity `external_id`, novelty/convergence flags, FACT/INFERENCE/UNKNOWN (or a confidence rubric), and event AX/EV class — plus relaxing `evidence.minItems` for explicitly provisional MONITOR items, or allowing a documented “no public URL yet” evidence type.
