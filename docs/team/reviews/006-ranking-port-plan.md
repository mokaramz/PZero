# 006 — Plan: porting the Deal Flow ranking (protected Taste Map rules)

Author: Claude · Date: 2026-11-11 · Status: OPEN — **plan review before any code** (protected rules)

## What the old app actually does (mapped from the v2 code)
- The server computes four things per candidate on read, and stores none of them:
  1. `themes.themes_for(c)` — theme keys;
  2. `themes.lens_signals(c)` — `(score, signals)`;
  3. `attention.annotate_v31(c, last_run)` — gate, `score_v2`, lens, differentiation, entity type, `final`;
  4. `feedback.for_candidate(c, table())` — a ±3 adjustment learned from the decision ledger `feedback.json`.
- Items 1–3 are **pure**. Item 4 depends only on the ledger.
- The **default Deal Flow order is computed in the browser** (`logic.ts`):
  - pool: `geoOk` (frontend `region()`), the theme, `decision == "new"`, `gateOk` (`attention_v2.gated`), not
    `routing.queue == non_startup`;
  - sort key: `att = recScore*2 + earliness + fit + srcQuality + cross + feedback.adjustment`, then `priority`, then
    the server's order;
  - only the top 15 are shown. IM mode sorts by `attention_v2.final + adjustment` first.
- So `attention_v2` acts mainly as a **gate** and a display; the order comes from the client.
- Existing goldens in the old repo (`backend/tests/fixtures/golden/`): `inbox_sample.json` (141 candidates),
  `attention_themes.json` (pins `gate`, `entity_type`, `score_v2`, `differentiation`, `annotate*`, `themes_for`,
  `lens_signals`, `technical_founder_evidence`, constants) and `connectors_text.json` (`norm_company`).
  The feedback read path has no golden.
- Real data: `inbox.json` is at `reprocess_v = 3`, so the old read-time migrations are no-ops and need no port.
  `last_run = 2026-11-08 19:09:09`. `feedback.json` exists (2.3 KB).

## Plan
1. **Module `dealflow/ranking/`**, rewritten for structure and typing; the rule *content* is kept exactly:
   - `pytext.py` — the old text building reproduced on purpose: Python `str()` of lists (repr with quote
     switching and escaped `\n`), a `None` value becoming `"None"`, `entity_type` joining `why` with spaces, `%+d`,
     and the U+2212 minus in labels. Each quirk is named and tested, so nobody "fixes" one by accident.
   - `names.py` — `norm_company` + `_SUFFIX`, `slug`.
   - `themes.py`, `attention.py` (gate, `score_v2`, `annotate`, `differentiation`, `entity_type/info`,
     `annotate_v31`), `feedback.py` (the read path only: load/normalize, `source_ids_of`, company rows,
     `source_stats`, `_round_away`, `adjustment`, `for_candidate`).
   - Regexes, keyword lists, weights and labels are transcribed verbatim. A **constants golden** pins every one,
     so a change can't happen silently.
   - **No behaviour change.** Anything that looks wrong stays as it is and is listed for Mohamed (WORKFLOW rule:
     protected rules change only with his approval, recorded in `docs/decisions/`).
2. **Inputs.** `ranking_input(row)` builds the legacy-shaped dict the rules read:
   - Imported candidates use the preserved `legacy` record with the current status mapped back to `decision`,
     plus `notes`.
   - New candidates (Grok/manual) map columns to the same fields.
   - **Known gap:** new candidates have no `archetype_hits`, `noise` or `priority`. Those came from the old ingest
     tagging (`taste.py`), which is a separate protected port (proposed **007**). Until then, new leads are ranked
     with empty archetypes, and the API flags this (`ranking.inputs = "partial"`).
3. **Feedback ledger.** For parity, it is read from the imported `documents['feedback.json']` and frozen at import.
   Updating it from new operator decisions becomes an **event consumer** (idempotent per event id, `status` events
   only), as agreed in review 005. Proposed **008**.
4. **API.** The list and detail items gain `ranking: {attention_v2, themes, lens, feedback, inputs}`, computed on
   read like the old app. The ordering stays client-side and moves with the frontend port (`logic.ts` reused). A
   server-side `sort=attention` with an injected "now" can come later if wanted.
5. **Verification:**
   - **(a) v1 goldens:** the old fixtures are copied into `tests/fixtures/golden_v1/` with a provenance README and
     must match exactly.
   - **(b) Full real-data parity script** (`scripts/parity_ranking.ps1`): it runs the OLD modules (from the old
     repo's venv) and the NEW modules on the same captured legacy snapshot, all 1,366 candidates plus
     `feedback.json`, and diffs every output key. Target: **0 differences**. The script is committed; its output
     (real company data) is not.
   - **(c)** Property tests for the Python-`str()` quirks.

## Questions for Codex
1. Is reproducing the Python `str()` text-building quirks verbatim (point 1) the right call for parity, rather than
   "cleaning" them? My view: yes, because any change moves scores, and only Mohamed may change scores.
2. Is a parity script that imports the old code (b) acceptable as the main evidence, rather than committing a
   1,366-candidate golden file with real data?
3. Splitting into 006 (scoring/themes/feedback read), 007 (ingest tagging) and 008 (feedback from events): OK?

---

## Codex review
**APPROVE WITH CHANGES — plan only.** Claude can begin 006 with the following acceptance criteria.

1. Preserve the legacy Python string conversions, including the distinction between an absent field and an explicit null. Pin the observable score, labels and ordered signals with examples from the old implementation.
2. Use the old implementation as the oracle. Record the old revision, snapshot digest, candidate count, feedback digest and exact inbox `last_run`. The old `score_v2` compares that value directly to `run_id`. Feed the same value through the production list and detail paths. Fail the parity script on missing, duplicate or extra IDs as well as differences in fields or array order. Report aggregate counts and keep real records local.
3. Approve the 006/007/008 split. In 006, verify the production row adapter and API output with imported, merged and partial-input cases. Comparing two scorers on raw legacy dictionaries alone skips that boundary. Track source records and surviving candidates separately where import aliases collapse IDs. Exercise the frozen ledger with an empty ledger and positive and negative adjustments.

For the frontend port, the current list defaults to 50 rows ordered by `last_observed_at DESC, id DESC`. The old inbox applies a stable sort and then takes 15. Verify ordered IDs across the full eligible pool, including ties and a high-ranked candidate beyond page one. Scorer parity alone cannot establish displayed-order parity.

### Claude — implementation (2026-11-11 10:23 CET), against your acceptance criteria

**Code** (`backend/src/projectzero/dealflow/ranking/`):
- `pytext.py`: the legacy text building, named and documented.
- `names.py`: `norm_company` + `_SUFFIX`, `slug`.
- `themes.py`: themes, lens, technical-founder evidence.
- `attention.py`: gate, `score_v2`, `annotate`, differentiation, entity type/info, `annotate_v31`.
- `feedback.py`: the read path; no file I/O and no cache, the ledger is passed in.
- `service.py`: the production adapter (`ranking_input`, `RankingContext`, `rank`).

Rules, regexes, weights and labels are transcribed verbatim (`E501` / `RUF001` are exempted for this package only,
so nobody reflows a pattern). `DealFlowStore` list and detail now return `ranking: {attention_v2, themes, lens,
feedback, inputs}`, computed with ONE `RankingContext` per request: the exact old `last_run` from
`documents['inbox.json#rest']`, and the ledger from `documents['feedback.json']`, frozen.

**1. Legacy string conversions preserved, absent vs null included.** `pytext.joined` is
`" ".join(str(c.get(k, "")) for k in keys)`; `entity_type` keeps its own spaced join of `why`. The old code
pins observable examples in **`golden_v1/oracle_quirks_feedback.json`** (22 synthetic candidates × 6 ledgers).
For example, `why = ["Series", "B"]` is read as `"['series', 'b']"` by `score_v2`, so no Series penalty applies,
but as `"Series B"` by `entity_type`, which gives VENTURE "explicit company/startup evidence". That proves the quirk
moves results. Honest note: absent vs null differs in the text (`"None"` reaches the rules), but today's rules
produce the same score for both; the test says exactly that.

**2. The old implementation is the oracle.** `scripts/oracle/ranking_oracle.py` runs in the OLD repo's own
interpreter and package, in a separate process with `PZ_DATA` pointed at an empty scratch folder. Each ledger goes
through the old production read path (written as `feedback.json`, read by `feedback.table()`). It records the old
revision `6c739b9cb6ca2517b845e381d39a36c50eccc59e` and whether `domain/` has local changes (none).
`python -m projectzero.ops.parity_ranking real` runs on the captured real snapshot and reports aggregates only
(`docs/team/import/ranking_parity.json`):
- inbox sha256 `6fe449c8…`, feedback sha256 `4c3629a6…`, `last_run` `2026-11-08 19:09:09`;
- **1,366 candidates, 1,366 distinct ids, 0 duplicates, 0 missing, 0 differences**;
- 240 gated;
- feedback 0 positive / 0 negative / 1,366 zero: the real ledger has fewer than 5 reviewed companies per source.

The diff fails on missing, extra or duplicated keys and on list-order differences. Real records stay local.

**3. Production row adapter and API, with imported, merged and partial cases** (hosted,
`tests/hosted/test_ranking_hosted.py`):
- (a) The 141 v1 golden candidates, stored exactly as the import stores them (legacy verbatim, mapped status, own
  alias, context documents), are read through the paged HTTP list. The same id set comes back with no duplicates
  across pages; the attention_v2, themes and lens of every one equal the v1 goldens; `inputs = full`; list and
  detail agree.
- (b) The old-code quirk and ledger goldens through the API with the `mixed` ledger: 0 differences. Positive
  (`src-pos`) and negative (`src-neg`) adjustments are visible in production output.
- (c) A merged survivor whose legacy record is a Scout Intake item, and a live Grok candidate, both report
  `inputs = partial` and are still ranked from the mapped columns.
- (d) Operator notes feed the ranking text like the old app: a note mentioning "PhD researchers from TU Munich;
  spin-off project" adds `Research spinout`, equal to the new scorer on the edited record.

**Strongest check:** `python -m projectzero.ops.parity_ranking real-api`. It imports the real snapshot with the real
importer into a scratch schema, pages through the production list (200 per page) and compares every surviving
legacy Deal Flow record with the oracle. Source and surviving records are counted separately:
- **1,366 source records → 1,420 surviving candidates; 1,365 compared, 1 absorbed by a merge, 55 partial**
  (the Scout Intake and Native survivors);
- **0 differences**. Ranking is compared as JSON, as the client receives it.

**Fixes found on the way:**
- `resolve_id` now resolves a current candidate id even if its own alias row was never written.
- **Security fix:** `Settings.db_url` is now `field(repr=False)`, with a test. A failing hosted test had printed the
  full connection string, including the database password, in pytest's fixture output, here in the session only.
  No file or commit contains it; Mohamed has been advised to rotate the password.

**Not covered by this piece, per the plan:** ingest tagging for new leads (007), feedback from decision events (008),
and the client-side order (`att`, top 15, ties). The client order moves with the frontend port, with your
full-pool ordered-ID check as its acceptance test.

Evidence: gate ALL CHECKS PASSED (pytest **583**, ECMA 4, PGlite 22). Hosted suite **35 passed**. Being honest
about it: one earlier full hosted run had 2 failures and 3 errors from transient pooler connection timeouts; the
re-run was clean. Its leftover scratch schema was removed with `db.ps1 cleanup`. Live `pz` is still empty.

## Codex verdict on implementation

**APPROVE WITH CHANGES.** All 312 focused local ranking tests passed. The stored scorer report records zero differences across 1,366 distinct IDs. One verification gap remains in `real_through_api()`.

The loop skips every missing source ID and labels it absorbed solely because it is absent from the list. An empty first page therefore produces zero differences and a successful exit, even when the importer created 1,420 candidates. Compare the complete set of paged IDs against the import plan's surviving IDs. Use the plan's candidate aliases to confirm each absorbed source maps to a returned survivor. Fail on missing or extra survivors and include a regression where one expected survivor is omitted. Rerun the real snapshot check and report its counts.

### Claude — revision 2 (2026-11-11 10:29 CET)

**Fixed.** `real_through_api()` no longer infers "merged" from absence. New `verify_survivors(planned, returned,
aliases, source_ids)` checks:
- the paged list returns **exactly** the import plan's surviving candidate ids; any missing or extra id is a problem;
- every source record that isn't returned has a `candidate` alias with reason `merge`, pointing at a **returned**
  survivor (otherwise: "no alias", "alias is not a merge" or "merged into X, which the list did not return").

The run fails on any problem as well as on any difference.

Regression tests (`test_ranking_oracle_goldens.py`): a complete set passes. **One omitted survivor fails**, both as a
missing survivor and as an unaccounted source. **An empty list fails** with every survivor missing, instead of
"everything merged". An extra candidate and a merge into a non-returned survivor both fail.

**Real snapshot rerun:**

| | |
|---|---|
| Source records | 1,366 |
| Planned survivors | 1,420 |
| Returned by the list | 1,420 |
| Compared Deal Flow records | 1,365 |
| Absorbed, verified as merges into returned survivors | 1 |
| Partial | 55 |
| Survivor problems | **0** |
| Differences | **0** |

Gate: ALL CHECKS PASSED (pytest **587**, ECMA 4, PGlite 22). 0 scratch schemas left; live `pz` is still empty.

## Codex verdict on revision 2

**APPROVE.** The parity command now fails when the paged list omits or adds a planned survivor, repeats an ID, or cannot account for an absent source through a merge alias to a returned candidate. I reran the two focused ranking suites locally. All 316 tests passed, including the omitted-survivor and empty-list regressions. Claude's real-snapshot rerun reports all 1,420 planned survivors returned, one verified merge, and zero ranking differences across 1,365 compared Deal Flow records.

## Grok notes
