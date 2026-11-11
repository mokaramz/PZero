# Data model and legacy import

Status: **DRAFT v0.1 — awaiting review by Codex.** Schema: `supabase/migrations/20261110000001_core_schema.sql`.

## Principles

1. **Keep everything.** All existing candidates and information stay. The old folder
   `Desktop\project-zero-data` is a read-only source; the import never writes to it.
2. **Two layers of safety.** Each migrated row keeps its legacy id (as its primary key or via `candidate_aliases`) and
   the original record in `legacy` JSONB. Separately, every old file — caches, spreadsheets and logs included — is
   archived **byte for byte** in `pz.legacy_documents.raw` (the whole folder is ~27 MB). The database refuses a row
   whose bytes don't match the recorded SHA-256 and size, and archived rows can't be updated or deleted. `parsed` is
   only a query convenience; restores always use `raw`. Either layer alone can rebuild the old data.
3. **Organize, don't overwrite.** Old and new data share one company identity, one candidate per company, and one
   status vocabulary. Each piece of evidence keeps its origin, so you can always see what came from where.
4. **Idempotent import.** Running the import twice changes nothing (sha256 per file; upserts keyed on legacy ids).

## Live data being migrated (snapshot 2026-11-10)

| Old file | Records | New home |
|---|---|---|
| `inbox.json` → candidates | 1,366 | `candidates` (+ `companies`, `company_identifiers`, `observations`) |
| `scout_intake.json` → items / cycles / events | 39 / 7 / 40 | `candidates` (origin `legacy_scout00`), `intake_submissions` (one per cycle packet), `events` |
| `native_scout.json` → signals | 150 | `candidates` (origin `legacy_native`) or `observations` on an existing candidate |
| `real_data.json` → signals | 10 | `conviction_entries` (+ `companies`) |
| `people.json` | 247 | `people`, `person_identifiers`, `company_people` |
| `events.json` | 543 (+20 leads) | `events` |
| `sources.json` | 46 | `sources` |
| `triage_proposals.json` | 1,005 | `triage_proposals` |
| `queue_routing.json` | 470 | `candidate_routing` |
| `committee.json` | 215 second-pass | `committee_reviews` |
| `inference_ledger.jsonl` | 2,264 lines | `model_ledger` |
| `schedule/jobs.json`, `runs.jsonl` | 15 / 222 | `job_state`, `job_runs` |
| `bridge_jobs.json` | 4 | `research_jobs` (status mapped; 17 `bridge_findings` stay on their Conviction entries) |
| radar_*, event_health, news, claims, cases, founder_calls, red_team, … | — | `documents` (one row per file, stable key = old relative path) until each context is modelled |
| `inference_cache/`, `native_cache/` | ~13 MB | **not imported** as live data (rebuildable caches) |
| `research_pages/`, xlsx/csv/md artifacts | — | not live data |
| **every file above, without exception** | 2,186 files | `legacy_documents.raw`, byte for byte |

## Status mapping

| Old field / value | New `status` | `legacy_status` |
|---|---|---|
| Deal Flow `decision`: new / baseline / rejected / watch / kept | same | original |
| Deal Flow `decision`: research | `reviewing` | `research` |
| Scout Intake: NEW INTAKE / REVIEWING / MONITOR | `new` / `reviewing` / `watch` | original |
| Scout Intake: APPROVED — CREATE / UPDATE | `kept` | original |
| Scout Intake: REJECTED / ARCHIVED | `rejected` / `archived` | original |
| Native Scout: NEW_SIGNAL / INVESTIGATE / MONITORING | `new` / `reviewing` / `watch` | original |
| Native Scout: DISMISSED / STALE / PROMOTED_TO_CANDIDATE | `rejected` / `archived` / `kept` | original |

## Identity resolution during import

Companies today have no shared id across Deal Flow, Scout Intake, Native Scout, Conviction, Founder Calls, Radar and
claims. The import builds one `companies` row per real company:

1. Match keys, strongest first: registry id (namespaced, e.g. `duns:079642993`) → submitter key (Grok `external_id`)
   → website domain (never a shared host such as a university domain, `github.io`, `linktr.ee`) → exact normalised
   name → normalised name + founder overlap.
2. **Strong** identifiers (`registry`, `submitter_key`, `domain`, `legacy_key`) are globally unique: the database
   refuses giving one to two companies. **Weak** identifiers (`normalized_name`, `alias`) are unique only per company,
   so two different companies with the same name both keep their name assertion until the operator reviews them.
3. Strong match → same company; the record's identifiers are added. **Cross-origin name match** (decision
   [0001](decisions/0001-cross-origin-name-merge.md)): an exact normalised-name match against the *only* company with
   that name, from a *different* origin, with no conflicting strong identifier → same company. Every other name-only
   match (same origin, ambiguous, or conflicting registries/domains) → **separate** companies plus a
   `merge_suggested` candidate event for the operator. Strong identifiers that point at two different companies →
   the record resolves to **no** company and is flagged `identity_conflict`.
4. When two old records resolve to the same company and both are open (e.g. a Deal Flow candidate *and* a Scout
   Intake item), they become **one** candidate: the Deal Flow id survives (it is the one deep links use most), the
   richer record wins the columns, the other becomes an `observation` with its full payload, and a `merge` candidate
   event records both ids. `pz.candidate_aliases` maps **every original id in its namespace** (`candidate` for 12-hex
   Deal Flow ids, `scout_intake` for `si-…`, `native_scout` for `sig-…`) to the surviving candidate;
   `pz.resolve_candidate(namespace, id)` is the one lookup the API uses for deep links. Re-import is idempotent.

The import writes a report (`ops/import_report_<date>.json`): per-file counts in vs. out, sha256, merges, merge
suggestions and anything refused. **Acceptance:** every old record is accounted for — imported, merged (with the
target named) or archived-only (with a reason).

## Open points for review

- The name normaliser's legal-suffix list (`gmbh|ag|…|co|corp`) must match the Python resolver exactly; short tokens
  such as `as`/`co`/`ab` may over-strip real names — needs a test set from the 1,366 live names.
- Schema tests: `supabase/tests` (PGlite = real Postgres in WASM, no Docker): `cd supabase/tests && npm test`.
- `candidates_one_open_per_company` enforces "a re-report never duplicates" at the database level; the import must
  merge before insert or it will fail loudly (intended).
- People link to companies and events by *name* today; `company_people` is filled only where resolution is strong,
  the rest stays in `people.attrs` until confirmed.
