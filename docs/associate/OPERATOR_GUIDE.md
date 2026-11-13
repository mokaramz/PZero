# Project Zero — operator guide (v1)

For Mohamed. Plain words: what to open, when, and what each screen means. Technical details are in
[V1_SYSTEM.md](V1_SYSTEM.md).

## The one idea

Project Zero finds companies early and does the reading. **You** make every decision that matters: who to contact,
what to verify, what to score, what goes to Omar. The machine proposes; it never decides, never contacts anyone and
never sends anything.

## Starting it

Double-click `START_PROJECT_ZERO.bat`. If checks are overdue, a blue banner says "Catching up on N overdue checks…"
(WATCH checks, the weekly scan, events). It runs in the background and stays within the AI budget caps.

## Daily (10–15 min)

1. **Today**: at most 7 things that deserve you, ranked: founder calls to prepare, verification proposals,
   conflicts to ask Omar about, WATCH companies whose reality changed, KEEP/RESEARCH proposals to review.
2. **Deal Flow**: new candidates already carry a *Machine triage* proposal (KEEP / RESEARCH / WATCH / REJECT).
   Accept or override it. Your click is the decision, and it is what the system learns from.
3. Choose **WATCH** for companies that are not interesting *yet*. They come back on their own when something
   changes: funding news, a pilot or customer on their site, a grant.

## Monday (≈ 1 hour)

- **System health**: is everything green? Failing sources show *why* and *what to do*.
- **Deal Flow → Find New Candidates** if the weekly scan has not already run.
- **Watchlist**: attach official pages (news, careers) to WATCH companies so page changes are noticed.

## Monday — Scout 00 cycle (≈ 20 min)

1. Nothing to import or copy by hand: Scout 00 uploads its finished packet to the Google Drive relay folder, Project
   Zero fetches it into `project-zero-data\scout00-inbox\` and ingests it (at start and every 15 minutes; **Check
   inbox now** on Scout Intake). One-time setup: [SCOUT00_TRANSPORT.md](SCOUT00_TRANSPORT.md#one-time-setup-mohamed). Today shows one card,
   *Scout 00 · Cycle NNN — N signals ready*. Entities Project Zero already knows are not duplicated: an earlier
   Scout Intake item gets the new cycle's evidence attached, and a Deal Flow / Conviction match is listed as "already
   known" (that record is not touched). The manual **Scout Intake → Import** still works as a fallback.
2. Ingestion stages new entities as NEW INTAKE only. Nothing is created in Deal Flow, Conviction, Network or Events,
   nothing is approved, and Scout 00's accounting state and methodology proposals are only shown, never applied.
   The same packet twice creates nothing new (ALREADY INGESTED).
3. For each item, choose one of:
   - **Approve → Create**: one record, carrying the cycle, lanes and evidence URLs;
   - **Approve → Update existing**: when a match was found;
   - **Monitor**: no record is created;
   - **Archive** or **Reject**: kept with the reason.
4. Scout events are added to Events only with **Add**. Registration is always yours.
5. Later, **Validation → Scout 00 feedback** reports back what happened to each discovery. That covers your decision,
   Project Zero's progress, real outcomes, lead time, and whether the evidence source is already monitored.

## Midweek — deal review

Open a company in **Conviction** → **Verification**:

- **Founders**: who they are, how we know (official register, your entry, machine-read), and *what still blocks
  founder verification*. Switzerland: one click looks the company up in Zefix. Germany / Denmark: paste the register
  extract you opened yourself. A director in the register is **not** automatically a founder.
- **Verification proposals**: founders / funding can be proposed when the rules are met. One click from you applies
  one flag.
- **Traction**: the top three unknowns and the evidence. READY FOR MOHAMED REVIEW means independent evidence exists.
  Only you tick traction.
- **Red Team** and **Independent reviewer** (Deal Flow detail): a second opinion appears only when it matters
  (disagreement, near the Radar bar, unclear conflict, IMQ). It costs about $0.002 per run, runs only when you click,
  and at most 3 times a week.

## Founder call

1. **Founder Calls** → open the call → **Prep card**: what we know, what is founder-reported, contradictions, and
   3–7 questions that could change your view, written for this company.
2. After the call: record the founder's claims → **After the call**. Each claim stays FOUNDER-REPORTED — UNVERIFIED
   until a public source confirms it. You see which claims need public verification and the plan. Paid research
   happens only if you click "Approve paid research".

## Map — where to go (before planning a week)

The **Map** answers *where is opportunity forming, where should I go, who is there, and where are we blind?* It
shows Project Zero activity and visibility, never investment scores.

- **Opportunity**: areas coloured by early signals and independent signal families. One long list from one source
  never makes a city "hot". A purple area is **under-covered**: few signals *and* weak sources. That means "we do not
  know", not "nothing there".
- **Where to go**: the few areas worth a trip, each with the reasons and travel (approximate city table or distance
  only; travel time is never invented).
- Click a city to see **Why here**: companies (machine proposals are labelled), people you have recorded, upcoming
  events, coverage per signal family and one next best action.
- **Build a sourcing day**: a proposed plan for a date. It never messages anyone, registers you or books travel.
- **Coverage gaps**: where Project Zero is blind. **Explore** keeps the classic layers and filters.

## News & Learning (5 minutes, most days)

**News & Learning** shows the few important European startup stories. Each one has what happened, why it matters,
the company in one line, and a VC lesson. **Teach me** explains the jargon.

Every story answers one question: *did Project Zero know this company before the news?* The possible answers are
**Early catch**, **Known but late**, **Missed**, **Historical case**, or **Not seen yet**.

- For a company you track, **Confirm outcome** records the round in Validation. Only your click does that.
- For an important company Project Zero never saw, add one early signal with its source, or click
  **Audit this miss**.
- **Weekly review** gives the biggest stories, any early catches or misses, one pattern, one sourcing lesson and one
  VC lesson.

After **Refresh news**, the line next to the button tells you what happened:

- **Refresh complete**, with the number of new stories;
- **Refresh complete — no new stories**, which is a success: the feeds simply had nothing you hadn't seen;
- **partly done** or **failed**, with which sources failed, in plain words.

The **Background activity** line at the top of every page shows what Project Zero is doing and what just finished.

News is context and a benchmark, not a way to find companies early. It never changes scores or sources.

**News sources** (a tab on the same page) shows which publications are best *for what*: Europe-wide coverage, a
country, Munich, early signals, fact confirmation, unique discovery and technical reliability. It never ranks a
source without enough data. Instead it says COLLECTING DATA and what is missing.

- If a publication you don't monitor keeps breaking important stories, it is proposed under System health → New
  sources.
- A source that fails, fills with noise, or drifts away from startups is shown as **declining**.

## New sources (System health, a minute a week)

Project Zero looks for new places where strong companies appear early: university spin-off pages, programmes, grant
lists. It finds them in evidence it already holds (news backcasts, missed companies, Scout 00 links). It tests each one
automatically: safe, public, not spam, not a startup database, names real startups, early rather than late news, and
not a copy of what Project Zero already sees.

- Sources that pass run on **probation**. They are scanned like any other source, and their candidates say "From a
  PROBATION source".
- After at least 3 weeks, the panel shows whether the source has earned trust: enough scans, reliable fetching, unique
  companies, little noise.
- Only then is **Promote to trusted** enabled. You can also **Keep in probation** or **Reject**.
- Broken sources are paused automatically. Nothing is ever deleted.

## Validation review (monthly, 20 min)

**Validation** answers: "Is Project Zero making me better at finding exceptional companies early?"

- **What can we measure yet?** Honest status per metric: KNOWN / COLLECTING / NOT YET MEASURABLE. Early on, most
  metrics are collecting. That is normal.
- **Record outcome** when a company you saw raises a round, wins a customer, or shuts down. Use the date it
  *happened*.
- **Record a miss** when a strong company slipped through. Note the earliest public signal and who should have found
  it.
- **Scout 00 feedback**: prepare the packet → *Copy & log handover* → paste it into Chief Scout 00 on grok.com.
- **External benchmarks**: if you download a Dealroom / Crunchbase export, import it to see "PZ saw X N days before
  Dealroom".

## Backups (monthly, 2 min)

**System health → Back up now**, then **Test latest backup**. A backup counts only after the restore test passes.
Zips are saved in `Desktop\project-zero-backups`. API keys are never included. Recommended: copy the zips to an
encrypted USB drive or an encrypted cloud folder now and then. Nothing is uploaded automatically.

## What always stays yours

Contacting founders · registering for events · sending anything to Omar · clearing a portfolio conflict · authoring
investment scores · ticking traction · merging identities · changing the methodology.
