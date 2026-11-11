# 0003 — The three open architecture questions

Date: 2026-11-11 · Decided by: Claude's recommendation, accepted under Mohamed's standing instruction of 2026-11-11
("generally commit and continue until you finish and approve your recommended choices") · Status: accepted, open to
Mohamed's override

## Context
`docs/ARCHITECTURE.md` §8 left three questions open, each with a draft assumption. They shape the next pieces (the
Deal Flow view, background jobs), so they are settled here. Any of them can be reopened by a new decision record.

## Decision
| # | Question | Decision | Why |
|---|---|---|---|
| 1 | Keep calling Grok over the xAI API on a schedule (the old weekday "search bridge")? | **No. Grok's direct delivery into intake is the only Grok path.** No xAI adapter is built now. | Mohamed: Grok works directly in the folder and delivers results itself; "no deep infra doing the job of Grok". Scout Bridge is removed. |
| 2 | May a lead with **no public URL yet** (stealth, social-only) be submitted as provisional? | **No. At least one public web URL stays a hard rule** of the intake contract. | The iron rule: the tool never invents facts. Every lead must be checkable. Grok can still report it once a URL exists. |
| 3 | Who else can sign in? | **Single operator, backend-only access.** No sign-in UI. The API binds to 127.0.0.1, and RLS keeps the public keys reading nothing. | Matches today's use. Adding users later is a new decision with auth design. |

## Consequences
- No xAI client, scheduler job or API key handling for Grok is written.
- `contracts/intake_submission.schema.json` keeps `evidence` with at least one URL as required.
- The frontend has no login screen. The backend never serves a browser key.
