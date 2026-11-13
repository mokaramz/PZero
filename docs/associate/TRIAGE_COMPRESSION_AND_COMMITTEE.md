# Triage Queue Compression + Investment Committee

The machine processes machine work. Mohamed sees only the few cases where his judgment, relationships or reputation
can change the outcome — and keeps the power to pull any company into Conviction.

## Cascade

```
machine proposals (Shadow Triage v3, unchanged)
 → DETERMINISTIC   Attention gate + Stage-0 junk (existing hard exclusions — they DEFER, never reject),
                   portfolio/conflict check, Europe-first operating queue, what PZ already knows
                   (analyses, Red Team, committee records, WATCH triggers, source convergence)
 → SECOND PASS     committee.second_pass — DeepSeek V4.1 Flash (reasoning_effort low), ambiguous KEEP/RESEARCH only
 → CASE PREP       existing case_prep "cand:" preparation: Analyst (DeepSeek V4-Pro) → Red Team (Qwen3.5-397B)
 → IC CHAIR        GLM-5.3, reasoning_effort max — hard prepared cases only (weekly cap)
 → OUTSIDE MEMBER  Kimi-K3 — optional contrarian, Mohamed's click only, max 2 / week
 → MOHAMED         a prepared decision card; Today shows at most human_review_daily_limit a day
```

## Routing states (workflow, not investment outcomes)

| State | Meaning |
|---|---|
| NEEDS_MOHAMED | a prepared case (or a sparse case the second pass says only a human can move) |
| CASE_PREPARING | strong signal, ≥ 2 public sources — Analyst → Red Team runs before Mohamed sees it |
| BACKGROUND_RESEARCH | high upside / thin evidence, or material new evidence — the machine keeps working |
| MACHINE_WATCH | interesting, not urgent — resurfaced by new evidence |
| DEFERRED_LOW_PRIORITY | low routing priority or a deterministic exclusion — kept and searchable |
| CONFLICT_GATED | touches the Project A portfolio — Omar first |
| CALIBRATION_SAMPLE | weekly stratified audit sample from the compressed states — at most `calibration_sample_weekly` per local week, drawn once (`queue_routing.json` → `calibration`); a review consumes its slot, and a restart, rerun or new evidence never draws a replacement |

Routing priority = existing Attention v2 + lens, plus routing signals (machine KEEP, funding-maturity edge, source
convergence, archetype match, protected pre-company / research teams, WATCH triggers, second pass, Analyst). It orders
attention only — it is not an investment score. Press, polish, funding news and SaaS earn nothing; sparse evidence is
never penalised.

## Human authority

The compressor never writes a Deal Flow decision, score, verification flag, conflict, contact or Omar handoff. Every
routed company stays in Deal Flow (routing chips, search) and can be kept / researched / watched / dropped through
`triage_review.decide` and Keep — score it. The committee is advisory; a human hold (Omar −, a negative call,
non-response) is analysed but never reversed — the Chair's disagreement is shown, the effective routing stays.

## Configuration (config.json)

```json
"attention_budget": {"human_review_daily_limit": 10, "calibration_sample_weekly": 5,
                     "second_pass_daily_limit": 60, "case_prep_per_run": 5, "auto_ic_chair": true},
"committee": {"chair_model": "zai-org/GLM-5.3", "chair_effort": "max", "chair_per_week": 5,
              "outside_per_week": 2, "second_pass_per_week": 300}
```

All gateway caps stay (per call, entity, day, week, month); the committee adds per-purpose call caps
(`ic_chair` $0.20, `ic_outside` $0.40, `triage_second_pass` $0.02) and weekly counts per role.

## Runtime

`compressor.run` runs every 6 h (scheduler job `triage_compression`) and on `POST /api/triage_compress`. Today and Deal
Flow read the stored result (`queue_routing.json`); a failed run keeps the previous routes and resumes next time. Each
route keeps its history (state, reason, evidence version, timestamp); decided companies move to `left_queue` so
Validation can compare where the machine put them with what Mohamed decided (`/api/validation` → `routing`).

## Tournament

`backend/scripts/ic_tournament.py` benchmarks Chair candidates on a scratch copy of PZ's own cases; the report lands in
the data folder (`validation/ic_tournament_<date>.md`, not committed). Promotion of GLM-5.3 (2026-10-30) is recorded in
`services/committee.py` next to `DEFAULTS`.
