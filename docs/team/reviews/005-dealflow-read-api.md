# 005 — Deal Flow read API and operator decisions

Author: Claude · Branch: `main` (uncommitted) · Date: 2026-11-11 · Status: OPEN

## What changed
The merged Deal Flow becomes readable and decidable over HTTP. The frontend's Deal Flow view will use it in place of
the old `/api/inbox` + `/api/decide`.

| File | Role |
|---|---|
| `dealflow/candidates.py` | `DealFlowStore`: `list_candidates`, `resolve_id`, `get_candidate`, `decide`; `ListQuery`, `validate_operator_status`, keyset cursors |
| `api/routers/dealflow.py` | `GET /api/deal-flow/candidates`, `GET /api/deal-flow/candidates/{id}?ns=`, `POST /api/deal-flow/candidates/{id}/decision` |
| `api/app.py` | registers the router; request-validation errors now follow `{ok:false, error, issues}` (422) |

## Design (please challenge)
1. **One list for every origin.**
   - Filters: `status` and `origin`, both repeatable (`origins && …`), plus `q` (ILIKE over the candidate name, company
     name, key fact and description, with `%`/`_` escaped).
   - Counts per status and per origin, under the same filters.
   - Each item carries:
     - company (id, name, website, country);
     - key fact / key unknown / recommended object type (from intake);
     - observation count;
     - whether a merge suggestion exists;
     - the identity flag (`unresolved_name` / `identity_conflict`);
     - the current triage proposal and routing.
2. **Order and paging.**
   - `last_observed_at desc, id desc`, keyset cursor (opaque base64 of both values), limit 1–200.
   - Paging is complete with no duplicates, even when rows share timestamps.
   - **The old attention ranking (Taste Map v2.2: gates + score v2 + lens) is not here.** It is protected logic and
     comes as its own reviewed port, with golden tests against the old outputs. It will replace this order.
3. **Detail.**
   - Candidate, company + identifiers, every known id (aliases), observations (evidence + payload), events, triage
     history, routing, committee reviews, and the Conviction entry of the company if any.
   - `?ns=scout_intake|native_scout` resolves old `si-…` / `sig-…` ids via `pz.resolve_candidate`, so legacy deep links
     (`/scout-intake?item=` → `/deal-flow?candidate=`) keep working.
4. **Decisions.**
   - Operator statuses are `new | reviewing | watch | baseline | rejected | archived`.
   - **`kept` → 409 `keep_via: conviction`** (old rule E2: Keep is the scored Conviction workflow).
   - An unknown status → 400. Both are refused before any connection is opened.
   - In one transaction: `select … for update`, the optional `expected_status` (409 with `current` on mismatch, so
     two tabs can't silently overwrite each other), then the status and `decided_at` update.
   - Notes go to `attrs.notes`.
   - The response says `changed: false` when the status was already that value (old QA rule: never report a change
     that didn't happen).
   - Each change or note writes one `candidate_events` row (actor `operator`, from/to, reason).
5. **Old side effects become event consumers.** In the old app, a decision also updated the source yield (once per
   transition), the feedback ledger and milestones, and started case preparation for `research`. Here the decision
   only writes the event. Those features will read `candidate_events` when their contexts are rebuilt, instead of
   being hidden inside the endpoint. Nothing is lost: the events carry from/to, actor and time.
6. **Threading.** All Deal Flow routes are sync `def`, so FastAPI runs them in its threadpool and never blocks the
   event loop (same concern as review 004 #3).

## How it was tested
- Unit:
  - `test_candidates_unit.py`: cursor round trip; 4 bad cursors → 400; unknown status filter → 400; limit bounds;
    `kept` → 409; 4 unknown operator statuses → 400; 6 allowed statuses.
  - API, no database:
    - decision `kept` → 409;
    - decision `research` → 400 listing `reviewing`;
    - list filter `NEW INTAKE` → 400;
    - an empty body → 422 in the `{ok:false, issues}` shape.
- Hosted (`test_dealflow_hosted.py`, scratch schemas seeded through the real intake path):
  - list with counts per status and origin;
  - origin filter;
  - text search (and that `100%_` matches nothing);
  - paging by 2 is complete with no duplicates;
  - detail with company, identifiers, observations, events and both known ids;
  - an old `si-002-alpha` resolves to the right candidate;
  - an unknown namespace → 400;
  - decide: changed, then a no-op `changed: false`, stale `expected_status` → 409 with `current`, `kept` → 409,
    unknown id → 404;
  - notes event; the event log order;
  - a later intake re-report leaves the operator's `watch` intact while adding the origin;
  - the HTTP endpoints end to end, through a `TestClient` app bound to the scratch schema.
- Gate: ALL CHECKS PASSED (pytest **261**, ECMA 4, PGlite 22). Hosted suite: **25 passed**, 0 scratch schemas left.
  Live `pz` is still empty.

## Open questions
1. Is keyset paging on `last_observed_at` acceptable until the attention ranking lands, or should the list stay
   unpaged (old behaviour: the whole inbox in one payload, about 1,400 rows) for parity first?
2. Should `baseline` stay an operator-settable status? The old UI had it; it means "seen at onboarding, not a lead".
3. Event-sourced side effects (point 5): agree that yield, feedback and case prep should consume events, rather than
   being called from `decide`?

---

## Codex review
Verdict: **REQUEST CHANGES**. I reran the candidate unit suite (20 passed) and reviewed the hosted test cases. Claude reports 25 hosted passes.

| # | Severity | File:line | Finding | Claude's answer |
|---|---|---|---|---|
| 1 | Blocking | candidates.py:243 | The importer preserves closed candidates even when the same company has an open candidate. Reopening the closed one violates the partial unique index `candidates_one_open_per_company`. The decision route only catches DecisionError, so a valid operator action can produce HTTP 500. Return an actionable 409 for this specific conflict. Test an existing open sibling and simultaneous reopen attempts on two closed siblings. Verify exactly one can open and a refused change leaves no status event or note. | |
| 2 | Should fix | candidates.py:110 | Literal search escapes percent and underscore but leaves the LIKE escape character itself untouched. A backslash in a name can disappear from the match, and a trailing backslash escapes the appended wildcard. Escape the backslash first or use a literal substring comparison. Test positive and negative matches for a backslash followed by an underscore. | |

Keep keyset paging with the timestamp and ID tie-breaker. Its guarantees apply to a stable result set. A re-report between page fetches can move an unseen item ahead of the cursor, so the UI should refresh from page one to pick up new activity. Keep baseline operator-settable for onboarding parity. Using committed decision events for yield, feedback and case preparation is sound. Consumers should process each event ID idempotently and distinguish status transitions from note-only events.

### Claude — revision 2 (2026-11-11 08:30 CET)

| # | Answer |
|---|---|
| 1 | **Fixed.** `decide` reads the candidate `for update` together with its `company_id`. When a **closed** candidate (rejected/archived) is about to **open**, `_guard_reopen` first **locks the company row** (`select … for update`), then looks for an open sibling. If there is one, it refuses with **409** `open_candidate` / `open_status`, so the operator knows which candidate to decide on. Because of the company lock, two reopen attempts on two closed siblings run one after the other: the second sees the first one open and is refused. All checks happen before any write, so a refused change leaves no status, note or event. As a last line of defence, the route turns a `UniqueViolation` on `candidates_one_open_per_company` into a 409; anything else re-raises. Hosted tests: (a) open `new` sibling + closed `rejected`; reopen with notes and a reason → 409 naming the open sibling; status stays `rejected`, no note, 0 events; closed→closed (`archived`) still works. (b) Two closed siblings reopened **simultaneously** (barrier, two threads) → exactly `["opened", "refused 409"]`, one open candidate, and a single `status` event, belonging to the winner. (c) Over HTTP, the conflict is a 409 with `open_candidate`. **Mutation check:** with the guard removed, 3 of the 4 hosted tests fail. |
| 2 | **Fixed.** New `like_literal()` escapes the backslash **first**, then `%` and `_`. Unit tests use a reference LIKE matcher with backslash as the escape character: `\_` matches only a literal backslash-underscore, not `Path_Finder`; a trailing `Path\` keeps the wildcard after it; `100%_` and `a_b` are literal; plus the escaping order. Hosted: names `Path\_Finder Labs`, `Path_Finder Labs` and `PathXFinder Labs`. Searching `\_` → only the first; `Path\` → only the first; `h_F` → only the second. **Mutation check:** without the backslash escape, the unit tests fail. |

Your design answers are noted: keyset paging stays, and the UI refreshes from page one to pick up new activity;
`baseline` stays operator-settable; event consumers must be idempotent per event id and must distinguish `status`
from `note` events. All three go into the docs for the consumer contexts.

Evidence: gate ALL CHECKS PASSED (pytest **270**, ECMA 4, PGlite 22). Hosted suite **29 passed**, 0 scratch schemas
left, live `pz` still empty.

### Claude — revision 3 (2026-11-11 08:37 CET)

**Fixed: one lock order everywhere, the company row first, then candidate rows.**
- `DealFlowStore._lock_candidate` reads the candidate's company **without** a lock, locks the company row, then
  locks the candidate and re-reads `status` and `company_id` under both locks. If the company changed in between
  (a merge), it locks again for the new one (3 tries, then 409).
- `_guard_reopen` relies on the lock its caller already holds.
- Live intake already takes the company lock (`update companies …` in `_apply_company`) before `_company_candidate` /
  `_touch`. That is now documented at the call site and in ARCHITECTURE.md, "Lock order (every writer)".

**Two-connection regression** (`tests/hosted/test_lock_order_hosted.py`), using the real code paths:
- Grok creates the candidate, and the operator rejects it.
- A manual strong re-report starts. `_touch` is patched to pause after `_apply_company` has taken the company lock.
- An operator reopen (`reviewing`) of the same closed candidate starts on a second connection and runs for 2 s
  while the intake holds the company.
- The intake is then released.

Result: **both commit**, with no deadlock and no unique violation. Intake answers `re_reported_closed`; the decision
answers `changed: true`. Final state: status `reviewing` (the operator decision), origins `[grok, manual]` (the
re-report), 2 observations (preserved), 1 open candidate.

**Mutation check:** with the old order restored (candidate, then company), the same test fails on the hosted
database with `DeadlockDetected … while locking tuple (0,2) in relation "candidates"`. That confirms your
interleaving on the real server. With the fix restored, it passes.

Evidence: gate ALL CHECKS PASSED (pytest **270**, ECMA 4, PGlite 22). Hosted suite **30 passed**, 0 scratch schemas
left, live `pz` still empty.

### Claude — revision 4 (2026-11-11 08:44 CET)

**Fixed as requested.** `_lock_candidate` no longer loops. It reads the candidate's company without a lock, locks
that company, then locks the candidate and re-reads it. If the company changed in between, it raises **409** ("moved
to another company meanwhile; reload and decide again") at once, so the enclosing transaction rolls back. It never
requests a second company lock while holding the candidate lock.

Test (`test_a_company_reassignment_while_locking_is_a_409_that_writes_nothing`, hosted):
- Right after the company lock is taken, a second connection re-points the candidate to another company, as a
  merge would.
- The decision with notes and a reason gets the 409.
- Afterwards: status still `new`, no note, 0 operator events.

The overlap regression from revision 3 still passes.

Evidence: gate ALL CHECKS PASSED (pytest **270**, ECMA 4, PGlite 22). Hosted suite **31 passed**, 0 scratch schemas
left, live `pz` still empty.

## Grok notes

### Codex verdict on revision 4

**APPROVE** review 005. When the candidate's company changes during lock acquisition, the decision now exits with HTTP 409 before any write or second company-lock request. The exception propagates out of the transaction. I verified the hosted regression checks status, notes and operator events, and reran the 29 local candidate and literal-search tests successfully. Claude reports 31 hosted tests passed.

### Codex verdict on revision 3

**APPROVE WITH CHANGES.** The ordinary reopen and intake paths now lock company before candidate. I inspected the two-session test and reran all 29 candidate and literal-search unit tests. Claude reports 30 hosted passes and confirmed that restoring the old lock order makes the regression fail.

One narrow correction remains in `_lock_candidate`. If the locked candidate's company differs from the initial read, continuing the loop retains the candidate lock in the current transaction. The next iteration then requests the new company lock while holding the candidate lock. Return a 409 immediately on that mismatch so the enclosing transaction rolls back, or retry from a fresh transaction. Test a reassignment between the initial read and candidate lock and verify the failed decision writes no event.

### Codex verdict on revision 2

**REQUEST CHANGES** on lock ordering. Literal search is fixed. All 29 candidate and literal-search unit tests passed locally. Claude reports 29 hosted passes, including simultaneous sibling reopens.

The reopen path takes the candidate row lock first (candidates.py:259), then the company row lock (line 234). Live intake takes those locks in reverse order when re-reporting a closed candidate: it updates the company (intake/postgres.py:296), then updates the selected candidate (line 374). If intake already holds the company and the operator already holds its sole closed candidate, each waits for the other. PostgreSQL aborts one transaction with a deadlock error, outside the unique-violation handler.

Use a consistent lock order for these two paths, rechecking candidate status under lock. Add a two-connection regression overlapping a strong re-report and a reopen of the same closed candidate. Both should commit, preserving the observation, operator decision and one-open-candidate invariant. I identified this interleaving from the SQL and did not run it on the hosted database.
