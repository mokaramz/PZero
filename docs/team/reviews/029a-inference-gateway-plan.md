# 029a — Plan: the inference gateway core (no live call)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-269) — implementation APPROVED

## Why
Every remaining model caller goes through one gateway in the old app (`inference/gateway.complete`): the News cards
(028d), the Deal Flow triage proposals, veto and second pass, the analyst and red team, the committee and the
Associate. The rewrite has no gateway yet. Every ported view follows its old "model unavailable" path; News, for
example, writes the deterministic `rules` card.

This review builds the gateway core **without enabling any paid call.** 028d (the News cards) is its first caller;
each other caller comes when its view is ported.

**Real spend** is tiny and all on DeepInfra: 2,326 ledger rows totalling $1.42, $1.06 of it the triage veto; the News
cards cost $0.008 in total.

## Scope
1. **`core/inference/`**, ported line for line where the logic is pure:
   - `config` (roles, providers, the price table, the caps);
   - `complete(role, messages, *, purpose, entity_id, run_id, run_cap_usd, json_mode, validate, model,
     max_output_tokens, override_reason, use_cache, timeout_s) -> Result`, which never raises for an expected failure;
   - `extract_json`, the error kinds and `must_stop`, the plain-language errors, and `status()` (readiness without
     key values, plus the budget summary for System health later).
2. **Providers.**
   - `FakeProvider`, deterministic: it records its calls, and `paid` is configurable to exercise the budgets.
   - An OpenAI-compatible client on `core.net`:
     - `POST {base_url}/chat/completions`;
     - a policy allowing only the provider's host, https, and no redirects;
     - the key added only through `headers_for` for that host;
     - `raise_for_status=False`, so the old status mapping and `Retry-After` keep working;
     - the old retries (at most 3 attempts, 2 s and 6 s, only timeout / rate_limited / server / network;
       `Retry-After` bounded to 30 s).
3. **The budget in Postgres.**
   - The old rule order is kept exactly: the run cap (even with an override); then an override with a reason of 8+
     characters skips the rest; then the per-call cap by purpose; the day, ISO-week and month caps including pending
     reservations; the role's monthly cap; the entity's all-time cap.
   - The check and the reservation run in ONE transaction under `pg_advisory_xact_lock(hashtext('<schema>.model_budget'))`,
     with reservations as rows of a new `model_reservations` table. Two processes therefore cannot overshoot; the old
     reservations lived in one process.
   - Spend is summed from `model_ledger` by indexed window queries on the Berlin clock.
   - The old engineering guard is replaced by decision (b).
4. **The ledger.** One `model_ledger` row per call (outcomes `ok`, `cache_hit`, `error`, `blocked`, `disabled`).
   Migration 0021:
   - adds `role`, `run_id`, `call_id` and `error_kind` as stored generated columns from `detail`, with indexes, so
     the append-only rows need no update;
   - widens `usd` to `numeric(14,8)`. Imported rows keep their imported values; the rounding is under $0.001 in total.
   - The writer puts the four keys in `detail`, as the importer already does.
5. **The cache.** A `model_cache` table (key, model, text, stored_at), keyed as before (the sha256 of provider, model,
   messages, json mode, max output, temperature and extra body), with no TTL, as before.
   - It starts EMPTY. The old 1,934 cached replies stay in the byte-exact archive as rebuildable state (decision e).
   - A hit is re-validated with the current validator, as before.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Keys only in `.env`.** `DEEPINFRA_API_KEY` is read at call time and never logged, returned or stored. The old
  analyst's fallback to a legacy `config.json` key field is dropped. xAI (the RESEARCH role, the Scout Bridge, the
  native search) is not ported.
- **(b) No test ever calls a live model.** A conftest guard clears every provider key and forces paid calls off;
  tests use the fake provider and a fake transport. A real provider refuses to run under tests, which replaces the old
  engineering guard.
- **(c) Paid calls are OFF unless explicitly turned on.** The old switch was on unless set to off. Here a real
  provider runs only when BOTH `PZ_AI_PAID=on` and its key are in `.env`. **Turning it on is Mohamed's decision.** This
  review adds no key and does not turn it on. Until then every caller follows its old refusal path (`not_configured`
  or `disabled`).
- **(d) The cache is checked after the kill switch** (the old app checked before). This is recorded as a fix: a
  cached paid answer is not served while paid calls are off. With an empty cache it changes nothing today.
- **(e) The cache starts empty**, rather than importing the 1,934 old entries: each entry is tied to an exact prompt,
  and only 70 of 2,326 calls ever hit it.
- **(f) Overrides** (`override_reason`) stay a caller argument, used by code paths that need them, as before; there is
  no UI to set one.
- **(g) The caps stay as before:** $0.05 per call, $1 a day, $5 a week, $25 a month, CHEAP $3 a month, $1 per entity,
  and the per-purpose caps.
- **(h) Retired roles:** ESCALATION is kept disabled, as before. RESEARCH (xAI) is dropped.

## Verification
- **Oracle** (old interpreter, the old `FakeProvider`, a frozen clock, a scratch ledger): the old `complete` and
  `budget.check` over sequences that cover:
  - every rule in order: the run cap with and without an override, a short override reason, the per-call and
    per-purpose caps, every window boundary on the Berlin clock, the role and entity caps;
  - reservations, the retries (each retryable kind, `Retry-After`, an overloaded message) and every non-retried kind;
  - JSON extraction, validation failures, and cache hits and misses.

  Compared with the new gateway over the same fake provider: the `Result`s, the ledger rows, and the decisions.
  Expected differences: (c) the kill-switch default and (d) the cache order.
- **Safety tests** with a fake transport and a resolver that refuses everything:
  - the key is sent only to the provider host and never on any other request;
  - a redirect is never followed;
  - another host or http is refused;
  - no key value appears in a `Result`, the ledger, a log or an error;
  - with no key, or with paid calls off, nothing is sent.
- **PGlite:** 0021's generated columns over existing rows, the new tables, the CHECKs, append-only.
- **Hosted:** two concurrent reservations cannot overshoot a cap (two connections racing for the last dollar); a
  failed call releases its reservation; the ledger rows round-trip; `status()` reports readiness without values.

## Questions for Codex
1. Is moving the cache check after the kill switch (d) the right fix?
2. Generated columns for the promoted ledger fields, or an index on `detail` instead?
3. Is "paid only when `PZ_AI_PAID=on` and a key is present" (c) the right default, with Mohamed's approval required to
   turn it on?

---

## Codex review

### H-264 plan verdict

**REQUEST CHANGES.** Keep the paid switch ahead of the cache so disabling a paid role also disables replay of its answers. Keep real calls off by default and require both Mohamed's explicit enablement and the provider key. Use generated columns for the four stable fields. Choose indexes for the actual budget and lookup queries, including their time windows.

The admission lock serializes reservations, but the plan leaves settlement and crash recovery unspecified. If a successful call releases its reservation before its ledger debit commits, a waiting caller can spend the same headroom. Specify one transaction under the same budget lock for recording the debit and retiring the reservation, with idempotent settlement by call ID. Distinguish a failure before dispatch from a timeout after dispatch, when the provider may already have billed the attempt. Define how retries are covered and how an abandoned reservation is reconciled without silently freeing potentially spent budget.

Add a two-connection fake-provider test that races settlement with admission at the cap, plus a restart case between dispatch and settlement. Verify that a repeat settlement records one debit and that the next caller sees either the reservation or the committed charge throughout.

### Claude — plan revision 2

Codex's points are all taken. The paid switch stays ahead of the cache, real calls stay off by default (both
Mohamed's explicit enablement and the key are required), and the four stable fields are generated columns.

**The indexes, chosen for the actual queries**
- `model_ledger (at)` for the day, ISO-week and month windows; `(role, at)` for the role's month; `(entity_ref)` for
  the entity's all-time total; `(run_id)` for the run cap.
- A UNIQUE partial index on `(call_id, attempt)`, where `call_id` is not null, makes settlement idempotent.
- `model_reservations (expires_at)` for the reconciler.

**One attempt, one reservation**
- The old code reserved once per call and retried inside it, so a billed failed attempt plus a successful retry
  could exceed the reserved amount. Here every ATTEMPT is admitted separately.
- Before each attempt (the first and each retry), under `pg_advisory_xact_lock(hashtext('<schema>.model_budget'))`,
  the gateway runs the old rule order with the attempt's estimate. It counts the committed ledger, every live
  reservation and every reconciled abandoned attempt, then inserts one `model_reservations` row keyed by (`call_id`,
  `attempt`) with the estimate and an `expires_at`, and commits.
- A retry that no longer fits is not sent: the call ends as `budget_blocked`, with the attempts so far settled.

**Settlement: one transaction under the same lock, idempotent by (`call_id`, `attempt`)**
- One transaction, under the same lock, inserts the attempt's ledger row with `on conflict (call_id, attempt) do
  nothing` and deletes its reservation. So the next admitter always sees either the reservation or the committed
  charge, and never neither.
- A repeated settlement inserts nothing and deletes nothing.

**What an attempt costs**
- **Failed before dispatch** (refused by the policy or the guard, the connection never opened, a DNS failure, the key
  missing): nothing reached the provider. The ledger row has `usd` 0 with `usd_source` `none`.
- **Answered:** the reported cost, else the cost priced from usage (as before).
- **Ambiguous, after dispatch** (a timeout or reset after the request was sent, or an answer without a usage block):
  the provider may have billed it, so the row is charged the attempt's ESTIMATE, with `usd_source` `estimated` and
  outcome `error`. Nothing is silently freed.
- The client reports which side of dispatch a failure happened on. `core.net` raises the connect and guard errors
  before sending.

**Crash recovery**
- `expires_at` is the reservation time plus the attempt's timeout plus a 60 s margin. The provider client's own
  deadline ends the attempt well before that, so a live process always settles first.
- Every admission, under the lock, first reconciles expired reservations. Each becomes a ledger row with outcome
  `abandoned`, the estimate as `usd` and `usd_source` `estimated`, inserted on (`call_id`, `attempt`), and the
  reservation is deleted. An abandoned attempt keeps counting as spent.
- A late settlement for a reconciled attempt then conflicts on (`call_id`, `attempt`) and records nothing more. It is
  logged as a late settlement, so exactly one debit exists.
- 0021 adds `abandoned` to the ledger outcomes.

**Tests (fake provider, fake transport, two connections, the Berlin clock injected)**
- **Settlement racing admission at the cap:**
  - A holds a reservation that brings the day to the cap;
  - B's admission waits on the lock, then sees A's reservation and is blocked;
  - A settles: one transaction, debit in and reservation out;
  - B, admitted again, sees A's committed charge and is still blocked;
  - a third caller after a smaller charge is admitted exactly up to the cap.
- **A restart between dispatch and settlement:** an attempt is reserved and dispatched, then the process "crashes"
  without settling. After expiry, the next admission reconciles it to an `abandoned` row charged the estimate. The
  late settlement afterwards records nothing (one debit). The day total includes the estimate throughout.
- **A repeated settlement** records one debit.
- **Each cost case:** a failure before dispatch is $0, a timeout after dispatch is the estimate, an answer is the
  reported cost, a retry is admitted again, and a retry that no longer fits is blocked unsent.

### H-266 revision 2 verdict

**REQUEST CHANGES.** Per-attempt admission, atomic settlement and charging abandoned attempts address H-265. Two details need correction before implementation.

1. The proposed unique index is partial. PostgreSQL cannot infer it from the stated conflict target alone. Use `ON CONFLICT (call_id, attempt) WHERE call_id IS NOT NULL DO NOTHING` for both settlement and reconciliation, or use a matching nonpartial unique index. Exercise the exact migration and both statements against PostgreSQL, including late settlement after reconciliation. The existing schema already indexes `at`.
2. A valid completion can arrive without a usage block. Preserve the validated answer, record success with an estimated charge when neither reported cost nor usable token counts are available, and avoid a retry. Reserve the error outcome for an actual request or response failure. Add a fake response that returns valid content without usage and assert one dispatch, a successful Result and one estimated debit.

### Claude — plan revision 3

Both points are taken.

1. **The conflict target matches the index.** Both the settlement and the reconciliation use
   `insert ... on conflict (call_id, attempt) where call_id is not null do nothing`, which matches the partial unique
   index. `attempt` is a stored generated column from `detail`, like the other four.
   - Imported rows with no `call_id` stay outside the index, and `at` already has an index.
   - **PGlite** runs the exact 0021 migration and both statements:
     - a settlement, then a repeated settlement (one row);
     - a reconciliation, then a late settlement for the same attempt (one row, the `abandoned` one);
     - a NULL-`call_id` row next to them is accepted.
   - **Hosted** repeats the race and the restart over the same SQL.
2. **A valid answer without usage is a success.**
   - When the reply is valid (extracted and validated) but has neither a reported cost nor usable token counts, the
     outcome is `ok`. The answer is kept, nothing is retried, and the attempt is charged its estimate with
     `usd_source` `estimated`.
   - `error` is kept for a real request or response failure: a timeout or reset after dispatch, an HTTP error, a
     malformed body, or a failed validation.
   - **Test:** the fake provider returns valid content with no usage block. There is exactly one dispatch, a
     successful `Result` with its data, and one ledger debit equal to the estimate, `usd_source` `estimated`.

### H-268 revision 3 verdict

**APPROVE for implementation.** Both settlement and reconciliation now specify the conflict predicate that matches the partial unique index. The planned database tests cover repeat settlement, late settlement after recovery and imported rows without a call ID. The fake-provider test covers the other H-267 finding: a valid reply without billing metadata returns its data after one dispatch and records one estimated debit. These are acceptance criteria for the implementation review.

## Implementation (Claude, 2026-11-12)

**What landed**
- **`core/inference/`.**
  - `config` holds CHEAP, STANDARD, and ESCALATION (disabled); RESEARCH/xAI is dropped. `paid_enabled(env)` is true
    only when `PZ_AI_PAID` is exactly `on`. It also holds the prices, the caps and the retries.
  - `budget` has the pure rule order per attempt, the Berlin windows, the estimate and the cost classification.
  - `store`: the `BudgetStore` Protocol (`admit`, `settle`, `cache_get`, `cache_put`, `totals`), the dataclasses, and
    `InMemoryBudgetStore` as the reference.
  - `providers`:
    - `FakeProvider`;
    - `OpenAICompatibleProvider` on `core.net`: the provider's https origin only, no redirect (any second hop is
      refused), the key added only by `headers_for` and read at call time, the key redacted from any echoed error
      body, `raise_for_status=False` with the old status mapping, and before/after-dispatch reporting. It refuses
      under pytest unless a transport and a resolver are injected.
  - `gateway`:
    - `complete(...) -> Result` never raises for an expected failure;
    - the order is: role, provider, key and price, then the paid switch, then the cache;
    - each attempt is admitted before it is sent, with at most 3 attempts (2 s / 6 s, `Retry-After` ≤ 30 s,
      "overloaded" doubles the wait), and each attempt is settled as its own row;
    - `status()` never shows a key value.
  - `errors` is the plain-language layer.
- **`pg_store.PostgresBudgetStore`.** Every method runs in one transaction under `<schema>.model_budget`:
  - `admit`: reconcile the expired reservations into `abandoned` rows charged their estimate, sum the `Spend` in SQL
    (the same sets as the in-memory `spend_of`), run `budget.check`, then reserve;
  - `settle`: the exact `on conflict (call_id, attempt) where call_id is not null do nothing`, then the delete;
  - the cache (first answer kept) and `totals`.
- **Migration 0021:**
  - `model_ledger.usd` becomes `numeric(14,8)`;
  - stored generated columns `role`, `run_id`, `call_id`, `attempt`, `error_kind`;
  - the unique (`call_id`, `attempt`) partial index, and indexes for role/month, entity and run (`at` was already
    indexed);
  - `model_reservations`, keyed by (`call_id`, `attempt`), with `detail` for what an abandoned row keeps, and
    `expires_at`;
  - `model_cache`, with a sha256 key, starting empty.
- **`backend/tests/conftest.py`.** Every provider key variable is set to `""` (so `load_dotenv` cannot bring one back)
  and `PZ_AI_PAID=off`, for EVERY test.
- **`.env.example`** now reads `DEEPINFRA_API_KEY=` and `PZ_AI_PAID=off`, with a note that turning it on is
  Mohamed's decision. The real `.env` is untouched: it has no model key and no `PZ_AI_PAID`.

**No paid call is possible yet.** Nothing in this review adds a key or turns paid calls on.

**Verification**
- **Oracle** (`parity_inference goldens` / `check`): the old `complete` and `budget.check` with the old
  `FakeProvider`, a frozen clock and a scratch ledger: 18 cases, 77 calls and 39 decisions, with 0 undeclared
  differences. Declared:
  - (c) the default off and its refusal text;
  - (d) the cache after the switch;
  - (h) RESEARCH unknown;
  - one row per attempt;
  - a failure after dispatch charged the estimate (every HTTP error counts as possibly billed);
  - a retry that no longer fits is not sent.

  A valid answer without usage was already charged the estimate by the old app, so it is not a difference.
- **Safety tests** (fake transport, fixture and refuse-all resolvers):
  - the key reaches only the provider host;
  - no 301/302/307/308 redirect is followed;
  - http, another port, another host and userinfo URLs are refused;
  - no key appears in any Result, ledger row, log or error;
  - nothing is sent with no key, with paid off, or with a refuse-all resolver;
  - the status mapping holds, and each failure reports its side of dispatch.
- **In memory:** the settlement race at the cap, 10 threads that never overshoot, the restart followed by a late
  settlement, a repeated settlement, a gateway-level stall.
- **PGlite** (4 new, 66 in total): existing rows keep their values and the generated fields are derived; a repeated
  settlement is one debit; a reconciliation then a late settlement leaves one `abandoned` row; NULL `call_id` rows are
  accepted; the CHECKs.
- **Hosted** (4, `test_inference_hosted.py`):
  - **The race at the cap, on two connections.** B waits while A's settlement holds the lock, then sees A's committed
    charge and is blocked; a smaller caller is admitted exactly up to the cap.
  - **The restart.** The reconciled `abandoned` row is charged the estimate; the late settlement returns False; the
    day total is one debit.
  - **A repeated settlement** gives one debit, with 8 decimals kept.
  - **The gateway over the Postgres store.** A reported cost is ledgered. A valid answer without usage is `ok`, with
    one dispatch and one estimated debit. `status` has no key value and `paid_enabled` false.
- **The whole backend suite** passes with the conftest guard.

**Not done here:** every caller. 028d (the News cards) is next. **Turning on paid calls** (`PZ_AI_PAID=on` and
`DEEPINFRA_API_KEY` in `.env`) is Mohamed's decision; until then every caller keeps its no-model path.

### H-270 implementation verdict

**REQUEST CHANGES.** All 72 focused inference tests passed locally. Two accounting paths still need coverage.

1. In `gateway.complete`, admission prices the request using `max_out`. In `OpenAICompatibleProvider.complete`, the later merge of `extra_body` can replace the outgoing `max_tokens` or add a completion count (`n`) that the estimate never priced. Make admission and dispatch use the same effective token limit and completion count. Reject unsupported billing-affecting options before dispatch or include them in pricing. Cover both caller and role extras with a fake transport and assert the sent request fits the reservation.
2. `budget.reply_cost` accepts a negative reported cost, and `actual_usd` accepts negative token counts. A valid answer can therefore post a negative debit and increase the next caller's available budget. Treat negative or nonfinite costs and invalid token counts as unusable metadata throughout settlement, including token columns. Fall back from reported cost to valid usage, then to the estimate. Test a valid answer with invalid billing metadata and verify one successful dispatch, one nonnegative debit and the resulting headroom.


### Claude — implementation revision 2 (2026-11-13 00:13 CET)

Both points of H-271 are taken.

1. **Admission and dispatch use the same limit and the same completion count.**
   - The gateway refuses, before admission and dispatch, any caller or role `extra_body` option that changes what a call
     can bill: `max_tokens`, `max_completion_tokens`, `n` or `best_of` (`gateway.BILLING_OPTIONS`). The refusal is
     `bad_request` with a reason that says to use `max_output_tokens`.
   - As a second guard, `OpenAICompatibleProvider` never lets an extra override those keys. Its body always carries
     `max_tokens` = the priced `max_out` and one completion.
   - **Tests:**
     - `test_a_billing_option_is_refused_before_admission_and_dispatch` (8 cases: each option, from the caller and from
       the role): nothing is reserved, nothing is sent, and there is no debit;
     - `test_the_sent_request_fits_the_reservation`: over the real client with a fake transport, the sent body has
       `max_tokens` = 321 and no `n` / `best_of`, and other provider options still pass.
2. **Invalid billing metadata is unusable throughout settlement.**
   - `budget.usable_usd` (a finite, non-negative number, not a bool) gates the reported cost, and `budget._count`
     gates every token count in `actual_usd`, including the cached tokens.
   - The gateway's `_tokens` keeps only non-negative ints (not bools) for the token columns.
   - The fallback is: a usable reported cost, then valid usage, then the estimate.
   - **Test** `test_invalid_billing_metadata_never_makes_a_negative_debit`, with a negative reported cost, a NaN cost,
     a negative token count and a bool count:
     - one successful dispatch, a valid answer, and one non-negative debit;
     - the token column is NULL or non-negative;
     - the source is `priced` when the counts are valid, else `estimated`;
     - the day's spend grew by exactly that debit.
- **Results.** The inference tests pass (85); `parity_inference check` shows 0 differences beyond the declared ones;
  the backend suite passes (1,715).

### H-273 implementation revision 2 verdict

**REQUEST CHANGES.** The billing-option guards resolve the reservation mismatch, and all 85 inference tests passed locally. One provider parsing path still loses the type needed by the cost validator. In `providers.reported_cost`, JSON `false` and `true` pass the numeric type check and become 0.0 and 1.0. Both then pass `budget.usable_usd`. A paid reply can therefore record zero or a dollar even when token usage yields a different charge. Validate the original value before converting it. Exercise both booleans through the OpenAI-compatible response parser with a fake transport, checking priced fallback with usable counts and estimated fallback without them.


### Claude — implementation revision 3 (2026-11-13 00:20 CET)

H-275 is taken. `providers.reported_cost` now validates the ORIGINAL value with `budget.usable_usd` before converting
it, so a JSON `true` / `false` (or a negative or non-finite number) is no reported cost.
- **Tests.** `test_invalid_billing_metadata_never_makes_a_negative_debit` gains four cases through the
  OpenAI-compatible response parser with a fake transport:
  - `estimated_cost` `true` and `false` with usable counts: `priced` from the counts;
  - `true` and `false` without counts: `estimated`.

  Each case has one dispatch, one non-negative debit and the matching headroom. Before the fix the `true` cases would
  have recorded $1.
- **Results.** The inference tests pass (89); the parity check shows 0 differences beyond the declared ones.

### H-277 implementation revision 3 verdict

**APPROVE.** The response parser now validates the original reported cost before numeric conversion. Both JSON booleans fall through to token pricing when counts are available and to the reservation estimate otherwise. All 89 focused inference tests passed locally, including the four parser regressions.

## Grok notes
