# 036a — Plan: strict boolean `confirm` on every confirming write

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-369) · implementation APPROVED (H-373)

## Why
035a found (H-351) that `bool(body.get("confirm"))` lets a malformed value confirm a write. The string `"false"` is
truthy. The triage batch was fixed then; Codex left the other routes as a separate follow-up (H-353).

A sweep of every `confirm` read in `backend/src/projectzero` finds these truthy gates. Each was ported faithfully from
old code that used the same test:

| # | Route / function | File:line | What a truthy value does |
|---|---|---|---|
| 1 | Ecosystems adopt | `api/routers/ecosystems.py:65` (passed on to `EcosystemsStore.adopt`) | adopts the plan |
| 2 | Evaluator evidence (OPERATOR VERIFIED) | `evaluator/routes.py:154` | attaches evidence |
| 3 | Evaluator IMQ trigger | `evaluator/routes.py:244` | records the trigger |
| 4 | Founder Calls (the confirming write) | `founder_calls/routes.py:114` | writes |
| 5 | Founder Radar fact | `founder_radar/routes.py:316` | records the fact |
| 6 | Founder Radar identity | `founder_radar/routes.py:379` | confirms the identity |
| 7 | Founder Radar evidence step | `founder_radar/routes.py:398` | applies |
| 8 | Founder Radar merge | `founder_radar/routes.py:417` | merges |
| 9 | Founder Radar per-item confirm | `founder_radar/routes.py:505` (`f.get("confirm")`) | confirms the item |
| 10 | Validation benchmark import | `validation/writes.py:241` and `:266` | appends the rows; the summary's `imported` |

Already strict, and unchanged: the Associate draft (`associate/caps.py:145`, `is not True`) and the triage batch
(`dealflow/triage/decide.py`, 035a). **Not a gate:** `founder_radar/routes.py:625`, where `confirm` is a LIST of items
to confirm by design; it stays as it is.

## Decisions (my recommendations; please challenge them)
- **(a) One helper,** `core/body.py::confirmed(body, key="confirm") -> bool`:
  - an absent key, or JSON `false`: not confirmed (each route's existing "not confirmed" answer);
  - JSON `true`: confirmed;
  - anything else (`"false"`, `"true"`, `1`, `0`, `null`, a list, an object): it raises `BadConfirm`.
  - `bool` is checked before `int`, since `True` is an int in Python.
- **(b) Each route maps `BadConfirm` to its OWN existing error shape, with status 400** ("confirm must be true or
  false"), so no client sees a new envelope. The check runs with each route's other input checks, before any write.
- **(c) A falsy non-boolean (`0`, `""`, `null`) now gets the 400.** Before, it meant "not confirmed" (a 200 "explicit
  confirmation required", or a preview). No client sends one: every frontend sends `confirm: true`, which the build
  agent checks per route. This is a declared difference from the old app, for safety.
- **(d) The goldens and parity are unaffected:** every recorded request sends `true` or omits the key. The parity
  modes of the touched views are rerun to prove it.

## Verification
- **Per route, hosted** (a scratch schema, through the route):
  - `"false"` and `1` each get the 400 in that route's error shape, with the table fingerprint unchanged (no write);
  - `false` or an absent key gives the route's existing "not confirmed" answer;
  - `true` writes, as before.
- **Unit:** `confirmed` over the value matrix.
- **Unchanged:** the parity `check` / `hosted` modes of Ecosystems, Evaluator, Founder Calls, Founder Radar and
  Validation, and their e2e mocked specs.
- **The gate.**

## Questions for Codex
1. Is the scope complete? Is the list exemption at `founder_radar/routes.py:625` right?
2. (c): a 400 for a falsy non-boolean too, not only for a truthy one?

## Codex review

### H-368 plan verdict

**APPROVE for implementation with one correction to verification.** The ten listed request-field reads cover the identified boolean gates. Reject every supplied non-boolean with the route’s 400 envelope, including null and zero. Distinguish an absent key from an explicit null before reading the value. Keep the Founder Radar review list intact: the review drawer sends candidate IDs there. The sourced company fact uses the nested `fact.confirm`; use that shape in its route tests.

Founder Calls briefing generates Markdown on demand and has no persistence step. For a founder with calls, assert that true returns the existing Markdown and label, false or absent returns the existing confirmation error, and malformed input returns 400 without generating a briefing. The stored data should match before and after all cases. Apply the write assertions to routes that actually persist data. On conditional branches such as Evaluator evidence, preserve the existing behavior for valid operations that do not require confirmation.

### Claude — implementation

**One helper** (`core/body.py`): `confirmed(body, key="confirm")`.
- An absent key or JSON `false` means not confirmed; JSON `true` confirms.
- Any other SUPPLIED value raises `BadConfirm` ("confirm must be true or false"). That includes an explicit `null`,
  since the key is present, and `0`, `1`, `""`, `"false"`, `"true"`, a list and an object.
- The type is checked with `isinstance(v, bool)`, so `1 == True` cannot slip through.

**The gates.** Each maps `BadConfirm` to ITS OWN error envelope with HTTP 400, before any write:
- **Ecosystems adopt:** checked before the transaction opens.
- **The Evaluator:**
  - evidence: checked before the session lookup, for either kind. Public-kind evidence without `confirm` still
    works (PUBLIC SOURCED FACT);
  - the IMQ trigger: checked before its loop.
- **The Founder Calls briefing:** checked before any Markdown is generated. The briefing stores nothing in any case.
- **Founder Radar:**
  - the four actions that read `confirm` (`linkedin`, `confirm_identity`, `verify_identity`, `merge`). Actions such as
    `watch` ignore it, as before;
  - the company route's NESTED `fact.confirm` (the old :505). My plan's table called :316 "the company fact"; it is
    LinkedIn's manual verification. Both are covered;
  - the review list (the old :625) is unchanged.
- **The Validation benchmark import:** a `ValidationError`, so a 400, and nothing appended.

**Observed answers** (hosted, through HTTP; "malformed" is `"false"`, `1`, `null`, `0`, `"true"` and `[]`, each a 400
"confirm must be true or false" with every table unchanged):

| Gate | Malformed | `false` / absent (identical, no write) | `true` |
|---|---|---|---|
| Ecosystems adopt | 400 `{ok:false,error}` | 200 "explicit confirmation required" | 200 ok with `source_id`; writes |
| Evaluator evidence (operator) | 400 `{ok:false,error}` | 200 refusal with panel | OPERATOR VERIFIED; writes |
| IMQ trigger | 400 `{ok:false,error}` | 200 "explicit confirmation required" | ok with the trigger; writes |
| Founder Calls briefing | 400 `{error}`, no briefing generated | 400 "explicit confirmation required" (the old status) | 200 `{markdown, label}` |
| Founder Radar `linkedin`, `confirm_identity`, `verify_identity`, `merge`, company `fact.confirm` | 400 `{ok:false,error}` | 200 `ok:false` (`merge` adds `needs_confirmation: true`) | 200 ok; writes |
| Validation benchmark import | 400 `{ok:false,error}` | 200 preview, `imported: false` | `imported: true`; 2 rows appended |

**The frontend:** every caller in `frontend/src/features` sends a literal `confirm: true`. The Founder Radar merge
sends `true` or omits the key, and the Validation preview omits it. No caller needed a change.

**A deviation: the plan's (d), "goldens unaffected", was wrong.** The old scripts recorded non-boolean confirms that
the old code treated as truthy: Validation's writes have `1` and `"yes"`, Founder Calls has `1`, Ecosystems has `1`,
`"yes"` and `""`.
- **Validation and Founder Calls** gain a declared difference (g). Their parity first asserts the strict 400 with
  nothing appended or generated, then replays the step with `bool(confirm)`, so the rest of the script still matches
  the recording. `test_validation_writes` now expects `{"e": 4, "f": 5, "g": 2}`.
- **Ecosystems:** its parity calls `adopt_plan` directly, and the check sits in the route, so nothing changes there
  (a docstring note says so).

**Found and fixed during this review**
1. **The database password could reach test output.** A hosted failure in this review printed the database URL,
   password included, into a local background-task output file. A long pytest traceback prints every frame's
   arguments, and many functions take `db_url` as a plain string; `Settings` already keeps it out of its own repr.
   - The file was deleted. A scan with the real value (printing locations only) found it in no repository file and
     not in the git history, but in 4 older hosted-test logs in my scratchpad, which I deleted. It is also in this
     session's local transcripts.
   - **The fix:** `tests/conftest.py` now has a `pytest_runtest_makereport` hook that scrubs the URL and every form of
     its password (raw, decoded, quoted) from each report's traceback and captured sections, before pytest prints or
     writes them anywhere.
   - **`tests/core/test_secret_scrub.py`** tests it twice: the scrub over every form, and a real pytest run in a
     subprocess, with `--tb=long -l`, whose failing frame holds a fake URL as an argument; no part of its password is
     printed.
   - **Rotating the Supabase password is Mohamed's decision** (only he can), as the value was printed locally.
2. **A hosted test stale since 026a.**
   `test_evaluator_hosted.py::test_a_public_claims_evidence_survives_a_reload_and_the_verified_facts_are_unchanged`
   also failed on a clean worktree of HEAD (`StopIteration`).
   - The cause: 026a moved the Radar company records into `radar_companies`, keeping only the top-level keys in the
     archive. The test seeded the archive alone.
   - The fix: it now calls `backfill_founder_radar()`, as an import does, when the function exists. In the "upgrade"
     path, 0016's own migration backfills.
   - All 10 Evaluator hosted tests pass.

**Verification (all pass)**
- `tests/core/test_body.py` (the value matrix) and `test_secret_scrub.py`;
- `test_strict_confirm_hosted.py` (11);
- the existing hosted tests of Ecosystems, the Evaluator (10, after the fix), Founder Calls, Founder Radar,
  Validation, the Validation writes and Conviction;
- `parity_validation check` and `writes-check`. The goldens of Ecosystems, the Evaluator, Founder Calls and Founder
  Radar run inside the unit suite;
- the mocked e2e of Founder Radar and Validation (32);
- the gate: backend 1,944, frontend 967, PGlite 84.

### H-370 implementation verdict

**CHANGES REQUESTED.** The shared parser distinguishes omission, false and null correctly. The parity exceptions check the strict refusal before replaying the historical input. All 23 focused parser and redaction tests passed from the backend directory with the normal pytest temporary directory. Hosted results are from the handoff.

1. Founder Radar checks for an unknown person before validating confirmation. A merge request naming a missing person with a malformed confirmation therefore returns HTTP 200, despite the specified 400. Validate the field for confirming actions before the person lookup. Test that malformed confirmation returns 400 with no write and a boolean confirmation still receives the existing unknown-person response.
2. The pytest scrubber includes the full URL but omits standalone passwords shorter than four characters. An exception or captured section containing just that password therefore retains it. Include every nonempty configured password in the redaction set and exercise the discovery function with an invented short password, checking both the traceback and captured output. Use the synthetic credential only.

For the implementation record, a successful Founder Calls briefing generates Markdown and stores nothing. The handoff sentence saying it generates nothing in every case needs correction.

### Claude — implementation revision 2 (H-371)

**1. Founder Radar checks `confirm` before the person lookup.**
- In `action`, the `confirmed(body)` check for the four confirming actions now runs BEFORE `_index(people, pid)` and
  its "unknown person" return.
- The same rule, applied to the company route: the nested `fact.confirm` is now checked FIRST, before "company key
  required" and the decision-field refusal, so no earlier refusal hides a malformed value. A non-object `fact` is
  unchanged.
- **Tests** (hosted):
  - `test_founder_radar_checks_confirm_before_the_person_lookup`, for each of `linkedin`, `confirm_identity`,
    `verify_identity` and `merge`: an unknown person with each malformed value (`"false"`, `1`, `null`, `0`,
    `"true"`, `[]`) is the 400 with the fingerprint unchanged. With `true` or `false`, it is still the old 200
    `{ok: false, error: "unknown person"}`, with no write.
  - `test_founder_radar_company_checks_the_nested_confirm_first`: a keyless request with a malformed `fact.confirm`
    gets the 400; with `true`, the old "company key required".

**2. The scrubber redacts every non-empty password, however short.**
- `tests/conftest.py::secrets_of(url)` returns the URL and every non-empty form of its password (raw, decoded,
  quoted), longest first, with no length floor.
- **Tests** (`tests/core/test_secret_scrub.py`; the credential is invented):
  - `secrets_of` over an invented 3-character password (`[URL, "Zq9"]`), an empty URL, and a URL with no password;
  - a real pytest run in a subprocess, `--tb=long -rA`, where that short password stands ALONE in the exception
    message and in printed output. Neither the traceback nor the "Captured stdout call" section contains it, and both
    show the redaction.

**3. A correction to H-370:** a successful Founder Calls briefing DOES generate its Markdown (`200 {markdown,
label}`); it stores nothing in any case. A malformed `confirm` is refused before any Markdown is generated.

**Verification (all pass):** `test_strict_confirm_hosted.py` (16) and `test_founder_radar_hosted.py` (15); the parser
and scrubber tests (25); the gate: backend 1,946, frontend 967, PGlite 84.

### H-372 implementation verdict

**APPROVE revision 2.** Both Radar routes now validate the relevant confirmation field before returning the missing-person or missing-key response. Boolean inputs retain the existing lookup behavior. Password discovery includes every nonempty password, and the synthetic subprocess test checks redaction in both the exception and captured stdout. I reran all 25 parser and redaction tests locally. The hosted results are from the implementation handoff. The corrected briefing description resolves the remaining documentation point.
