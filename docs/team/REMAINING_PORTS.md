# What remains after the 14 views (2026-11-13)

The read side of every view in [PORT_ORDER.md](PORT_ORDER.md) is ported (reviews 009–033a), and so is the
background-jobs runner (032c). Each item below is still shown in the app as deferred, with its visible reason. My
recommended order (Mohamed's standing instruction; Codex, please challenge it) puts first what Mohamed loses at the
cutover if it is missing, then what only completes a view.

| # | Port | What it brings back | Notes |
|---|---|---|---|
| 1 | **Deal Flow scan** (`scan`, `scanReport`, `scanHistory`) | Finding new candidates: the weekly `deal_flow_scan` job, Find New Candidates, the per-source report | Network only; the core of sourcing. The runner job becomes ported. |
| 2 | **Machine triage** (`triage`: accept / override, `triage_retry`, `triage_compression`) | Triage proposals on new candidates, the retry after a provider outage, the attention compression | Paid model calls, through the gateway (off until Mohamed turns paid calls on). |
| 3 | **Watch sensors** (`watch`, the `watch_checks` job) | The WATCH page checks and their triggers | Network. |
| 4 | **Case preparation** (`case_refresh`) | Fresh prepared cases (they expire 2026-11-15 in the imported snapshot) | Paid model calls. |
| 5 | **Analysis** (`analysis`, `reviewQueue`, `redTeam`) | The Agent Review Queue, machine analysis, the red team | Paid model calls; lifts the desk's (d). |
| 6 | **Claim Index / verification** (030b) | One-click verification proposals | Lifts Today's (e) and Conviction's Verification deferral. |
| 7 | **Source network** (`source_network`) | New-source discovery and decisions | Network. |
| 8 | **Hardening** (032b) | Backups, integrity, governance and releases, redesigned for Supabase | Lifts System health's (d). |
| 9 | **Identity** (`founders`) | Founder identities in Deal Flow | |

**Small follow-ups** (each a small review of its own):
- Conviction's request clock: its naive `datetime.now` fallback, read and write timestamps together (032a H-301).
- The importer skipping and reporting malformed legacy records (031a finding).
- `bounded_transaction` moved into `core/db`.

**The cutover** (Mohamed's steps, in this order, documented in 032c):
1. pause the old task "Project Zero - background jobs";
2. run the live import;
3. register and enable "Project Zero v2 - background jobs".

Until items 1–4 are ported, the scan, the triage, the watch checks and the case preparation stop at the cutover.
That is a product decision for Mohamed: cut over now with the deferrals visible, or wait for 1–4.
