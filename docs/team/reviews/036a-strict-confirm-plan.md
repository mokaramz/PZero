# 036a — Plan: strict boolean `confirm` on every confirming write

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-369) — implementation next

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
