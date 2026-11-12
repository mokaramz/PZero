# Port order for the remaining views

Recorded 2026-11-12 after review 018, as a recommendation under Mohamed's standing instruction ("continue until you
finish and approve your recommended choices"). Codex can challenge it in any plan review. Already ported: Deal Flow
with Scout Intake (merged), Conviction, Network (people, watchlist), Events.

## Rules for every port
- **No Scout Bridge.** It is not part of the rewrite. Every old `bridge_create` button (Sources, Ecosystems, News,
  Founder Radar, Health) is left out the way Deal Flow handles controls that are not ported. No xAI transport is
  ported.
- **Leaves first.** Read-only before writes. A service that another view needs comes before that view.
- **Paid calls last.** Views that call an LLM or fetch from the network wait until the inference ledger and budget
  are rebuilt.
- **Old data.** 14 files are fully modelled by the legacy import. Every other `*.json` is a `documents` row and every
  other `*.jsonl` is raw bytes. A port that needs one of those models it first, in its own migration.

## Order
| # | View | Why here |
|---|---|---|
| 1 | Radar (`/radar`) | One read endpoint over modelled data (inbox, real_data); `meta` already exists. |
| 2 | Public work (`/public-work`) | A self-contained create, edit and delete over one document. |
| 3 | Sources (`/sources`) | `sources.json` is modelled; the toggle is a single write. |
| 4 | Ecosystems (`/ecosystems`) | Deterministic ecosystem and coverage code that Map needs; one small write. |
| 5 | Founder Calls (`/founder-calls`) | The domain the Evaluator and Today reuse; no LLM. |
| 6 | Active Evaluator (`/evaluator`) | Needs the founder-calls and IMQ domains, plus two Founder Radar operations it owns, with their separate persistence kept: `add_evidence` (validates and returns an evidence row, which a public resolution appends to the claim ledger) and the `verified_facts` read (separately confirmed company facts). Founder Radar (step 8) reuses them. Acceptance (Codex H-139): after a reload, a resolved public claim still has its evidence in the claim ledger, and the company's verified facts are unchanged (a public resolution does not promote a fact). No LLM or network. |
| 7 | Map (`/map`) | Mostly read-only once Ecosystems is in; must tolerate missing News and source-network data. |
| 8 | Founder Radar (`/founder-radar`) | Large, with heavy writes and web fetching, but nothing depends on it. |
| 9 | Validation (`/validation`) | Append-only, no LLM; the read side first. |
| 10 | News & Learning (`/news`) | The first paid LLM and network view; lands with Validation (they import each other). |
| 11 | Today (`/today`) | A read model over watch, case prep and the compressor; after those services exist. |
| 12 | Investment Desk (`/`) | A dashboard over Today, Sources and the review queue. |
| 13 | System health (`/health`) | Reports on everything else; the read side first, then the background-job actions. |
| 14 | PZ Associate (`/associate`) | An LLM agent whose tools wrap almost every other view. |

The background-jobs port (the scheduled event scan, catch-up) runs alongside 10–13.
