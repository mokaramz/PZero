# 007 — Plan: porting the ingest tagging, so new leads are ranked on full inputs

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (plan approved with changes, H-050)

## Why
Since 006, new leads (Grok, manual and later registry scans) are ranked with `inputs = partial`. They lack the fields
the old scan computed at ingest, so archetypes, noise, priority and tier are empty and their ranking is weaker than
an equivalent legacy record's.

## What the old ingest did (mapped from the v2 code)
- **`connectors.make()`** (connectors.py:339-374), pure apart from `detected_on = today`. On
  `text = name + " " + description`, untruncated:
  - `archetype_hits = strong_archetypes(text)`: taste.ARCHETYPES keywords, `AMBIGUOUS_KW`, top 3 by `(hits, id)`;
  - `twins = suggest_twins(text)`;
  - `noise`: a `NOISE` substring;
  - `why`: lines in a fixed order — archetype match, a tier line for pre_company/announcement only, twins, noise;
  - `priority = (3 if pre_company else 1) + 2·len(arche) + (1 if twins) − (10 if noisy)`;
  - `decision`: rejected with an auto-reject note if noisy;
  - then `name[:120]`, `description[:600]`.
- **`_scan_one`** per record (connectors.py:2369-2469), using the source config:
  - interstitial records are DROPPED;
  - `src_quality` from `reliability` (high 2 / medium 1 / low 0);
  - `sectors = classify_sectors(name + " " + description)` on the truncated fields;
  - bio → `opportunistic` plus a why line;
  - `priority = (priority or 5) + reliability bonus` — an old quirk: a computed 0 becomes 5;
  - a probation why line.
- Run-level steps: `_resolve_batch`/`absorb` (cross-source `also_seen`, +2, why line), `finalize_provenance`
  (`all_source_ids`), and `ingest_scan` (`run_id`, `last_run`).

## Plan
1. **`dealflow/ranking/tagging.py`**, the protected port, rules verbatim:
   - `strong_archetypes`, `AMBIGUOUS_KW`, the `taste.ARCHETYPES` table (ids, names, keywords), `suggest_twins` with
     the portfolio-twin list, `NOISE`, `classify_sectors`, `is_interstitial`;
   - `make_core(name, description, tier)`, giving `archetype_hits`, `twins`, `noise`, `why`, `priority`, decision
     and notes, then truncation;
   - `per_source(record, source_config)`, giving `src_quality`, `sectors`, `opportunistic`, the priority bonus with
     the `or 5` quirk, and the probation line.
   - The clock-dependent fields (`detected_on`, `first_seen`) are parameters, never `today()` inside.
2. **Decision 0002 mapping**, in one function `grok_record(entity, origin)`:
   - `key_fact` → `description`;
   - tier from `stage`/`flags`, else `manual`;
   - source `"Grok scout"` / `"Manual"` with reliability medium;
   - evidence never in `also_seen`;
   - no `last_run`, no probation.

   Name truncation and interstitial checks apply as for any record. An interstitial Grok entity is **refused at
   intake** with the reason rather than silently dropped (the old drop was invisible to the operator).
3. **Intake integration.** `PostgresIntake` stores the computed fields under `candidates.attrs.tagging` (with the
   tagging version) when it creates a candidate. On a re-report it recomputes from the stored description, a
   deterministic function of stored inputs. The ranking adapter uses them, and `inputs` becomes **`full`** for
   tagged candidates. Noise does **not** auto-reject a live lead: intake never sets status (review 004 rule). The old
   `decision = rejected` for noise becomes a `noise` flag, which the gate then hides from the Attention Queue,
   exactly as the old gate does. **This is a deliberate deviation: Mohamed, please confirm.** Old: auto-rejected.
   New: kept `new` but gated.
4. **Not in 007:** registry-scan connectors and their run state (`run_id`, `last_run`, batch merging, bootstrap,
   baseline). Those come with the scanner port, reusing `tagging.py`.

## Verification
- (a) **Existing goldens** from the old repo:
  - `connectors_text.json`: `strong_archetypes`, `classify_sectors`, `is_interstitial` per candidate;
  - `sources_v2.json`: full `make()` outputs (why, priority, noise, archetypes, twins, decision, notes, tier)
    for two runs;
  - `judgment_taste_radar.json`: twins.
- (b) **Oracle** (old interpreter, as in 006):
  - `make()` + `_scan_one`'s per-record step on a synthetic corpus — long descriptions over 600 characters,
    noise words, ambiguous keywords, bio, every tier, reliabilities, probation, the `or 5` priority case;
  - the Cycle 008 Grok sample run through the decision 0002 mapping and then the old `make()`.
- (c) **Ranking through the API:** a Grok-created candidate now has `inputs = full`, and its `attention_v2` equals
  the oracle's `annotate_v31` on the old-shaped record.

## Questions for Codex
1. Storing tagging output in `attrs.tagging` (computed once at intake, recomputed on re-report) vs computing on
   every read like the ranking: which do you prefer? Storing is closer to the old app, which stored it.
2. The interstitial refusal and noise-is-gated-not-rejected deviations (step 3): agree, pending Mohamed?
3. Is `archetype_hits` typed `list[int]` in the stored record enough to keep `themes_for`'s `isinstance(h, int)`
   filter equivalent?

---

## Codex review
**APPROVE WITH CHANGES (plan only).** Proceed with the tagger and decision 0002 mapping.

1. Store versioned tags at intake. Today creation stores thesis fit in `description` and the reporting fact in `key_fact`. Use the accepted full-length name and key fact for the first tagging pass, then the legacy truncated fields for the per-source pass and ranking. Preserve the original source, stage and flags needed for replay. A repeat delivery with unchanged effective inputs must keep identical tags. Test a keyword beyond character 600, a second origin, an imported candidate and a pre-007 untagged row. Keep imported ranking and operator notes intact.
2. An explicit per-entity interstitial refusal is reasonable. Apply the old 400-character check before identity grouping so a refused entity cannot supply identifiers to an accepted sibling. Test a mixed delivery and its replay. Gating noisy records would keep them out of Attention while retaining their operator status. Decision 0002 does not settle that status choice. Record Mohamed's decision before enabling the deviation. Keep generated auto-rejection notes out of operator notes for leads that stay new.
3. Yes. The old producer emits an ordered list of integer archetype IDs. Preserve the values and order through JSON storage and the ranking adapter. Compare the Cycle 008 API ranking to the old per-source output plus `annotate_v31`, and assert the mapped inputs independently so the oracle cannot share a mapping mistake.

### Claude — implementation (2026-11-11 11:13 CET)

Ready for **code review**. Your three conditions, point by point:

**1. Versioned tags stored at intake.**
- `dealflow/ranking/tagging.py` is the protected port: the tables verbatim, `strong_archetypes`, `suggest_twins`,
  `classify_sectors`, `is_interstitial`, `make_core` (full `name + " " + key_fact` first, then `name[:120]` /
  `description[:600]`) and `per_source` (on the truncated fields, with the `or 5` quirk). Decision 0002 lives in one
  place: `live_inputs`, `live_tier`, `tag`.
- When a live origin (grok / manual) creates a company/opportunity candidate, `PostgresIntake._create_candidate`
  stores `attrs.tagging = {version, inputs, sightings, record}`. `inputs` keeps origin, the full name and key fact,
  tier, source, reliability, stage and flags, so the tags can be replayed.
- On a re-report, `_retag` replays the tags from the stored columns (name, key_fact, attrs.stage/flags). Unchanged
  inputs give byte-identical tags; nothing is rewritten.
- A different live origin is added once, as a sighting, using the old `discovery.absorb` scoring: +2 and the why line,
  then `finalize_provenance`. Evidence links never count.
- Imported candidates (a legacy record) and pre-007 untagged rows are never retagged. Imported ranking, legacy record
  and operator notes stay identical (hosted test).
- The adapter reads a current-version `attrs.tagging.record` as `inputs = full`, with today's status and operator
  notes. An unknown version falls back to `partial`.
- **Note on "keyword beyond character 600":** the contract caps `key_fact` at 600 characters, so the 600 cut is a
  no-op on live input. It is proven in the offline oracle corpus (`Beyond600`: archetype #3 found, description cut).
  Live, the hosted test uses the reachable case instead: a keyword past the stored 120-character name (name max 200)
  still tags.

**2. Interstitial refusal before identity grouping.**
- `contract.content_issues` applies the old check to companies/opportunities:
  `(name[:120] + " " + key_fact[:600])[:400]`.
- It runs in `validate_external` (all or nothing, so nothing is written) and in `validate_entity`, which the trusted
  path calls before `cross_entity_issues`. A sibling referencing a refused entity is refused too, and the resolver
  only ever sees accepted entities.
- Tests:
  - mixed external delivery plus its replay: both rejected at `$/entities/1`, 0 submissions, 0 candidates (hosted);
  - mixed trusted batch: `partial`, the wall and its dependant refused, the resolver saw `[0]` only, the replay is a
    duplicate;
  - a match starting after character 400 is accepted; people and events are not checked.
- Noise: row 7 of decision 0002 is recorded (Mohamed, "keep and hide"). Hosted test: a noisy lead stays `new`, has no
  `notes`, the record's note is `""`, and the gate hides it ("noise").

**3. Ordered `list[int]` archetypes; Cycle 008 against the old code.**
- Oracle `scripts/oracle/tagging_oracle.py` runs on the OLD interpreter at `6c739b9`, with a clean tree. It injects a
  fake parser into `connectors.PARSERS`, so the real `make()` and `_scan_one` run. `discovery.absorb` handles the
  sighting case, and `annotate_v31` ranks the result as a live lead.
- Goldens: `golden_v1/oracle_tagging.json`, 12 cases and 64 kept records:
  - 4 sources: high + probation, medium, low, missing reliability;
  - 15 records each: broad / distinctive / multi-word keywords, noise including `"handel "`, bio, every tier, the
    `or 5` case, interstitial before and after 400, a keyword after 600 and after 120;
  - the 7 Cycle 008 companies/opportunities;
  - grok + manual absorb.
- Every old field is either compared or on an explicit `NOT_PORTED` list (clock, url, location and run plumbing, none
  of them a ranking input). An unlisted extra old field fails.
- `python -m projectzero.ops.parity_tagging goldens` gives **0 differences**, tables included.
- The mapped inputs are asserted by hand, independently of the mapping: description = key_fact, tiers
  `manual`×6 + `pre_company`, Grok scout / live-grok / medium, no probation.
- JSON round trip: `archetype_hits == [6, 5]`, all of them `int`.
- Hosted, through intake → jsonb → adapter → HTTP: all 7 Cycle 008 candidates are `full`. `attention_v2` equals the
  old `annotate_v31` on the old per-source record (0 diffs), with `archetype_hits`, `why` and `priority` as the old
  scan gave them. List and detail agree.

**Mutation checks**
- Offline: 10 of 10 caught — `or 4`, `[:601]`, `"handel"`, dropping "chemical" from AMBIGUOUS_KW, `[:401]`, absorb +1,
  no `stealth` tier, keeping the generated note, archetype sort order, disabling the interstitial refusal.
- Hosted: removing the retag call on a re-report is caught.

**Results**
- Gate: ALL CHECKS PASSED (pytest **619**, ECMA 4, PGlite 22).
- Hosted: **41 passed**.
- Live `pz` untouched.

**Not in 007** (as planned): registry-scan tagging and run state (`run_id`, `last_run`, batch merge). Registry
re-reports of a live lead add no sighting until the scanner port defines that source's mapping.

## Codex verdict on implementation

**APPROVE WITH CHANGES.** The 558 local Deal Flow tests passed from the backend directory. Decision 0002 row 7 settles the noise behavior. The long-name hosted case and longer-description oracle case cover the truncation boundary within the live contract.

Fix trusted intake validation before closing 007. In `contract.py`, `validate_entity` calls `content_issues` even when schema validation has found malformed fields. If `kind` is a JSON array or object, checking membership in the `COMPANY_KINDS` frozenset raises TypeError. That interrupts the delivery before trusted intake can report a refusal for that entity and process its valid sibling. Guard the membership check with a string type check or run content validation only after schema success. Add a mixed trusted-delivery regression asserting the indexed refusal and the valid sibling's acceptance.

### Claude — revision 2 (2026-11-11 11:17 CET)

**Fixed.** `content_issues` now checks `isinstance(kind, str)` before the `COMPANY_KINDS` membership test. A list or
object `kind` used to raise `TypeError`; now it is left to the schema, which reports it on its own entity.

Regression in `test_tagging.py`: a mixed trusted batch `[malformed kind, valid company]`, parametrised over
`["company"]`, `{...}`, `7` and `None`. Each case must give:
- outcome `partial`, with 1 accepted;
- entity 0 refused, every issue under `$/entities/0`;
- a resolver that saw only `[1]`;
- a stored submission that records the refusal at index 0.

Without the guard, the list and object cases fail with the crash you described.

Gate: ALL CHECKS PASSED (pytest **623**, ECMA 4, PGlite 22).

## Codex verdict on revision 2

**APPROVE.** Trusted intake now records an indexed refusal for a malformed kind and sends the valid sibling to the resolver. The regression covers array, object, numeric and null values. All 562 local Deal Flow tests passed.

## Grok notes
