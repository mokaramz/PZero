# PROJECT ZERO FINAL — delivery document
*12.09.2026 · everything below is in the shipped zip · development frozen at this scope*

## 1. Feature overview

**Judgment core (v4.1, unchanged since approval)**
- Taste Map v2.2 as code: 15 archetypes verbatim, ~40-company portfolio conflict list, rubric (Founder 25 / Venture-scale 20 / Why-now 15 / Taste 15 / Earliness 10 / Insight 10 / Resemblance 5), penalties incl. −25 potential conflict with the mandatory "do not forward until Omar/Project A confirms" warning.
- Provisional vs Verified scoring; verified-only Radar (8+1+1, empty slots allowed) + Research Queue + conflict-gated section; Discover inbox with pre-company watchers and announcement feeds; memos, timing-driven outreach emails.

**People & network**
- People tab: full person records, relationship strength, follow-ups (overdue = red), provenance rule (user-provided only, SUGGESTED-labelled auto-actions).
- "3 most talented people" ritual: one click creates three linked records, chains preserved.
- Talent Graph view: recommendation/introduction chains as a tree, with founder-potential badges and person→startup links.
- Watchlist: manual-first signal sweep for founders/researchers/investors — public links per person (Google/News/GitHub/Scholar + stored profiles), "log a signal", last-checked stamps. No scraping, by design.

**Events**
- Structured-first discovery (Devpost API, Luma embedded data, any ICS you add) + page watchers + manual add; confidence labels VERIFIED / LIKELY / NEEDS REVIEW; first scan surfaces current/future events; past events dropped; duplicates merged across sources **with full provenance preserved** ("Seen on: …").
- Evidence-based Event Score /100 (7 dimensions, every point tied to a visible statement; elite-institution boost only for genuinely founder/technical events; admin events capped).
- Post-event debrief loop: people met → Person records; startup leads → Discover as pre-company candidates; outcomes logged; feeds the weekly update.
- **Where Should I Go?**: upcoming events ranked by Event Score × travel factor (Karlsruhe gazetteer) + open-contact bonus, with the reasoning printed per row.
- **Sourcing Weekend**: give it a window → per-city missions chaining the best events + Talent-Graph coffees, with expected outcomes.

**Map / control room**
- MapLibre + OpenFreeMap Positron. Layers: startups (stage colors, score-scaled, Omar-ring), events (squares), **people** (purple, watchlist-ring), **universities/labs** and **hubs/accelerators** (24 verified institutions from Karlsruhe to London). Clustering, time/distance/stage/type/score filters, right intelligence panel, jump-to-profile/ecosystem.

**Ecosystem pages** — one page per focus city (Karlsruhe, Munich, Zürich, Lausanne, Stuttgart, Frankfurt, Paris, Amsterdam incl. Delft/Eindhoven, Berlin, Darmstadt, London): pipeline startups, upcoming events, your people, institutions, travel time, and an honest strategic note per city.

**Home control center** (landing view) — priority startup, best upcoming event (from Where-Should-I-Go), overdue follow-ups, new signals, Omar activity (sent/awaiting feedback), watchlist status, weekly progress numbers.

**Omar & output** — Send-to-Omar copyable email cards (human-sounding, evidence sentences only from your own words, conflict warning auto-added), feedback capture, Weekly Sourcing Update with no-filler rule.

**Public work tracker** — ideas → drafts → published, per platform, inbound capture; every item shows the positioning warning (never "Project A Scout" publicly).

## 2. Automated vs manual sources

| Automated (structured) | Automated (watcher/diff) | Manual by design |
|---|---|---|
| Devpost hackathon API · Luma city pages (embedded JSON): Munich, Berlin, Zürich, Paris, Amsterdam, Frankfurt · any ICS calendars added to `EVENT_ICS` · 6 startup announcement RSS feeds (Tech.eu, EU-Startups, ArcticStartup, Startbase, Munich Startup, startupticker) | 11 pre-company startup pages (DIANA, Palladion, TUM VL, UnternehmerTUM, EUDIS, EIC, Venture Kick, ETH, EXIST, Fraunhofer, HIGHEST) · 11 event pages (Pioniergarage, KIT, UnternehmerTUM, ETH EC, EPFL, START Global, MLH, Google/AWS/NVIDIA, Bits & Pretzels) | LinkedIn (people, events, stealth watchlist) · Meetup/Eventbrite (paid APIs) · corporate & consulting event calendars (SAP…BMW, McKinsey…Accenture) · Handelsregister · transfer-office coffees · Boardy (log intros with Source=Boardy) · Omar |

## 3. Known limitations (honest)
1. **Luma/Devpost parsers depend on their current page/API formats.** Tested for correct parsing of the expected structure and for graceful failure; if a site changes, you get a clean red "open manually" line — report it and the parser gets adapted. This sandbox has no live internet to those sites, so live parsing wasn't verified end-to-end.
2. **Geocoding uses a ~25-city gazetteer**, not a global geocoder. Startups/events in unlisted towns show under "no coordinates" until you use a listed city in the location field (or we add Nominatim later).
3. **Event watchers read text, not meaning** — hence the NEEDS REVIEW label; confirm before planning a trip around a watcher lead.
4. **Where-Should-I-Go / Sourcing Weekend are only as good as your event data** — empty calendar in, empty ranking out.
5. **No automated LinkedIn/investor-connection monitoring** — deliberate (ToS + reliability); the Watchlist implements the same idea manually.
6. **Weekly-progress "found" counts** rely on discovery dates; manually added companies without dates won't count.
7. Map tiles + MapLibre come from CDNs — the map needs internet; all data stays local.
8. Single-user, local, no auth — do not expose port 8177 beyond localhost.

## 4. Test results (final run, all pass)
- Where-Should-I-Go: ETH hackathon in Zürich ranked #1 (88) with travel factor + "1 open contact: Sofia Keller" evidence.
- Sourcing Weekend: Zürich mission value 102 (hackathon + coffee) beat Frankfurt 54.
- Home: priority startup, best event, due follow-ups, watchlist all populated correctly.
- Ecosystem page Zürich: startups 1, events 1, people 1, orgs 2. Talent-Graph forest renders.
- Map payload: 8 startups, events, 1 person, 24 institutions.
- Public work: item saved/listed. Watchlist: signal logged + last-checked stamped.
- Event dedup/merge: second source merged into one event, provenance kept ("manual" + "Luma").
- First-run event filter: historical/weak keyword lines no longer become leads (strong-word or dated-current requirement).
- **Regression (unchanged behavior):** startup scoring ✓ · 15 archetypes ✓ · a68 Provisional 64 / Verified 39 ✓ · penalties ✓ · exactly 3 conflict-gated (Aereus, RegCheck, 5U AI) ✓ · Radar: empty Top 10, 4+ in Research Queue ✓ · Discover ✓ · 9 pipeline entries ✓ · memo sections ✓ · Omar card ✓ · weekly update ✓.

## 5. Optional integrations / API keys (all off by default; nothing requires them)
- **Luma ICS calendars** — best upgrade, no key: subscribe to a calendar → paste the `.ics` URL into `EVENT_ICS` in connectors.py.
- **Evertrace** — optional future upstream feed *if* Omar grants access; nothing depends on it.
- **UK Companies House API** — free key, would add UK incorporations to Discover (not wired; ask and it's a small addition).
- **MapTiler** (free key) — only if OpenFreeMap ever misbehaves; CARTO raster is the keyless fallback.
- **GitHub API** — free token would allow polite automated activity checks for watchlist people (LATER item, currently manual links).
- **Boardy** — personal use only, no API; log introductions with Source = Boardy.
