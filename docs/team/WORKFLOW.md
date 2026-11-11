# How the team works

| Role | Who | Does | Does not |
|---|---|---|---|
| Owner / decision maker | Mohamed ("Smooth Operator") | Sets goals, answers open questions, approves merges to `main` | — |
| AI engineer | Claude | Designs, writes code and tests, writes review requests, applies review feedback | Merge without a review verdict on design-level changes |
| Mentor & reviewer | Codex | Reviews designs and diffs, challenges decisions, flags bugs and risks, gives a verdict | Write production code on the same branch Claude is writing |
| Search, refine & review | Grok | Researches (libraries, sources, data quality, market facts), refines prompts/source lists, second-opinion reviews; in the product, delivers leads through the intake contract | Write database tables directly; make investment decisions |

## Shared channel

All coordination goes through **[HANDOFF.md](HANDOFF.md)**. It is append-only, and every entry carries its number,
time, sender → recipient and topic. Claude checks it for changes every minute.

## The loop (one piece of work at a time)

1. **Claude** finishes a piece on a branch `feat/<area>` and writes a review request
   `docs/team/reviews/NNN-<topic>.md` from [the template](reviews/TEMPLATE.md): what changed, why, what to look at,
   how it was tested, open questions.
2. **Codex** reviews and appends a `## Codex review` section: findings (blocking / should-fix / nit) and a verdict:
   `APPROVE`, `APPROVE WITH CHANGES` or `REQUEST CHANGES`.
3. **Grok** is asked for a `## Grok notes` section when the piece depends on outside facts (an API's behaviour, a
   source's reliability, best practice for a library).
4. **Claude** answers each finding inline (`fixed in <commit>` / `won't fix: <reason>`), then asks Mohamed to merge.
5. Disagreements that the reviewers and Claude can't settle go to Mohamed as one short question.

## Ground rules

- `main` only receives reviewed work. Small, reviewable pieces beat big drops.
- The quality gate (`scripts/check.ps1`, once it exists) must pass before a review request is written.
- Secrets live only in `.env` (git-ignored). Nobody pastes keys into chats, review files or commits.
- Protected investment rules (Taste Map v2.2) change only with Mohamed's explicit approval, recorded in
  `docs/decisions/`.
- UI follows the old design system (`docs/design-system.md` from the old repo, to be carried over): no AI branding,
  forbidden hues, one primary action per decision area.

## Grok delivering leads (product path)

Grok works in this folder. To deliver a hunt or pulse it writes a JSON file that follows
[`contracts/intake_submission.schema.json`](../../contracts/intake_submission.schema.json) and, from `backend\`:

```
.venv\Scripts\python -m projectzero.cli.main intake check  path\to\delivery.json   # validate only, writes nothing
.venv\Scripts\python -m projectzero.cli.main intake submit path\to\delivery.json   # record + resolve into Deal Flow
```

(`pz intake …` is the same command once the package's `pz` script is on PATH.)

`submit` answers with one line per entity: created / re_reported / re_reported_closed, the candidate id, and how the
company was resolved (strong identifier, same name from another origin, created, identity conflict).
- A refused delivery (exit 2) writes nothing; fix it and resubmit.
- The same file twice is a duplicate (exit 0, no change).
- **Until the one-time legacy import has run, `submit` answers CLOSED (exit 3).** Use `check` meanwhile.
