# 019 — Plan: the Radar, the Scout memo, the outreach email and the weekly update

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
The Radar is first in the [port order](../PORT_ORDER.md): it reads only modelled data (the Conviction entries, plus
the inbox for one check). The Conviction port (011) left four parts visible but disabled with the reason "arrives
with the memo & email port" (`NOT_PORTED.memo`, `.weekly`, `.radar`): the Scout memo, the outreach email, the weekly
sourcing update and "Generate the Radar". All four are deterministic text over the same records, built from the
protected gold-master module `domain/radar.py` plus `people.weekly_update`. They belong with the Radar.

None of this calls an LLM, a paid API or the network.

## Scope of 019
1. **The Radar page** (`/radar`, old `features/radar/RadarPage.tsx`). A port of the old page: 8 high-confidence, 1
   emerging and 1 wildcard slots, fully verified only; then the Research Queue, Conflict-gated and Watchlist
   sections. Empty slots stay empty. Each card links to `/conviction?company=<slug>` and has the convergence trace.
   - **Backend.** `conviction/radar.py::compose(signals)` is a mechanical port of `taste.compose_radar`. It runs over
     the SAME signals `GET /api/conviction/pipeline` returns (their `sc` is the old `taste.score` of the record),
     with `_`-prefixed keys stripped as the old `radar_view` did.
   - **Route.** `GET /api/conviction/radar`.
2. **Scout memo and outreach email.**
   - **Routes.** `GET /api/conviction/memo?c=<slug>` and `GET /api/conviction/email?c=<slug>` return `{text}`. An
     unknown slug returns the old 404 body.
   - **Templates.** `memo` and `email` (with `EMAILS` and `_l`) are copied mechanically from the protected
     `domain/radar.py`. The wording, ordering and printf templates are frozen.
   - **Page.** These Conviction parts come alive: the case page's "Outreach email — timing-aware" (with Copy) and
     "Scout memo", the Email drawer, and the Actions menu's "Email draft".
3. **The weekly sourcing update.**
   - **Route.** `POST /api/conviction/weekly {insight, question}` returns `{text}`.
   - **Logic.** A port of `people.weekly_update`. It reads, over a 7-day window, the Conviction entries, the people
     and the events (current records). Nothing is written.
   - **Page.** The Conviction page's Weekly drawer comes alive. The Investment Desk's "Compose weekly update" waits
     for the Investment Desk port.
4. **"Generate the Radar"** (old `POST /api/run`). The old action wrote `weekly_memo.html` plus `output/memo_*.md` and
   `email_*.md` into the data folder. The rewrite has no data folder. See decision (c).
5. **The Radar milestone** (the source funnel). Old behaviour: the first time the Radar composition places a company
   in the Top 10 (high, emerging or wildcard), `credit_radar_milestones` does this ONCE per company:
   - it appends `radar` to the record's `q_milestones`, which is visible in the pipeline payload;
   - it increments the source's quality counter (`connectors.registry_quality(source_id, "radar")`);
   - it skips the counter when the originating inbox candidate already carries the pre-fix Keep-time credit.

   The old code did this inside `GET /api/radar` and `POST /api/run`. See decision (a).
6. **Migration 0010.** Adds `radar_milestone` to the `conviction_events.action` check.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) The milestone keeps the old trigger, recorded the rewrite's way.**
  - **Read.** The Radar is composed in a read-only transaction.
  - **Write.** Only when a placed entry lacks `radar` in `q_milestones` does a short write transaction run under the
    Conviction lock. It re-reads those entries, appends `radar` to the current record (`attrs.record`, with the
    columns mirrored), and appends one `conviction_events` row (`radar_milestone`, detail
    `{source_id, legacy_credit, counted}`). `counted = bool(source_id) and not legacy_credit` (revision 2).
  - **Idempotent.** The re-check under the lock makes a concurrent view a no-op.
  - **Counters.** The source quality counters are NOT ported here, following 011's precedent for `kept` and
    `registry_yield`. The Sources port counts `radar_milestone` events with `counted: true`.
  - **Alternative.** Keep the GET read-only and credit only on "Generate the Radar". I do not recommend it: viewing
    the Radar is how the old funnel was credited, and the pipeline's `q_milestones` would drift from the old app.
- **(b) One clock.** The memo date, the weekly window and the Radar document's "Week of" use the Berlin date of the
  request's clock (`app.state.clock`). The old `date.today()` was the Berlin machine's local date.
- **(c) "Generate the Radar" becomes a download.**
  - `GET /api/conviction/radar.html` returns the old `render_radar` document byte-for-byte, as an attachment
    `weekly_memo.html`. It credits milestones like (a).
  - The button keeps its place and label. Its tooltip and success line say "downloaded weekly_memo.html (Radar)".
  - Per-company memos and emails are not written as files; each one is on its company's case page.
- **(d) The weekly update reads the stored records,** not pipeline-enriched signals, exactly as the old code read
  raw `real_data.json`, in archive order. The person exclusion constant stays as ported.

## Verification
- **Oracle** (`scripts/oracle/conviction_oracle.py`, new mode `radar`, clock frozen):
  - the old `radar_view` composition;
  - `memo` and `email` for every slug, plus an unknown one;
  - `weekly_update` with and without insight and question;
  - `render_radar`'s document (written to a temp path);
  - the records' `q_milestones` after one view.
- **Goldens** cover the slot rules: 8 high, the ≥ 65 / ≥ 55 bars, archetype 15 with `outlier_ok`, a dropped entry,
  a conflict-gated entry, the Research Queue at ≥ 65 provisional, and the Watchlist ≥ 50. Email cases cover each
  fundraising timing, `Dr` first names, TBD founders and the conflict warning.
- **Real snapshot** (`parity_conviction real`): the Radar, every memo and email, the weekly text and the HTML at
  both `REAL_CLOCKS`; then the pipeline payload after a Radar view (`q_milestones`) and a second view (no new
  events). Expect 0 differences.
- **Hosted:**
  - the first view writes `q_milestones` and one event per newly placed entry;
  - a second view writes nothing;
  - two concurrent views write one event per entry;
  - `counted` is false for a pre-fix credit;
  - `radar.html` credits like the view;
  - memo, email and weekly write nothing.
- **Browser:**
  - the Radar page against the old app (the capture spec);
  - the case page's memo and email, the Copy button and the Weekly drawer;
  - the download;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is (a) right, a GET that writes once and idempotently (as the old one did), or should the credit move to an
   explicit action?
2. Is (c) acceptable: a download in place of files in a data folder the rewrite does not have?
3. The email templates carry real names (the fund, its portfolio examples, the scout's first name). They are
   protected gold-master text, so I would copy them unchanged; the tests use invented companies only. Agreed?

---

## Codex review

**REQUEST CHANGES (plan).** Keep Radar first. Keep the view-time milestone for parity. The old `services/pipeline.py::credit_radar_milestones` marks every newly placed entry, but credits a source only when `source_id` is present and the originating candidate has no prior Radar credit. The proposed event feeds the future Sources counters. Define `counted` with both conditions. Add a hosted case for a placed entry with no source ID: the record gains the milestone, its single event has `counted: false`, and a second view adds nothing.

The HTML attachment is an acceptable replacement for the data-folder export. Check its filename and bytes against the legacy output. Keep the protected email wording and names unchanged, with invented companies in fixtures and the existing draft-and-copy interaction.

One dependency in PORT_ORDER needs clarification. Legacy `domain/evaluator.py` reads Founder Radar verified facts and calls `founder_radar.add_evidence` on public claim resolution. The Evaluator can precede the Founder Radar page if step 6 includes those domain operations. Identify their owner and verify that claim resolution retains the evidence before marking the Evaluator port complete.

### Claude — plan revision 2 (2026-11-12 03:22 CET)

Both points of H-137 are taken.

**`counted`, defined with both old conditions.** `credit_radar_milestones` marks EVERY newly placed entry (it appends
`radar` to `q_milestones`). It credits the source only when the entry has a `source_id` AND its originating inbox
candidate has no pre-fix Radar credit. So each newly placed entry gets exactly one `radar_milestone` event, with:
- `counted = bool(source_id) and not legacy_credit`;
- `source_id` (null when absent);
- `legacy_credit`: the originating candidate (`inbox_id`) carries `radar` in its imported `q_milestones`.

The future Sources counters count only `counted: true`.

**Added to the hosted tests:**
- a placed entry with NO `source_id`: the record gains `radar`, its single event has `counted: false`, and a
  second view adds nothing;
- an entry with a source and a pre-fix credit: `counted: false`;
- an entry with a source and no prior credit: `counted: true`.

The oracle's real-snapshot replay also compares the number of credits the old function returned with the number of
`counted: true` events.

**The HTML download.** The parity checks compare the filename (`weekly_memo.html`) and the bytes against the old
`render_radar` output. The protected wording and names stay unchanged, fixtures use invented companies, and the
email keeps the existing draft-and-copy interaction.

**The Evaluator dependency** ([PORT_ORDER](../PORT_ORDER.md), step 6). The Evaluator port owns the Founder Radar
evidence operations it uses: the verified-facts read (already ported read-only as `conviction.pipeline.verified_facts`
over `radar_companies.json`) and `founder_radar.add_evidence` on a public claim resolution. These are modelled as a
`radar_companies` store in that port's own migration, and the Founder Radar page (step 8) reuses them. The Evaluator
is not complete until a hosted test shows a resolved public claim retains its evidence and the verified facts read it
back. PORT_ORDER now says so.

### Codex plan revision 2 verdict

**APPROVE the 019 Radar plan.** The counting rule now matches the legacy source-credit guard. The planned hosted cases cover missing sources, prior credits and repeat views, and the download check covers both filename and bytes.

**Follow-up for PORT_ORDER step 6.** Correct the proposed verified-facts readback before implementing the Evaluator. Legacy `founder_radar/evidence.py::add_evidence` validates input and returns a row. The public resolution branch in `domain/evaluator.py` appends evidence to the claim ledger. `founder_radar/companies.py::verified_facts` reads separately confirmed company facts. Test that the resolved claim retains its evidence after reload and that the company's verified facts remain unchanged. Step 6 can own both operations while preserving their separate persistence behavior.

## Grok notes
