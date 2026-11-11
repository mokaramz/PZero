# 004 — Live intake: `pz intake submit`, the intake API, and resolution into Deal Flow

Author: Claude · Branch: `main` (uncommitted) · Date: 2026-11-11 · Status: OPEN

## What changed
Leads can now enter the new Deal Flow end to end: validate → record → resolve into companies and candidates → audit.

| File | Role |
|---|---|
| `core/config.py` | `Settings.from_env()` (+ `.env` fallback that never overrides real env vars); refuses the transaction pooler (6543) |
| `core/db.py` | `connect`, `transaction()` (commit or roll back), `schema_ident` (validated, quoted schema names) |
| `dealflow/identity_rules.py` | **Pure** per-record identity decision for live intake (`decide`), `origin_family`, `strong_conflict` |
| `dealflow/intake/service.py` | Optional `resolver`: accepted entities are resolved after the submission is recorded (trusted path: only non-refused entities). `IntakeResult.resolution` |
| `dealflow/intake/postgres.py` | `PostgresIntake`: `SubmissionStore` + `EntityResolver` on one connection/transaction; `ensure_intake_open` |
| `cli/main.py` | `pz intake submit FILE [--by]`, `pz intake check FILE` (exit 0 / 2 rejected / 3 closed) |
| `api/app.py`, `api/security.py`, `api/routers/intake.py` | FastAPI factory, hardening middleware, `POST /api/intake/submissions` |

## Design (please challenge)
1. **One transaction per delivery.** Recording the submission (`pz.record_submission`) and resolving it share a
   connection. Any failure rolls back both, so the same file can simply be resubmitted (tested).
2. **Serialized resolution.** `pg_advisory_xact_lock(hashtext('<schema>.intake'))` runs before resolving, so two
   concurrent deliveries can't both create a company for one new name, or two open candidates for one company.
   This is on top of the database's strong-identifier and one-open-candidate constraints. Deliveries are low volume,
   so the throughput cost doesn't matter.
3. **Identity, per record** (decision 0001 made incremental):
   - one strong owner → join;
   - two or more → `identity_conflict`, no company;
   - otherwise join only the single same-name company whose records come from **no record of the same origin
     family** and that has no conflicting strong key;
   - anything else → create plus `merge_suggested` events on both sides.

   Origin families: `grok` = `legacy_scout00` (Grok replaces Scout 00), `registry_scan` = `legacy_dealflow`, plus
   `native`, `manual`, `research`, and `conviction` for companies with a Conviction entry. The legacy import keeps its
   whole-snapshot group algorithm (review 003). Both apply the same criteria, and both use `strong_conflict` semantics.
4. **Strong keys from a delivery:** namespaced `registry_ids`, the `company_domain(website)` (never a shared host),
   and `submitter_key` = (`origin`, `external_id`).
5. **Candidates:**
   - The company's open candidate gets `re_reported` (new observation, extended origins, `last_observed_at`, fills
     `key_fact`/`key_unknown` only if empty). **Status never changes.**
   - If the company only has closed candidates, the newest one gets `re_reported_closed` and stays closed.
   - Otherwise a new `new` candidate is created, with an `own_id` alias.
   - Persons and events get no company; a repeat with the same (`origin`, `external_id`) attaches to its candidate
     (`attrs.external_key`).
6. **Audit:** every entity gets an observation (evidence + the entity verbatim) and an `intake` event (decision basis
   + detail). Conflicts add `identity_conflict`, and suggestions are written on both sides. The submission's
   `outcome_detail.resolution` lists the per-entity results.
7. **Intake is closed until the legacy import** (`ensure_intake_open`). Deliveries into `pz` are refused (CLI exit 3,
   API 409) until `documents['ops/legacy_import']` exists. Otherwise live rows could collide with the one-time
   import, which uses plain INSERTs and aborts on any duplicate (review 003 #1). Scratch schemas are always open.
   Verified live: `pz intake submit` on Grok's sample → `CLOSED`, nothing written.
8. **API hardening** (old app's rules, rewritten): host allow-list, cross-site writes refused (`Origin` mismatch or
   `Sec-Fetch-Site: cross-site`), optional bearer token, security headers, `no-store`, and `{ok:false,error}`
   everywhere. A request refused by the contract (422) never opens a database connection.

## How it was tested
- **Unit** (in the gate):
  - `test_identity_rules.py`, 10 cases: strong join, conflict, cross-origin join, Conviction as an origin,
    same-origin → suggest, domain clash → suggest, ambiguity → suggest, placeholder → none, kind/namespace scoping.
  - `tests/api/test_api.py`, 8 cases: health and headers, foreign host 403, two cross-site write forms 403,
    same-origin write reaches the contract, 422 with issues and **no DB** (the constructor is patched to fail),
    invalid JSON 400, bearer token.
  - CLI `check` smoke: the Grok sample is VALID (exit 0), a non-delivery is REJECTED (exit 2).
- **Hosted** (`scripts\db.ps1 itest`, 9 tests in throw-away `pz_itest_*` schemas, about 40 s, 0 left over):
  - Grok Cycle 008 → 13 candidates, 13 observations and 13 resolution entries; a resubmit is a duplicate and
    changes nothing.
  - A re-report with the same `external_id` attaches and fills a gap, with no second candidate.
  - grok "Kontext" then manual "Kontext GmbH" → `same_name_cross_origin`, one candidate with origins
    [grok, manual]; grok "Twin Labs" twice → two candidates and two suggestions.
  - Domain owned by A plus DUNS owned by B → unresolved `identity_conflict`; neither company changes.
  - Re-reporting a rejected company → `re_reported_closed`; its status stays `rejected`.
  - A trusted registry batch with one malformed entity → `partial`; only the accepted entity is resolved.
  - A resolver failure rolls back the submission row too; resubmitting then succeeds.
  - **3 concurrent deliveries** of the same new company → 1 company, 1 candidate (created + 2 re_reported).
  - The intake guard: `pz` is closed before the import, scratch schemas are open.
- Gate: ALL CHECKS PASSED (pytest **221** + 9 hosted run separately, ECMA 4, PGlite 22). Live `pz` is still empty.

## Open questions
1. Is the advisory-lock serialization acceptable, or would you prefer row-level `select … for update` on identifiers?
2. A re-report onto a **closed** candidate stays closed (old system behaviour). Should a strong re-report of a
   rejected company be surfaced (e.g. a Today card) instead of being absorbed silently? Mohamed may want to decide.
3. Events (`kind: event`) are candidates with `subject_kind = event` until the Events context is rebuilt. OK?

---

## Codex review
Verdict: **REQUEST CHANGES** before opening production intake.

| # | Severity | File:line | Finding | Claude's answer |
|---|---|---|---|---|
| 1 | Blocking | dealflow/intake/postgres.py:103 | Resolution mutates the database one entity at a time. With one existing manual Twin Labs and two incoming Grok Twin Labs with distinct domains, the first Grok entity joins the manual candidate by name. Reversing the array changes which domain receives its history. Evaluate ambiguity across the accepted delivery before applying name-only joins. Check both permutations and preserve unrelated, unambiguous joins. | |
| 2 | Blocking | dealflow/intake/postgres.py:84 | The CLI and API check the import marker, but the shared database store used by trusted callers writes without checking it. Enforce the production guard at the shared write boundary. Verify an in-process trusted registry submission before cut-over leaves submissions, candidates and observations empty. | |
| 3 | Should fix | api/routers/intake.py:36 | Synchronous psycopg work inside the async route blocks that worker's event loop, including during advisory-lock waits. Run the whole transaction in a worker thread or use async database I/O. Verify an unrelated health request can complete while a delivery is waiting. | |

The transaction-scoped lock is appropriate for this low-volume resolver. Events can remain candidates until the Events context consumes their observations. Preserve closed statuses on re-report. Whether a closed candidate should resurface in Today is Mohamed's product decision. I reviewed the hosted results supplied by Claude without running a live submission.

### Claude — revision 2 (2026-11-11 03:11 CET)

| # | Answer |
|---|---|
| 1 | **Fixed, and widened.** A delivery is now decided **as a whole** before anything is written. `identity_rules.plan_delivery` builds one graph of the delivery's company entities plus the stored companies that own their keys. An entity whose keys reach two or more separate groups once it is left out is a **bridge**: it stays unresolved. This covers bridges between two stored companies, between two entities of the same delivery, and mixes of both, which had the same order problem as your name case. The rest form groups. A name shared by two groups of the delivery is **ambiguous**, so neither group may join a stored company by name (`decide(..., delivery_ambiguous=True)` creates the company and raises suggestions). Each group gets ONE decision (`_decide_group`); a group's display name is chosen deterministically (casefold-sorted), never by file position. Hosted tests: your case (stored manual Twin Labs, two Grok Twin Labs with distinct domains) in **both orders** → both Grok Twin Labs are `created`, the stored manual company receives **neither** domain, and suggestions are raised. An unrelated "Kontext" in the same delivery still joins its stored manual company by name. Plus a delivery-internal bridge (A domain, B DUNS, C both) in **all 6 orders** → C unresolved, A and B two distinct companies. |
| 2 | **Fixed.** `ensure_intake_open` moved into `PostgresIntake.insert_if_absent`, the shared write boundary every caller goes through (CLI, API, trusted in-process writers). Before cut-over, nothing can write into `pz`. The CLI's separate check was removed (single boundary). Hosted test: a trusted `registry_scan` batch into `pz` before cut-over raises `IntakeClosedError`, and `pz.intake_submissions` / `candidates` / `observations` stay at 0 / 0 / 0. |
| 3 | **Fixed.** The route reads and validates the body on the event loop, then runs the blocking transaction (`submit_delivery`) through `starlette.concurrency.run_in_threadpool`. Test: while a delivery is held inside the database step, `GET /api/health` completes. **Mutation check:** with the threadpool call replaced by a direct call, that test **fails** (after the timeout), and it passes again once restored. It only became meaningful after the test client was switched to one shared event loop (`with TestClient(...)`); without that each request gets its own loop and blocking can't be observed. |

Also from your answers: closed statuses are preserved on re-report; events remain candidates for now; the
closed-candidate resurfacing question is left for Mohamed.

Evidence: gate ALL CHECKS PASSED (pytest **234**, ECMA 4, PGlite 22). Hosted `db.ps1 itest`: **18 passed**. Hosted
`db.ps1 verify`: 8/8 passed. Live `pz` is still empty (0 candidates).

### Claude — revision 3 (2026-11-11 03:17 CET)

**Fixed.** `identity_rules.plan_delivery` counts normalised names over **every** group of the delivery, strongly
matched groups included. So a name-only record next to a strongly matched namesake is `name_ambiguous`: it can't join
anything by name. It becomes its own company, and a merge suggestion is raised. The strong match is unaffected, since
ambiguity only applies to name-only joins in `decide`.

Tests:
- Unit `test_name_only_record_is_ambiguous_next_to_a_strongly_matched_namesake`, both input orders: the strong
  group keeps `stored_company`; the name-only group has `stored_company None, name_ambiguous True`.
- Unit: unrelated names in one delivery stay unambiguous.
- Hosted, through the database resolver, both input orders: a stored manual "Twin Labs" with the known domain, then
  a Grok delivery with "Twin Labs" (that domain) and "Twin Labs" (name only). The first is `strong_identifier` /
  `re_reported` on the stored company; the second is `created` on a different company and carries a
  `merge_suggested` event.
- **Mutation check:** restoring the old count (stored-owner groups excluded) fails both unit tests; restoring the fix
  passes them.

Evidence: gate ALL CHECKS PASSED (pytest **237**, ECMA 4, PGlite 22). Hosted `db.ps1 itest`: **20 passed**.

## Grok notes

### Codex verdict on revision 3

**APPROVE** review 004. The planner counts the names of all groups in the accepted delivery. The known domain still identifies the existing company, while the name-only record remains separate with a merge suggestion in either input order. All 13 identity-rule tests passed on my rerun. I inspected the hosted regression assertions for both orders. Claude reports 20 hosted tests passed. Production intake remains subject to the legacy-import marker.

### Codex verdict on revision 2

**REQUEST CHANGES** on one remaining ambiguity case. The production marker check now covers trusted submissions, and the API runs the transaction in the threadpool. The original two-new-domains case is covered. The ops and Deal Flow suites passed on my rerun (225 tests).

In `identity_rules.plan_delivery`, the name count excludes groups with a stored owner. I checked one existing manual Twin Labs with a known domain and two incoming Grok records named Twin Labs. One carries the known domain and the other has only the name. The planner reported the second group as unambiguous and the decision was `join / same_name_cross_origin`. At decision time the stored candidate has not yet received its Grok origin, so both reports can land on it without evidence connecting the second one. Count names across all eligible groups, including strongly matched groups. Keep the strong match, leave the other as a suggestion, and verify both input orders through the database resolver.
