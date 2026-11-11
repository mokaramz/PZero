# 0002 — How Grok leads enter the old ingest tagging (and therefore the ranking)

Date: 2026-11-11 · Decided by: Mohamed (owner) · Status: accepted

## Context
The protected ranking rules (review 006) read fields that the OLD scan computed at ingest: archetype hits, twins,
noise, `why`, priority, sectors, discovery tier and source quality. They were designed for registry scans and news
feeds. Grok deliveries (which replace Scout 00) have different fields, and each way of mapping them onto the old
inputs moves scores. These are product decisions, so the owner makes them.

## Decision
| # | Question | Decision | Effect |
|---|---|---|---|
| 1 | Where does Grok's `key_fact` go? | **`description`** | Archetypes, twins, noise, sectors, the gate and the stage penalties all read it, so Grok leads are tagged and scored like registry records. (The old Scout Intake → Conviction path used `why_found`; that path is not Deal Flow ranking.) |
| 2 | Discovery tier | **From stage, else `manual`**: `pre_company` if `stage == "pre_company"` or `flags` contains `pre_company` or `stealth`; otherwise `manual` | Pre-company gets +20 / lens +2 / priority base 3; manual is neutral. Never the news-feed −8. |
| 3 | Grok as a source | **A scout channel**: source name `"Grok scout"`, reliability `medium` (`src_quality` 1) | `_MANUAL_SRC` matches "scout": +8 "Non-obvious / proprietary source". No high-reliability bonus. |
| 4 | Extra evidence links | **Evidence only**, never `also_seen` | Only a genuinely different origin (e.g. the same company also found by a registry scan) is a cross-source sighting. |
| 5 | Does a Grok delivery set the global `last_run`? | **No** (default derived from 1–4) | "New this run +5" stays a registry-scan concept, so Grok deliveries never take it away from the latest scan. |
| 6 | Probation line | **None** for Grok | No extra scored `why` text. |
| 7 | A noisy live lead (holding / consulting / services keywords) | **Kept `new`, hidden from the Attention Queue** (Mohamed, 2026-11-11, "keep and hide") | The old ingest auto-rejected it (`decision = rejected` + an auto-reject note). Live intake never sets a status, so the lead stays `new`; its `noise` flag makes the protected gate hide it ("flagged as noise by sourcing"). The generated auto-reject note is NOT written into operator notes. |

Manual (operator paste) deliveries follow the same mapping with source name `"Manual"` (`_MANUAL_SRC` matches
"manual": +8, the old meaning of a manual source) and reliability `medium`.

## Consequences
- Grok leads compete in the Deal Flow ranking on the same rules as registry records, with a scout-channel bonus.
- The mapping lives in one place (`dealflow/ranking/tagging.py`, review 007) and is pinned by tests. Changing any
  row above is a new decision record.
