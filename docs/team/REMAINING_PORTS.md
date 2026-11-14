# What remains after the 14 views (2026-11-13)

The read side of every view in [PORT_ORDER.md](PORT_ORDER.md) is ported (reviews 009–033a), and so is the
background-jobs runner (032c). Each item below is still shown in the app as deferred, with its visible reason. My
recommended order (Mohamed's standing instruction; Codex, please challenge it) puts first what Mohamed loses at the
cutover if it is missing, then what only completes a view.

| # | Port | What it brings back | Notes |
|---|---|---|---|
| 1 | ~~**Deal Flow scan**~~ (done, 034a) (`scan`, `scanReport`, `scanHistory`) | Finding new candidates: the weekly `deal_flow_scan` job, Find New Candidates, the per-source report | Network only; the core of sourcing. The runner job becomes ported. |
| 2 | **Machine triage** (`triage`: accept / override, `triage_retry`, `triage_compression`) | Triage proposals on new candidates, the retry after a provider outage, the attention compression | Paid model calls, through the gateway (off until Mohamed turns paid calls on). Split in three (H-349): 035a accept / override / batch reject and the decision log (no model calls); 035b the cascade, post-scan auto-triage, `triage_retry` and Retry now; 035c the compression run, after items 4 and 5. |
| 3 | ~~**Watch sensors**~~ (done, 037a + 037b) (`watch`, the `watch_checks` job) | The WATCH page checks and their triggers | Network. |
| 4 | **Case preparation** (`case_refresh`) | Fresh prepared cases (they expire 2026-11-15 in the imported snapshot) | Paid model calls. |
| 5 | **Analysis** (`analysis`, `reviewQueue`, `redTeam`) | The Agent Review Queue, machine analysis, the red team | Paid model calls; lifts the desk's (d). |
| 6 | **Claim Index / verification** (030b) | One-click verification proposals | Lifts Today's (e) and Conviction's Verification deferral. |
| 7 | **Source network** (`source_network`) | New-source discovery and decisions | Network. |
| 8 | **Hardening** (032b) | Backups, integrity, governance and releases, redesigned for Supabase | Lifts System health's (d). |
| 9 | **Identity** (`founders`) | Founder identities in Deal Flow | |

**Small follow-ups** (each a small review of its own):
- Today's WATCH section: harden it against an archived trigger line with neither `url` nor `source` (it raises
  `KeyError: 'source'`, as the old code did; 0 such lines exist today) — a declared difference (037b H-391).
- ~~**Before the cutover:** a set-based triage batch confirm~~ (done, 035d: 500 in 2.65-3.00 s, from 207 s; the 2 s
  end-to-end target is missed by the connect and the eligibility re-read, accepted in H-367).
- Conviction's request clock: its naive `datetime.now` fallback, read and write timestamps together (032a H-301).
- The importer skipping and reporting malformed legacy records (031a finding).
- `bounded_transaction` moved into `core/db`.
- ~~Strict boolean `confirm` on the confirming write routes~~ (done, 036a: 10 gates, plus a pytest report scrubber for
  the database password and the Evaluator hosted test stale since 026a).

**The cutover** (Mohamed's steps, in this order, documented in 032c):
1. pause the old task "Project Zero - background jobs";
2. run the live import;
3. register and enable "Project Zero v2 - background jobs".

Until items 1–4 are ported, the scan, the triage, the watch checks and the case preparation stop at the cutover.
That is a product decision for Mohamed: cut over now with the deferrals visible, or wait for 1–4.

## Codex review of the order (H-334)

Start the Deal Flow scan survey now. Keep machine triage second so the next port can exercise the scan’s actual candidate output, including what happens when paid access is off. For a cutover near November 15, move case preparation ahead of watch sensors if Mohamed needs fresh cases and intends to enable paid access. Otherwise keep watch sensors third. The snapshot expiry is a reason to prioritize that decision, not a deadline for every port.

Keep the remaining feature order. Before the live import, check the malformed-record finding against a rehearsal and reconcile any skipped records. Before enabling scheduled writes, establish what backup can be restored and how to roll back the handover. The v2 runner omits the old background backup. These checks can happen alongside the scan work while the broader 032b redesign stays eighth. Mohamed retains the cutover decision.
