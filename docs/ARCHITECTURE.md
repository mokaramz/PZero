# Project Zero (optimized) — architecture

Status: **DRAFT v0.1 — awaiting review by Codex** (see [team/WORKFLOW.md](team/WORKFLOW.md)).
Author: Claude (AI engineer). Date: 2026-11-10.

This is a clean rewrite of `Desktop\project-zero` (v2). The product, its investment rules and its look stay the same;
the structure, the data store and the sourcing pipeline change. Nothing is copied wholesale: each module is rewritten
from an understanding of what the old one did, with the old code and its tests used as the behavioural reference.

## 1. What changes and why

| # | Change | Reason |
|---|---|---|
| A | JSON documents → **Supabase (hosted Postgres)** | Old saves rewrote whole files (2 MB `inbox.json` per change); companies had no shared id across 6+ files; duplicate checks were written 3 times. Row-level transactions and real keys fix all three. |
| B | **Deal Flow + Scout Intake + Native Scout → one Deal Flow** | Three queues with three status vocabularies fed each other in a loop, and there were two ways into Conviction (scored and unscored). One pipeline, one status set, one way in. |
| C | **Scout Bridge removed** | 4 jobs ever (3 stuck in `needs_operator`), bypassed every spend cap. Its one unique ability — on-demand research — becomes a capped research service. |
| D | **Grok delivers directly** into this system through a validated intake contract | Replaces the Google Drive relay, the Scout 00 inbox folder and the paste path. Grok searches and refines; it does not run deep infrastructure. |
| E | Professional module boundaries | Old files reached 1,000–2,700 lines with cross-feature imports. New code is grouped by bounded context with one-way dependencies. |

What does **not** change: the Taste Map v2.2 investment rules (golden-tested), the iron rules (provisional ≠ verified;
conflicts go to the Manager first; nothing is sent automatically; the tool never invents facts about people), the
UI and design system, and the HTTP API shapes the UI depends on (except the merged Deal Flow endpoints).

One rule changes deliberately: **"local-first"** is replaced by "hosted in the operator's own Supabase project".
Data now leaves this computer; access is restricted to the backend (see §5).

## 2. System overview

```
                 ┌────────────────────────── React SPA (same UI) ──────────────────────────┐
                 │ fetch /api/*  (never talks to Supabase directly)                         │
                 └──────────────────────────────────┬───────────────────────────────────────┘
                                                    │
 Grok (agent in this folder) ──CLI `pz intake submit`┤
 Registry scan (connectors)  ──────────────────────▶│  FastAPI  ──▶ application services ──▶ domain (pure rules)
 Manual paste                ──────────────────────▶│                    │
 Scheduler (background)      ──────────────────────▶│                    ▼
                                                    │             repositories (SQL)
                                                    │                    │
                                                    └──────────▶ Supabase Postgres + Storage
```

## 3. The single Deal Flow pipeline

```
 SOURCES ──▶ INTAKE ──▶ RESOLVE ──▶ TRIAGE ──▶ DEAL FLOW ──▶ CONVICTION
```

1. **Sources** — every way a lead arrives is an *origin*: `registry_scan`, `grok`, `manual`, `research`, and
   `legacy_scout00` / `legacy_native` for migrated records. Each arrival is stored as an immutable **observation**
   (what was seen, where, when, by whom, with evidence URLs).
2. **Intake** — one service (`dealflow/intake/service.py`) with two doors onto the same entity rules
   ([`contracts/intake_submission.schema.json`](../contracts/intake_submission.schema.json) `#/$defs/entity`):
   - **External** (`submit_external`): Grok via `pz intake submit`, the operator's paste via HTTP. The caller may
     assert only origin `grok` or `manual`; anything else is refused with "server-side only". All or nothing: one bad
     entity refuses the whole delivery and writes nothing.
   - **Trusted** (`submit_trusted(TrustedBatch)`): registry connectors, research jobs, the legacy importer. The origin
     (`registry_scan`, `research`, `legacy_*`) is set by the calling code and can't come from data; a `TrustedBatch`
     with an external origin is a programming error. Entities are checked one by one, so one malformed registry
     record is refused and reported (`partial`) without blocking the scan.
   Both doors store the submission once (sha256 of canonical JSON: the same delivery twice changes nothing) and hand
   accepted entities to resolution.
3. **Resolve** — one entity resolver (name, normalised name, website domain, registry ids, founders) maps each
   observation to a **company** (or person / event) and to its **candidate**. A re-report attaches evidence to the
   existing candidate; it never creates a second one. Uncertain matches are flagged for the operator, never merged
   silently.
4. **Triage** — the existing cascade for *every* candidate regardless of origin: Stage 0 junk filter → cheap model
   proposal → veto → routing (Needs you / Preparing / Background / Watch / Deferred / Conflict-gated). Proposals only;
   the operator decides.
5. **Deal Flow** — one status set (below), the existing attention ranking, workspaces, feedback ledger and source
   yield. Cards show their origins ("Registry · Grok"), so cross-source convergence is visible in one place.
6. **Conviction** — one scored way in (the Keep form). Scout Intake's other approve targets survive as alternative
   actions on a candidate: *Founder Radar person*, *pre-company opportunity* (behind the promotion guard), *add event*.

### Unified candidate status

| New | Old Deal Flow | Old Scout Intake | Old Native Scout |
|---|---|---|---|
| `new` | new | NEW INTAKE | NEW_SIGNAL |
| `reviewing` | research | REVIEWING | INVESTIGATE |
| `watch` | watch | MONITOR | MONITORING |
| `baseline` | baseline | — | — |
| `rejected` | rejected | REJECTED | DISMISSED |
| `archived` | — | ARCHIVED | STALE |
| `kept` | kept (via Keep form) | APPROVED — CREATE/UPDATE | PROMOTED_TO_CANDIDATE |

Every status change is an append-only `candidate_events` row (actor, from, to, reason, time). The old value is kept
on the row as `legacy_status` so nothing is lost in translation.

### Grok's role

- **In the team:** search engine, refiner and reviewer (see [team/WORKFLOW.md](team/WORKFLOW.md)).
- **In the product:** Grok works directly in this folder and delivers results by running
  `pz intake submit <file.json>` (or `POST /api/intake/submissions`). The submission must pass the contract; a
  malformed one is refused with the exact reason and writes nothing. Grok never writes database tables directly.
- Grok does **not** do: scoring, committee judgment, case preparation, promotion, outreach, or any decision. Those stay
  with the rules engine, the capped model gateway and the operator.

## 4. Backend structure

Python 3.12, FastAPI, psycopg 3, Pydantic v2. Connection: the Supabase **session pooler (port 5432)** — it keeps
transactions and session-level `pg_advisory_lock` working over IPv4. Never the transaction pooler (6543). A direct
connection only if the host has IPv6 or the IPv4 add-on (Grok research, [review 002](team/reviews/002-grok-supabase-connection-research.md)).
Still to demonstrate on the real project: lock contention and release between two independent workers.

```
backend/src/projectzero/
  core/            config, db (connection pool, transactions), errors, logging, clock, security middleware
  contracts/       Pydantic models generated from / checked against /contracts/*.schema.json
  dealflow/        the merged pipeline: intake, resolution, observations, triage, routing, candidates, sources
  conviction/      conviction entries, scoring (Taste Map), case prep, committee, verification
  network/         people, founder radar, identity, watchlist, public work
  events/          events, event sources, map/geo
  research/        model gateway (budgets, ledger, kill switch), on-demand research jobs (ex-Scout Bridge)
  insight/         today, investment desk, validation, news & learning, associate, health
  ops/             scheduler, jobs, backups/export, legacy import
  api/             app factory + one thin router per context (parse → service → shape response)
  cli/             `pz` command: serve, intake submit, migrate, import-legacy, jobs run
```

Rules:
- **Dependency direction:** `api → services → domain`; `services → repositories → core.db`. Domain modules are pure
  (no I/O) and hold the protected investment rules.
- A context may call another context only through its public `service.py`, never its repository.
- Files stay small (target < 400 lines). Each context has `models.py`, `repository.py`, `service.py`, `rules.py`
  as needed, plus its tests.
- Every outbound HTTP call goes through one safe client (timeouts, size cap, SSRF guard). Every paid model call goes
  through the gateway (preflight, reservation, ledger, daily/weekly/monthly caps, `PZ_AI_PAID` kill switch).

## 5. Data and security

Full model: [DATA_MODEL.md](DATA_MODEL.md). Schema: `supabase/migrations/`.

- **Relational core with JSONB detail.** Companies, people, events, sources, candidates, observations, decisions get
  real columns and keys; the deep, evolving parts (evidence, provenance, score parts, model output) are JSONB.
- **Nothing from the old data is lost.** Every migrated row keeps `legacy_id` and the original record in a `legacy`
  JSONB column; every old file is also archived verbatim (`legacy_documents` table, large/binary files in the
  `legacy-archive` Storage bucket). The old data folder is read-only and is never modified.
- **Append-only logs** (model ledger, decisions, job runs, candidate events) are insert-only tables; updates and
  deletes are revoked.
- **Access:** RLS is enabled on every table with no `anon`/`authenticated` policies, so the public API keys can read
  nothing. Only the backend connects (service role / database URL from `.env`). The browser never receives a key.
- **Concurrency:** row-level transactions replace the old global lock; jobs use Postgres advisory locks so the app and
  background runner never run the same job twice.
  - **Lock order (every writer):** intake advisory lock (intake only) → company row → candidate rows. Live intake
    takes the company lock (update) before touching a candidate, and operator decisions lock the company, then the
    candidate, re-reading it under both. Taking them the other way round deadlocks: this was proven on the hosted
    database (review 005).
  - Every connection sets `idle_in_transaction_session_timeout = 5min`, so a vanished client can't hold locks for
    long.
- **Backups:** Supabase's daily backups plus our own `pz export` (JSON dump of every table, sha256 manifest).

## 6. Frontend

Rebuilt in the same stack (React 19, TypeScript, Vite, React Query, MapLibre) on the same tokens, components and
design rules (old `docs/design-system.md`, `ui-review-checklist.md`). Each view is rewritten and checked against
screenshots of the old view at the same data.

Visible differences, all consequences of the merge:
- Navigation: **Scout Intake** and **Scout Bridge** are removed; Deal Flow gains an **Origin** filter and shows
  intake fields (key fact, key unknown, recommended object type) on cards and in the detail panel.
- Old deep links redirect: `/scout-intake?item=…` → `/deal-flow?candidate=…`, `/scout-bridge` → `/deal-flow`.
- The nine "research job" buttons now create capped research jobs; their results appear where they did before.

## 7. Build order

1. Foundation: repo, config, db layer, schema v1, test harness, CI gate script.
2. Legacy import (read-only) → Supabase, with counts and checksums verified against the old folder.
3. Deal Flow pipeline (intake contract, resolver, triage, candidates) + its API + the Deal Flow view.
4. Conviction, then Network, Events, Insight views — one context per review cycle.
5. Scheduler and background jobs.
6. Parity pass: every view against old screenshots; every protected rule against the old golden tests.

## 8. Open questions

All three are settled in [decision 0003](decisions/0003-open-architecture-questions.md): Grok's direct delivery
only, a public URL stays required, single operator. They are kept below for context.

1. Should the app keep calling Grok over the xAI API on a schedule (the old weekday "search bridge"), or is Grok's
   direct delivery the only Grok path? Draft assumes: direct delivery only; the xAI adapter is optional.
2. Evidence gate: should a lead with **no public URL yet** (stealth, social-only) be submittable as an explicitly
   provisional item? Draft keeps "at least one public web URL" as a hard rule (iron rule: the tool never invents
   facts) — Mohamed to decide.
3. Who else (if anyone) should be able to sign in? Draft assumes: single operator, backend-only access.
