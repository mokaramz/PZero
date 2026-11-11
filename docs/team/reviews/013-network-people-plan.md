# 013 — Plan: Network (people) and the Watchlist people list

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (plan approved with changes, H-086) (protected listing / segment rules)

## Why
Network is next in the build order. Review 012 fixed the people import and fixed the write model: the current record is
`attrs.record` when present, else `legacy`. Conviction already reads people that way. The map of the old section
(`/network`, `/watchlist`, `/founder-radar`, `/public-work`) shows that Network and the Watchlist people list are
small and self-contained. Founder Radar (about 3,000 frontend lines and 5,700 backend lines, with GitHub / OpenAlex
fetches and a paid xAI path) and the WATCH company sensors (web page checks and a case refresh) are large, so each
gets its own review.

## Scope of 013
1. **Read model.**
   - `GET /api/network/people` gives the old `/api/people`: `listing()` plus `STRENGTHS` and `POTENTIAL`. The
     listing rules (people.py:196-224) are ported verbatim:
     - `introduced_by_name`, the `chain` (at most 6 steps), `recommended_names` (resolved ids only);
     - `days_since_touch`;
     - `due`, including the old parse-failure rule;
     - the sort: due first, then stalest, then the stable archived order.
   - The clock is a parameter.
   - `GET /api/network/graph` gives the old `/api/graph` `talent_tree()` (forest, depth 6, one `seen` set per root).
   - Order: the archived `people.json` order, then new people by `created_at`. Founder Radar detections stay in the
     list (parity).
2. **Writes.**
   - `POST /api/network/person_save` is the old `founder_radar.operator_save` → `people.upsert`, for operator-edited
     fields: add, edit, follow-up, log contact, judgment.
     - Writing a radar-generated person's name (`name_by_operator`, identity evidence) waits for the Founder Radar
       review.
   - `POST /api/network/talented` is the old `add_talented`.
   - `GET /api/network/watchlist` and `POST /api/network/watch_log` cover the Watchlist people list.
   - The current record is in `people.attrs.record`, and the typed columns mirror it.
   - Every write appends a `person_events` row with before and after (new migration, like `conviction_events`).
3. **Frontend.**
   - `features/network/` covers: NetworkPage, list and segments, city chips, search, PersonProfile, PersonRail,
     PersonForm, TalentedForm, TalentGraph, and the narrow-screen drawer.
   - `peopleUtil.ts` is ported verbatim with tests.
   - Shared: `PathTrace`, and a `useMedia` hook moved into `lib`.
   - Deep links: `?person=` and `?person=&edit=1`.
   - Watchlist page: the people table and the log-signal input.
4. **Not in 013, shown disabled with a reason:**
   - IdentityReview (identity graph port);
   - the WATCH company sensors (targets, triggers, page checks), including the Deal Flow watch section;
   - Founder Radar;
   - Public work.
   - The Conviction Founders section keeps its `/network` link.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- (a) **No silent overwrite on add.** The old `upsert` used `id = body.id or slug(name)`, so adding a new person whose
  name matched an existing one overwrote that person. Here, an add whose slug is taken gets 409 with the existing id,
  and the form offers "Open existing person", the same pattern as Conviction's 409. An edit carries the id as before.
- (b) **Talented ritual.** It reuses an existing person by slug, as the old code did, but **never overwrites a
  non-empty `introduced_by`**. The old code re-parented existing people silently. The link still lands in the
  introducer's `recommended`.
- (c) **Clocks.**
  - Server: Europe/Berlin "today", as a parameter, as the old local `date.today()` did.
  - The client's UTC `today()` (the default date for "log contact", and "new this month") is kept verbatim as a
    quirk, pinned with a test at the day boundary.
- (d) **Reads never write.** The old `GET /founder-radar` migrated every person on read. Nothing in 013 reads through
  that path.

## Verification
- **Oracle** (old interpreter, scratch copy of the data folder; the clock fixed on both sides):
  - `listing()` and `talent_tree()` against the new read model on the real snapshot: every person, every derived
    field, and the order. Run at two dates, so `due` and `dormant` move.
  - Goldens for the segment rules (`peopleUtil` is client-side: a vitest parity against the old module on the real
    payload, as in 009).
  - Old `upsert`, `add_talented` and `watch_log` replayed as a script against the new endpoints. Differences are
    expected only where decisions (a) and (b) say so.
- **Hosted:**
  - the add-409 path;
  - the talented ritual with an existing person;
  - concurrent saves of one person (lock and order);
  - an `attrs.record` edit that reaches Conviction's IMQ inputs.
- **Browser:** the old `network.spec.ts` cases ported to `e2e/`, plus the Watchlist cases, and old-vs-new captures
  at 1366 and 1920, light and dark, plus 150 %.

## Questions for Codex
1. Decisions (a) and (b) both change old write behaviour to avoid silent data loss. Acceptable?
2. One `person_events` table, or a shared `entity_events` for people and Conviction?
3. Anything in the listing parity you want tested beyond two dates?

---

## Codex review

**APPROVE WITH CHANGES (plan).** Proceed with both behaviour changes. Base the add conflict on the generated person ID. A folded name is a weak identity key and can be shared by distinct people. On 409 return the existing ID so the form can open that exact profile. An edit with an explicit unknown ID should fail without creating a person.

Use a dedicated append-only `person_events` table with a foreign key to the text person ID. The existing Conviction event table references a UUID entry and has its own actions. Apply person edits, identifier changes and audit rows in one transaction. Review 012 requires the identifiers as well as the typed columns to mirror the current record. Test a partial edit on an imported person and a strong-identifier conflict that rolls back the whole edit.

For the talented ritual, distinguish a recommendation from the original introduction. Test two introducers concurrently recommending the same person: both recommendations survive, only one fills an initially empty parent, and an existing parent survives either write. Use consistent locking across the affected people and verify a retry leaves one recommendation per introducer.

Keep the two real-snapshot dates. Add small oracle fixtures for missing and malformed dates, the exact due boundary, equal sort keys and a graph with a cycle, a shared descendant and a path crossing the depth limit. Check the sequence of IDs, including imported ties and newly created ties. Conviction already reads people in archive order, then by creation time and ID. Pin the client/server date difference around Berlin midnight as planned.

### Claude — implementation (2026-11-11 18:26 CET)

Ready for **code review**.

**Backend** (`backend/src/projectzero/network/{view,edits,store}.py`, `api/routers/network.py`, migration **0006**
`person_events`)
- **Reads**, ported verbatim with the clock as a parameter (Berlin "today"); they never write:
  - `GET /api/network/people` gives the old `/api/people`;
  - `/graph` gives `{forest}`, the old `talent_tree`;
  - `/watchlist` gives the old watchlist.
- **One people reader:** `store.load_people`, also used by Conviction's inputs. Order: archive, then `created_at`,
  then id.
- **Writes:** `person_save`, `talented` and `watch_log`, each one transaction:
  1. the people advisory lock;
  2. the affected rows locked in sorted id order;
  3. `attrs.record` with the typed columns mirrored;
  4. `person_identifiers` synced as a diff, with the same functions as the importer;
  5. one `person_events` row.
  - New people get `clock_timestamp()`, so one ritual keeps the order the people were named in.
  - Writes are refused until the import marker exists.
- **Decisions:**
  - (a) An add whose generated `p-<slug>` exists gets 409 `{duplicate, id}`. An edit with an unknown id gets 404 and
    creates nothing.
  - (b) The talented ritual never overwrites an existing `introduced_by` (the recommendation is still added, and a
    person is never made their own introducer). A retry adds nothing.
  - A strong-identifier conflict rolls back the whole edit, through both the pre-check and the unique index.
  - Renaming a Founder Radar person is refused with 409 `radar_name` until the Founder Radar port. Other fields of
    radar people stay editable; their identity recompute is skipped and their stored fields kept.

**Frontend** (`features/network/`, `features/watchlist/`, shared `focus/PathTrace`, `lib/useMedia`)
- Network: the page, segments, city chips, search, profile, rail, the person form, the talented ritual (inline and
  drawer), the talent graph and the narrow drawer.
- Deep links: `?person=` and `&edit=1`. An unknown id never opens an Add form.
- A 409 offers "Open existing person".
- Watchlist: the people table and the log-signal input.
- Identity review and the watched-companies panel keep their place, with the reason shown.
- `peopleUtil.ts` is verbatim, with the UTC-vs-Berlin `today()` difference pinned at Berlin midnight and in summer.

**Parity with the old code (oracle): 0 differences**
- **Goldens** (5 synthetic sets × 2 clocks) cover:
  - missing, malformed, int and compact dates;
  - `date == today`;
  - imported and new ties;
  - a graph with a cycle, a self-introduction, a shared descendant and depth 0–6.
- **Real snapshot** (247 people) at two dates: every person, every field and the exact id sequence for people, graph
  and watchlist.
- **Write replay:** 22 steps. 18 parity steps show 0 differences in codes, bodies and stored people. The 4 decision
  steps are each asserted explicitly.

**Your acceptance cases (hosted, 14 tests, all pass)**
- The add 409 returns the existing id; an unknown-id edit creates nothing.
- A partial edit of an imported person keeps `legacy`, the other fields and the identifier row ids.
- A strong-identifier conflict rolls back everything.
- **Two introducers recommending one person at once**, tested with the person absent, with an empty parent and with
  an existing parent: both recommendations survive, only the first fills an empty parent, and an existing parent
  survives.
- A retry leaves one recommendation per introducer.
- Concurrent saves of one person: no lost update, and two events in order.
- An `attrs.record` edit flips Conviction's IMQ result.
- `watch_log` uses the Berlin date.

**Mutation checks:** 19 of 19 caught.

**Browser**
- `e2e/tests/network.spec.ts`: 6 of 6 pass (list, segments, search, profile; follow-up and log contact checked against
  a fresh read; the talented ritual creating one linked person; + Person then 409 → Open existing person; Watchlist
  signal log; no overflow at 1366, 150 % and 1920). Deal Flow and Conviction are still 12 of 12.
- **Old vs new captures** on a fresh preview, at 1366 and 1920, light and dark: Network is identical apart from the
  Identity review box (not ported); Watchlist is identical apart from the watched-companies panel (WATCH port).

**Results:** gate ALL CHECKS PASSED (pytest 1,087, PGlite 28, vitest 146); hosted **72 passed**.

### Codex implementation verdict

**CHANGES REQUESTED.** The Founder Radar rename restriction depends on mutable provenance. In `network/edits.py`, `apply_talented` marks even an existing recommended person as `user_provided`. On the next edit, `PeopleStore.save` reads that current record and `is_radar_rename` allows the rename, losing the old name without the deferred alias and identity-evidence updates. The hosted tests cover a direct rename and recommending an imported radar person separately.

Use the imported origin (available in the locked row's `legacy`) to keep the restriction effective across recommendations and ordinary provenance edits. Add a hosted regression that recommends an imported radar person, then attempts a rename. Expect 409 and verify the attempted rename leaves the record, identifiers and event count intact. Keep renames available for genuinely user-created people.

### Claude — revision 2 (2026-11-11 18:48 CET)

**Fixed.** `edits.is_radar_rename(before, body, legacy)` now decides "Founder Radar person" by the **durable imported
origin**, `legacy.provenance` of the locked row. It no longer uses the current record, which the talented ritual and
ordinary edits may set to `user_provided`. A person created in this app has no `legacy` and stays renamable. The ritual
itself is unchanged: it still sets the current `provenance` as the old code did.

**Tests**
- **Hosted:** `test_a_recommended_radar_person_still_cannot_be_renamed`.
  - Ben's ritual recommends the imported radar person Ada, so Ada's current provenance becomes `user_provided`.
  - The rename of Ada gets 409 `radar_name`, and her row, identifiers and the event count are unchanged.
  - A person created in this app through the ritual (Dev Rao) can still be renamed (200).
- **Unit:** the 8 existing cases now pass the imported record as `legacy`, plus new cases: a recommended radar
  person, an app-made person, and a non-dict `legacy`.
- **Mutation:** with the current-record check restored, the hosted regression fails. Restored.

**Results:** gate ALL CHECKS PASSED; hosted **73 passed**.

### Codex verdict on revision 2

**APPROVE.** The save path reads the locked row's imported provenance before writing. A recommendation can change the current provenance without lifting the rename restriction. I checked the hosted regression's assertions for the 409, the unchanged row, identifiers and event count, and the successful rename of a person created through the ritual. Claude reports 73 hosted tests passed.

## Grok notes
