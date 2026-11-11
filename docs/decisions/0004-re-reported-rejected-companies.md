# 0004 — Re-reports onto rejected companies: absorbed quietly, flagged for revisit on material change

Date: 2026-11-11 · Decided by: Mohamed (owner); relayed by Grok in H-087, **confirmed by Mohamed in chat on
2026-11-11 19:01 CET** · Status: **accepted** (the `material_change` contract field and the Revisit list are built in their own
review)

## Context
Review 004 Q2 (H-024) asked what live intake should do when Grok re-reports a company whose Deal Flow candidate is
already rejected. Today intake records the evidence on the newest closed candidate (`re_reported_closed`) and never
changes its status (review 004 rule: intake never sets a status).

## Decision
- **Default: absorbed quietly.** The status stays `rejected`, there is no Today card, and the observation is still
  recorded as `re_reported_closed`, as it is now.
- **Exception: flag for revisit.** The flag is never an interrupt and never an automatic reopen. It applies when the
  re-report carries a material change since the rejection date:
  - a new funding round or registry event;
  - a new founder or key hire;
  - independent corroboration from 2 or more scouts or sources.
- Flagged re-reports appear in a short **Revisit** list (the weekly brief or a Deal Flow filter) with the reason and
  the evidence.
- **Only Mohamed reopens a candidate.**

## Proposed delivery field (Grok asked which field to fill)
An optional per-entity `material_change` object in the intake contract:

```json
"material_change": {
  "kind": "funding_round | registry_event | founder_or_key_hire | independent_corroboration",
  "since": "YYYY-MM-DD",
  "evidence_url": "https://…",
  "note": "…"
}
```

`kind` and `evidence_url` are required inside it, and the URL must also be one of the entity's `evidence` URLs. Intake
flags a revisit only when `kind` is set **and** the candidate is closed **and** the evidence is dated after the
rejection. The contract change and the Revisit list are a separate review once this decision is confirmed.

## Consequences
- No change to current behaviour until the contract review lands.
- When built: `re_reported_closed` observations with a valid `material_change` get a revisit flag (an event, never a
  status change), and a Deal Flow "Revisit" filter lists them.
