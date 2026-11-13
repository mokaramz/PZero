# Project Zero v1 — system architecture (closed loop)

Technical companion to [ARCHITECTURE.md](ARCHITECTURE.md) (code layout) and [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) (how
to use it). Status: v1 complete as of 2026-10-11 (commits `c0956d6` … `4cc006a`).

```
SENSORS → DISCOVERY → TRIAGE → MONITORING → RESEARCH → EVIDENCE → VERIFICATION → JUDGMENT → RED TEAM / REVIEW
        → HUMAN ACTION → RADAR / IMQ → REAL-WORLD OUTCOME → VALIDATION → LEARNING → better sourcing
```

## Constitution (unchanged)

The frozen methodology is never changed by this layer: `taste.py`, `radar.py`, `imq.py`, `analyst.py`, `attention.py`,
`themes.py` and `sources_v2.py`, plus the locked Shadow Triage v3 prompt/models. `git diff 4f37894 HEAD` on them is
empty. Machine intelligence only proposes. These remain human-only: founder contact, event registration, Omar
handoff, conflict clearance, investment score authorship, `verified.traction`, entity merges and methodology changes.

## Stages → modules

| Stage | Module(s) | Notes |
|---|---|---|
| Sensors | `domain/connectors.py`, `domain/event_sources.py`, `domain/scout_intake.py` | registry sources, event watchers, Scout 00 intake |
| Discovery | `services/discovery.py` | scan → ingest → provenance (`first_seen`, `also_seen`, `quality_source_id`) |
| Triage | `services/shadow_triage.py` (locked v3), `services/auto_triage.py`, `services/triage_review.py` | auto-triage of new / changed candidates after each scan; proposal only |
| Monitoring | `services/watch.py`, `services/scheduler.py` | WATCH triggers (scan re-hits + official page diffs); catch-up on start; `--run-due` |
| Research | `services/research_loop.py`, Scout Bridge (`domain/bridge*.py`) | local evidence → known URLs → structured → paid only on a click |
| Evidence | `services/claims.py` (Claim Index), `services/registries.py` | publisher classes, independence groups; registry records only after confirmation |
| Verification | `services/verification.py`, `services/identity.py`, `services/traction.py` | founders / funding: deterministic proposals + click; traction: assembled, never ticked |
| Judgment | `services/analyst_runner.py` (Analyst via gateway), frozen `taste.py` | Mohamed authors scores |
| Challenge | `services/red_team.py`, `services/reviewer.py` | Red Team = Qwen; Reviewer = GLM, conditional, advisory |
| Human action | `services/today.py`, Founder Calls (`domain/founder_calls.py`), Active Evaluator | ≤ 7 actions/day; call prep + post-call verification |
| Gates | `domain/radar.py`, `domain/imq.py`, Omar guard in `services/pipeline.py` | unchanged |
| Learning | `services/validation.py` | outcomes, lead time, source alpha, misses, calibration, benchmarks, Scout 00 packet v1 |
| Protection | `services/backup.py`, `services/integrity.py`, `services/governance.py`, `services/health.py` | backup + restore test, integrity, AI provenance, system health |

## Stores (data folder)

Authoritative stores are unchanged: `inbox.json`, `real_data.json` (Conviction), `people.json`, `founder_calls.json`,
`scout_intake.json`, `sources.json`, `events.json` and the rest.

New sidecars, all append-only or derived:

| Path | Kind | Written by |
|---|---|---|
| `shadow_triage/auto_runs.json` | run log | post-scan auto-triage |
| `validation/outcomes.jsonl`, `audits.jsonl`, `snapshots.jsonl`, `scout_feedback.jsonl` | append-only | Mohamed / daily snapshot / packet handover |
| `watch/targets.json`, `watch/triggers.jsonl` | config + append-only | Watchlist / sensors / acknowledgements |
| `schedule/jobs.json`, `schedule/runs.jsonl` | job state + log | catch-up |
| `registry/records.jsonl`, `registry/links.jsonl` | append-only | registry lookups / pastes / confirmations |
| `identity/reviews.jsonl` | append-only | identity collision decisions |
| `reviews.json`, `review_requests.jsonl` | records | Reviewer |
| `experiments/runs.jsonl` | append-only | shadow harness |
| `inference_ledger.jsonl` (+ `prompt_sha`) | append-only | every AI call |

Backups go to the sibling folder `project-zero-backups/`, never into the data folder.

## AI models (all through `inference/gateway.py`, caps: $0.05/call · $1/day · $5/week · $25/month · CHEAP $3/month)

| Job | Model | Role |
|---|---|---|
| Machine triage | DeepSeek-V4-Flash; Qwen3.5-397B veto on REJECT (thinking off) | CHEAP / override |
| Analyst | DeepSeek-V4-Pro | STANDARD |
| Red Team | Qwen3.5-397B-A17B (thinking off) | STANDARD override |
| Reviewer | Zhipu GLM-4.7 (thinking off) — third independent family | STANDARD override |
| Scout Bridge research | xAI Grok (disabled by default; manual copy/paste works) | RESEARCH |

Everything else is deterministic: validation, watch, scheduling, registries (except the lookup HTTP call), identity,
traction, health, backup and integrity all cost $0.

## Background work

The app is local-first. On start, `scheduler.start_catch_up()` runs only the overdue jobs, once, one after another, in
a background thread, with a visible banner:

| Job | Interval |
|---|---|
| WATCH checks | 24 h |
| Deal Flow scan | 7 days (it triggers auto-triage within caps) |
| Event scan | 3 days |
| Validation snapshot | 24 h |
| News refresh (then news-source evaluation) | 24 h |
| Weekly learning review (and rolling news-source metrics) | 7 days |
| New-source discovery & probation | 24 h |
| News source comparison (history snapshot) | 30 days |

`projectzero --run-due` runs the same pass headless; it is suitable for Windows Task Scheduler, but nothing is
installed automatically. Set `PZ_CATCHUP=0` to disable it; tests, e2e and parity disable it too.

## Quality gates

- `scripts/check.ps1 -E2E`: ruff, mypy-free pytest (897), vitest (15), tsc, build, Playwright (109).
- `backend/scripts/parity.py --post`: 204/208. All four diffs are intentional: the Paris / STATION F coverage additions (2) and `reprocess_v` 2 → 3 on GET inbox (2) from the RC timestamp-name migration.
- `projectzero --backup` then `--restore-test`: the archive is verified and the app is booted on the restored copy.

## News & Learning (added 2026-10-11)

`services/news.py`, `/news` page. Public RSS feeds of European startup media (Sifted, Tech.eu, EU-Startups, Silicon
Canals, Startbase, deutsche-startups.de, Munich Startup, Maddyness, UKTN, ArcticStartup) plus the startupticker items
the Deal Flow scan already collects. Articles collapse into canonical events (same company + type within 10 days; the
same URL once). Identical headlines on other sites count as syndicated copies, not independent confirmation.
Materiality comes from rules; noise, roundups and VC fund news stay out of the top.

The PZ check uses Validation's entity model and gives one of these states:

- CAUGHT_EARLY (≥ 14 days, not found via the article itself)
- KNOWN_LATE
- MISSED (only with a backcast signal inside the operating period)
- HISTORICAL (signals predate PZ)
- NOT_RELEVANT
- UNKNOWN (never an automatic miss)

News observations date later events for Validation's lead time (one metric, not two). Outcome proposals reach the
ledger only on Mohamed's CONFIRM. "Audit this miss" creates a prefilled Validation miss audit. A watched company in the
news fires one WATCH trigger. Learnings go into the Scout 00 packet.

Backcast signals need a source URL and are never generated by a model. Curated cases live in
`resources/news_cases/` (RobCo). Cards are written by the CHEAP role, grounded on the article text, at $0.05 per run,
with rule-based cards as the fallback.

Jobs: `news_refresh` runs every 24 h and `news_weekly_review` every 7 days, both via catch-up. Sidecars:
`news/events.json`, `news/actions.jsonl`, `news/runs.jsonl` and `news/weekly.jsonl`.

## Adaptive source network (added 2026-10-11)

`services/source_network.py`, the **New sources** panel in System Health, and the `source_network` job (every 24 h,
via catch-up). It discovers sources, validates them, runs them on probation, measures them, and Mohamed decides on
trust.

The lifecycle is DISCOVERED → VALIDATING → REJECTED | PROBATION → TRUSTED (Mohamed's click only), plus DEGRADED and
DISABLED. Nothing is ever deleted.

- **Discovery (evidence only, no network):**
  - curated `precursor_sources` and dated backcast signals in News cases;
  - `signal_source` URLs of Validation miss audits;
  - Scout 00 evidence links that recur at least twice;
  - URLs added by Mohamed.

  An article URL becomes its listing page. URLs the registry or the announcement feeds already monitor are not
  duplicated; the evidence is attached to the existing source instead.
- **Validation (deterministic, $0 AI):**
  - SSRF guard and robots.txt;
  - two fetches (access, stability);
  - no login, CAPTCHA or paywall; server-rendered content without a result flood;
  - quality class from the Claim Index domain lists: databases and aggregators are SECONDARY and rejected; SEO,
    social and press-wire domains are LOW and rejected;
  - spam and keyword stuffing;
  - "names startups", measured as what the existing page watcher's first scan would produce;
  - Europe; early-signal versus late-stage wording;
  - originality versus the inbox and News headlines.

  Earliness and sample size are shown but not hard gates. One famous company is evidence, not proof.
- **Probation:** the source is added to the existing registry as a `page_diff` watcher with `probation: true`. Its
  candidates carry `probation_source` and a visible "why" line; their scoring and attention are unchanged.
  Performance comes from the existing measures: scan history, inbox and Validation source alpha. Validation's
  source table gains a `lifecycle` column (ESTABLISHED for registry sources).
- **Trust eligibility (all required):**
  - at least 21 days and at least 4 scans;
  - fetch reliability of at least 75 %;
  - at least 3 unique non-noise companies;
  - noise of at most 60 %;
  - entity precision of at least 60 %.

  Even then, promotion is only by Mohamed's click.
- **Degradation:**
  - 3 failures in a row → DEGRADED;
  - 6 failures → fetching paused (`enabled: false`, record kept);
  - recovers automatically when the source works again;
  - extreme noise (≥ 80 % of ≥ 10 candidates) also degrades a source.
- **Integrations:**
  - Scout 00 packet: a `SOURCE NETWORK` section;
  - System Health: a `source_discovery` block (light: no Validation rebuild);
  - coverage gaps listed with documented candidates from the same city or country;
  - "sourcing alpha" surfaced for sources with repeated early catches or strong outcomes (evidence only, no weights).

Sidecars: `sources/network.json` (candidates and state) and `sources/network_log.jsonl` (append-only transitions and
decisions). Routes: `GET source_network`, `POST source_network_run`, `POST source_decision`
(promote | keep | reject | disable | validate) and `POST source_candidate`.

## News source intelligence (added 2026-10-12)

`services/news_sources.py` adds a **News sources** tab under News & Learning. It answers: which news sources are best
for Project Zero, for which purpose, measured on observed data. There is no single score.

Every source is measured on its own dimensions, over 30 / 90 / 180-day and all-time windows (default 90):

- **Coverage:** leave-one-out recall, scoped to Europe, DE, FR, UK, CH, the Nordics, Munich, AI and deeptech.
- **Speed:** delay behind the first report of the same canonical event. Hour precision applies from feed
  timestamps, which are now stored as `published_ts`.
- **Sourcing earliness:** a company mentioned at least 14 days before its material event.
- **Originality:** syndicated copies and press-release markers, estimated at headline level.
- **Unique value**, **relevance precision** and **noise**.
- **Authority:** a domain-class prior, replaced by observed agreement with other reports and primary sources.
- **Technical health:** from the run log; `per_feed` is now recorded on every run.

**Benchmark:** canonical News events that are material (HIGH / MEDIUM), European, have an identified company, and are
not fund news. Curated cases are excluded.

**Anti-circularity:**

- recall only counts events that another source also reported;
- the benchmark discloses origin concentration and cross-source overlap;
- coverage and "unique" rankings stay COLLECTING DATA until at least 8 events are shared between sources.

**Rankings:**

- they use the Wilson lower bound;
- a leader needs at least 3 covered events;
- roles use the same minimums as the rankings;
- labels are INSUFFICIENT DATA (< 8), EARLY READ (< 30) or MORE RELIABLE.

**Disagreements:** when sources disagree on an amount or round type, the disagreement is logged append-only. It
stays OPEN until a primary source or two agreeing independent sources settle it, and it is shown on the story card.

**Missing publications:** these are detected from citations ("according to Handelsblatt", "(Reuters)") and from
external sources of material events. At 3 or more events, the publication goes to the existing Adaptive Source
Network as a `news_publication` candidate:

- validation requires a public RSS / Atom feed;
- a candidate that passes runs as a PROBATION News feed (`news/feeds_extra.json`), with every article marked;
- eligibility for trust: ≥ 60 days, ≥ 20 runs, ≥ 80 % fetch reliability, ≥ 15 relevant articles, ≥ 2 unique
  material events and noise ≤ 70 %;
- promotion is Mohamed's click only.

**Degradation:** established feeds are marked DEGRADED, never removed, on any of these:

- 3 or more failed runs;
- a login or paywall;
- editorial drift (relevance halves compared with the previous 90 days);
- severe noise;
- syndication dominance;
- a collapse in unique value.

**Schedule:** evaluation runs daily after the News refresh, weekly with the review, and monthly in the new
`news_source_review` job, which also writes the history snapshot.

**Integrations:** Scout 00 packet `NEWS SOURCE LEARNING`; Health `news.sources`; GET `news_sources?window=` and POST
`news_sources_evaluate`.

**Also fixed in News:** German and French funding headlines ("erhält / holt sich … Millionen", "lève … millions")
were classified as routine news. Digest formats (#StartupTicker, "zum Wochenende", "cette semaine") counted as
events. Stored unclassified events are re-derived with the current rules.

## Map — ground sourcing & ecosystem intelligence (added 2026-10-12)

`services/geo_intel.py` adds GET `geo_intel`, GET `geo_ecosystem?city=`, GET `geo_search?q=` and POST `sourcing_day`.

**Places.** Ecosystems come from the coverage registry plus the events gazetteer, with coordinates from a fixed
table. An item is placed only when its own location names a known city or an unambiguous sub-locality (Garching →
Munich, Ecublens → Lausanne). Country-only and non-European locations stay unplaced and are counted.

**Units per city.** Each of these becomes a unit in its city:

- Deal Flow candidates;
- Conviction companies;
- Scout Intake items;
- canonical News events whose text names the city;
- Founder Radar people;
- events in the next 45 days.

Each unit has a family (research, accelerator, grants, company formation, founder formation, Scout 00, news,
customer / pilot, hiring, funding preparation, event) and is marked early or late.

**Early vs late:** a unit is early when its machine-proposal capital stage is pre-funding or round-forming, or when
that stage is unknown and the source is a pre-company source of a known family. It is late when the stage is already
funded or first institutional.

**States:**

- VERY ACTIVE: convergence plus at least 3 early signals.
- INTERESTING: at least 2 early signals, or convergence, or 1 early signal plus a high-signal event.
- UNDER-COVERED: little detected and visibility POOR or NOT ASSESSED, as distinct from LOW SIGNAL.
- NORMAL otherwise.

At most 3 early signals count per source, so volume never wins.

**Convergence:** at least 3 families, at least 4 independent units and at least 3 entities. Late news never counts,
and one canonical event is one unit.

**Where to go:** only VERY ACTIVE or INTERESTING areas that also have something actionable; otherwise it says the
data is too weak.

**Travel:** the gazetteer's approximate hours from Karlsruhe, or distance with "travel time not calculated".

**Sourcing day:** a plan only. Times appear only when an event lists one. Institutions say "opening hours not
checked" and meetings say "only if you arrange it".

**Caching:** coverage comes from Health's cached summary (`all`), warmed at startup. The intelligence is cached until
an input store changes; a rebuild takes about 0.6 s on real data.

## Integration hardening (2026-10-12)

The Cycle 004 packet was replayed on a scratch copy. Fixes:

- Scout Intake flags Deal Flow candidates whose name or text mentions the entity as a possible match. These are
  headline-named candidates such as "Y-Combinator backs … Ageospatial". It only offers the match and never merges.
- A double "Confirm outcome" in News records one Validation outcome.
- Scout 00 packet rows carry the original evidence sources, the lead time and per-source learning.
- An auto-triage run interrupted by a restart keeps exactly its selected candidates pending; it now stores `ids` at
  start.
- Heilbronn is registered as a coverage ecosystem.

## News refresh & action feedback (2026-10-12 incident)

**Symptom.** "Refresh news" looked like it did nothing. The backend ran correctly, but the click was
fire-and-forget: no job status, no polling and no cache invalidation. The page kept showing the old stories and the
old "Last refresh" line until a manual reload, and a run with nothing new looked identical to no run.

**Refresh job.** `news.run()` is now the single, locked refresh job, used by the button, the daily job, catch-up
and `--run-due`.

- `POST news_refresh` returns a run id at once. A click while a refresh runs starts nothing and says so.
- `GET news_refresh_status` reports the stage (fetching n/m, ingesting, WATCH, cards, metrics), the last run and the
  last successful run.

**Run record.** Each run writes one record to `news/runs.jsonl` with:

- run id, trigger, start / completion times, duration;
- status `ok` / `partial` / `failed` / `interrupted`;
- a per-feed result: items, seconds, newest publication, HTTP code, rate-limit flag, stale flag;
- counts: new / material / noise / updated / already known / reclassified;
- timings, cost and the news-source evaluation summary.

**Recovery and politeness:**

- A run cut off by a restart is recorded as `interrupted` at startup (`news/run_state.json`).
- Feeds are fetched 4 in parallel.
- A feed that answers 429 is paused for 30 minutes (`news/feed_cooldown.json`); a polite skip is not a failure.
- A feed whose newest item is 14 days old or more is flagged stale.

**Parsing fixes:**

- Undeclared HTML entities no longer kill a feed.
- Atom `published` wins over `updated`.
- Relative links and GUID links are resolved.
- Publication days are the operator's local day.

**Ingest fixes:**

- Known-name patterns are compiled once: ingest went from about 11 s to under 1 s.
- Identical headlines on another site within 10 days merge as syndicated copies.
- Same-month event-id collisions no longer overwrite an event.
- Acquisition headlines are filed under the acquired startup.

**Action feedback, system-wide:**

- `useAction` acknowledges every click instantly in a Background activity bar.
- `GET activity` reports server jobs with real progress only: news refresh, scan, triage, batch analysis, shadow
  analyst, catch-up, new-source check.
- Results use the same words everywhere (RUNNING / COMPLETE / PARTIAL / FAILED) and stay readable.
- Failures are explained in plain English, and duplicate in-flight clicks are ignored.
- Confirming an outcome and promoting a source to trusted are two-step buttons.
