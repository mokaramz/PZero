# Project Zero (optimized)

Clean rewrite of Project Zero — the personal deal-sourcing and investment-intelligence workbench — on Supabase, with
one merged Deal Flow pipeline and a modular codebase. Same product, same rules, same UI.

**Status:** design phase. Start here:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — what changes, the pipeline, module layout
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — schema and how all existing data is kept
- [contracts/intake_submission.schema.json](contracts/intake_submission.schema.json) — how leads (Grok) enter
- [docs/team/WORKFLOW.md](docs/team/WORKFLOW.md) — how Claude, Codex and Grok work together
- [docs/team/reviews/](docs/team/reviews/) — open review requests

The previous version lives in `Desktop\project-zero` (reference only) and its data in `Desktop\project-zero-data`
(read-only source for the one-time import).

## Setup (once the backend exists)

1. Copy `.env.example` to `.env` and fill in the Supabase values from your project's settings.
2. Apply the schema: `npx supabase db push --db-url "$SUPABASE_DB_URL"` (no Docker needed).
