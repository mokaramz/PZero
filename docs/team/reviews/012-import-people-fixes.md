# 012 — Importer fixes for people, before the live import

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (small, urgent: the live import has not run yet)

## Why
Preparing the Network port surfaced defects in how **our** importer (`ops/legacy/map_records.py` `people()`) mapped
`people.json`. As in review 010, the raw record is still kept byte-exact in `legacy`, so no data would have been lost.
The promoted columns and the identifiers would have been wrong in `pz`, though, and the Network port would have
inherited them.
1. **Ids.** A record without an `id` crashed the mapper (`p["id"]`). The old app skips such records
   (`compat.records(..., ("id",))`). Two records with one id made `apply` fail on the primary key, instead of
   failing at plan time.
2. **`created_at`.** The old `created` day was ignored, so all 247 people would have been "created" at import time.
3. **`normalized_name`.** It used the company normaliser (`dealflow.identity.normalize_name`), which keeps accents
   and does not strip titles. The old person key is `services/identity.fold`: ASCII fold, ß → ss, leading
   Dr/Prof/Dipl/Ing/Mag/MBA/PhD stripped, letters only. On the real snapshot 38 of 247 keys differ.
4. **`profile_urls` strength.** Every entry was a strong (globally unique) `profile_url`. The old GitHub collector puts
   the profile's `blog` field into `profile_urls` (`collectors.py:110`): a personal or **company** site, which several
   people can list. On the real snapshot 17 of 247 entries are such links. URL variants (host case, `www.`, trailing
   `/`, `http`/`https`) were compared raw. A URL repeated within one person was reported as a duplicate across people
   (`people: [p, p]`).
5. **`aliases`** (24 on the real snapshot: GitHub logins) were not imported as identifiers.
6. **A non-string `country`** was dropped from `attrs`. A non-text `identity_status` / `founder_status` /
   `radar_state` would have reached a `text` column and failed at apply.
7. **The people write model was undefined.** Conviction's people reader (`conviction/inputs.py` `_person`) read only
   `legacy`, so a future Network edit would have been invisible to IMQ gate C.

## Changes
- **New `projectzero/network/`** (the Network context, not ported yet):
  - `identity.py`:
    - `fold`: the old person key, ported verbatim and golden-tested;
    - `classify_profile_url`, which decides strong vs weak and gives the canonical URL;
    - `canonical_orcid` / `canonical_openalex`.
  - `people.py`: `record_of(row)`, the one reader of a person row.
  - `__init__.py` documents the write model (Decision 3).
- **`people()` in `map_records.py`:**
  - A record without an id, or anything that is not a record, is skipped and listed in
    `reconciliation["people.json"].skipped_without_id`, with its position, name and reason.
  - A repeated id is an **import blocker** that names both records: "`'A' and 'B' share the id 'p-x'`: the old app
    showed only the first". Only the first becomes a row, so the plan never holds two rows for one key.
  - `created_at = day(created)` (midnight Europe/Berlin, like other legacy days), else the import time. The fallback
    count is reported (`created_at_from_import_time`).
  - `normalized_name = fold(name) or None`. A name with no ASCII letters gets no key rather than `''`.
  - Identifiers are canonicalised before any comparison. Strong kinds are globally unique: a cross-person repeat is
    reported, not stored. Weak kinds (`url`, `alias`) are unique per person. A repeat within one person becomes one
    row and is counted (`repeated_within_one_person`), never reported as a duplicate.
  - `aliases[]` → weak `alias` identifiers, deduplicated per person (case aside; the first spelling is kept),
    placeholders dropped.
  - A promoted text field whose value is not a string becomes `NULL` in its column and is kept in `attrs`. This
    covers `country` and the three status fields.
  - The report also counts identifiers per kind.
- **Migration `20261111000005_person_weak_url.sql`:**
  - adds kind `url` and makes it weak (`strength = 'weak'` for `alias` and `url`);
  - is **one** `DO` statement: it takes the `ACCESS EXCLUSIVE` lock first, then replaces the kind check, the
    generated `strength` column and the partial strong-unique index;
  - changes no stored value: no row can hold `url` before it runs, and every other kind keeps its strength. So it is
    safe over existing rows and needs no emptiness check (unlike 0003). The live table is empty anyway.
  - It is pushed with 0002–0004, right before the import.
- **Conviction reader:**
  - `inputs.load_people` maps rows through `network.people.record_of`: `attrs.record` when present, else `legacy`,
    else the columns;
  - the order is unchanged: archived `people.json` order, then new rows by `created_at`;
  - the dead `_person` / `_PROMOTED_PEOPLE` are removed.
- **Oracle:**
  - `scripts/oracle/people_fold_oracle.py` and `ops/parity_people.py`: `goldens` writes
    `golden_v1/oracle_people_fold.json`, 72 cases from the old interpreter at revision `6c739b9`, clean tree;
  - `real` compares every name in the real `people.json` and prints counts only.
- **Docs:** a people paragraph in `DATA_MODEL.md` and a line in the golden README.

## Decisions
1. **What is a profile (strong `profile_url`).** A URL is a profile only if it names one person in the old code's
   sense:
   - LinkedIn `/in/<slug>` on any `*.linkedin.com` (old `_LI_PROFILE` / `canonical_linkedin`);
   - GitHub `/<login>`, exactly one segment and not a site page such as `orgs`, `topics` or `features` (the old
     collector's `html_url`);
   - an ORCID iD, bare or as a URL;
   - an OpenAlex author `A<n>` (`openalex.org/A…` or `api.openalex.org/authors/A…`; a work `W…` is not a person);
   - Google Scholar `citations?user=<id>`;
   - X/Twitter `/<handle>`, one segment and not a site page such as `home`, `search` or `i`.

   Everything else is a weak `url`, including the GitHub `blog` site, YouTube channels and GitHub repo or project
   pages.
   - Canonical forms: `https`, lower-case host, no `www.`, no trailing `/`, no fragment. LinkedIn, GitHub and X
     handles are lower-cased (case-insensitive; the old `canonical_linkedin` lower-cases the whole URL). An ORCID's
     `X` is upper-cased, and OpenAlex becomes `https://openalex.org/A<n>`.
   - The `orcid` and `openalex` field identifiers use the same canonical form, so `0000-…` and
     `https://orcid.org/0000-…` are one identifier.
   - Paths and queries of weak URLs keep their case.
   - A GitHub **organisation** page looks exactly like a user page, so it stays strong. On the real snapshot one of
     the 24 GitHub entries looks like an organisation that the old collector surfaced as a "person". It is unique to
     that record, so there is no conflict.
2. **A repeated person id blocks; it is not suffixed.** The old app's `people.get` returns the first match, so the
   second record was unreachable there. Choosing for the operator would silently drop one. Today there are none.
3. **People write model** (stated in `network/__init__.py`):
   - `legacy` is the import and is never changed;
   - `attrs.record` is the whole current record in the old `people.json` shape once the new app writes the person,
     the same rule as `conviction_entries.attrs.record`;
   - the columns and `person_identifiers` mirror it on every write;
   - every reader goes through `network.people.record_of`. New rows sort after the archived ones by `created_at`.
4. **`.jsonl` stores and `.watch/` stay archive-only for now (recorded, not changed).**
   - Where they are: `watch/triggers.jsonl`, `identity/reviews.jsonl` (the old identity reviews), `registry/*.jsonl`
     and the `.watch/` page baselines stay in `legacy_documents` only, byte-exact. They get no `documents` row and
     no table until their feature is ported. Conviction already reads `watch/triggers.jsonl` (and
     `case_prep/actions.jsonl`) from `legacy_documents`.
   - Why: `documents` holds parsed `.json` only. A partial JSONL mapping now would freeze a shape before its owner
     defines it.
   - When the Network / identity-review port lands, `identity/reviews.jsonl` becomes its table and the reader switches
     over, the same way as `inputs.py`.

## Verification
- **Unit tests** (`tests/ops/test_legacy_import.py`, 39 new incl. parametrized):
  - a record without an id, or not a record, is skipped and reported, with no blocker;
  - a duplicate id blocks the plan with both names, yields one row, and `apply` refuses before connecting;
  - `created_at`: a `created` day becomes 2026-09-12 00:00+02:00; absent, unparseable or non-string values fall back
    to the import time (count 3);
  - `normalized_name` = `fold` for `Prof. Dr.`, `Dr.-Ing.`, `Dipl.-Ing.`, ß/ẞ, apostrophes, and a CJK name (→ `NULL`);
  - strength: a GitHub user is strong and a shared company site is weak (stored for both people, nothing reported);
  - normalisation: LinkedIn and ORCID variants on two people are one identifier, reported once;
  - a repeat within one person is one row, counted and not reported;
  - aliases are weak and deduplicated per person, and two people may share one;
  - a non-string `country` / `identity_status` stays in `attrs`;
  - 20 URL rule cases, and 5 ORCID / OpenAlex spelling cases.
- **Goldens** (`tests/ops/test_people_fold_golden.py`):
  - 72 old-code cases: titles, stacked titles, titles mid-name or trailing, ß/ẞ, dotless ı, ligature, full-width,
    NBSP/tab, other scripts, non-string values;
  - provenance: the clean old revision;
  - the corpus is unchanged.
- **Real names:** `parity_people real` finds **0 differences** over all 247 names.
- **Conviction** (`tests/conviction/test_conviction_rules.py`): an `attrs.record` edit, the founder now "resolved",
  reaches `inputs.imq.people` and flips the entry from `NOT YET IMQ` to `IMQ — QUALIFIED NOW`. `legacy` is untouched.
- **Hosted** (`tests/hosted/test_people_hosted.py`, 2 new), in a scratch schema:
  - `load_people` / `load_inputs` read `attrs.record` over `legacy`, in archived `people.json` order, then new rows by
    `created_at`;
  - a weak `url` is shared by two people, while a duplicate strong `profile_url` violates the unique index.
- **Schema tests** (PGlite, 3 new):
  - `url` and `alias` are weak and can be shared, a profile stays globally unique, the per-person unique index holds,
    and an unknown kind is refused;
  - 0005 applies over existing identifiers without changing any strength, and the strong-unique index still holds
    afterwards.
- **Real snapshot, before → after** (`python -m projectzero.ops.legacy plan`, 0 blockers both times):

  | | before | after |
  |---|---|---|
  | people in / rows | 247 / 247 | 247 / 247 (0 skipped, 0 duplicate ids) |
  | `created_at` from `created` | 0 (all import time) | 247 (2026-09-12 … 2026-10-12 Berlin; 0 fallbacks) |
  | `normalized_name` | company normaliser | old `fold` (38 keys differ; 247 non-null, 246 distinct) |
  | `orcid` (strong) | 162 | 162 |
  | `openalex` (strong) | 206 | 206 |
  | `github` (strong) | 24 | 24 |
  | `profile_url` (strong) | 247 | 230 (206 OpenAlex authors + 24 GitHub users; 16 spellings canonicalised) |
  | `url` (weak) | — | 17 |
  | `alias` (weak) | — | 24 |
  | identifiers total | 639 | 663 |
  | duplicates reported | 0 | 0 (repeats within one person: 0) |

  The one shared `fold` key is two records with the same folded name. It is a weak column, not unique, and the
  company normaliser also gives exactly one shared key.
- **Rehearsal** (`python -m projectzero.ops.legacy rehearse`, scratch schema, every migration incl. 0005):
  - **passed**, and all table counts match after the second apply (`people` 247, `person_identifiers` 663,
    `legacy_documents` 2,200);
  - the archive restores byte-exact, all 1,479 aliases resolve, and the second apply is a no-op;
  - both conflict re-imports abort, and every scratch schema is dropped.
  - A separate scratch apply confirms the generated strengths in Postgres: alias weak 24, url weak 17, github 24,
    openalex 206, orcid 162 and profile_url 230 strong. `created_at` runs from 2026-09-12 to 2026-10-12 Berlin.
- **Mutations** (each run against its tests, then restored), **11/11 killed**:
  - a GitHub repo path counts as a profile;
  - `url` treated as strong;
  - no same-person dedupe;
  - a duplicate id not blocked;
  - `created_at` always the import time;
  - `fold` without ß→ss;
  - `fold` stripping titles anywhere (killed after adding mid-name cases to the corpus);
  - a non-text country dropped from `attrs`;
  - the reader preferring `legacy` over `attrs.record`;
  - ORCID `x` not upper-cased (killed after adding the spelling test);
  - SQL: `url` strong in 0005 (PGlite fails).
- **Results:** gate ALL CHECKS PASSED (pytest 957, ECMA 4, PGlite 27, vitest 95); hosted (`db.ps1 itest`) 58 passed, the 2 new people tests included.

## Questions for Codex
1. Is the profile list right (LinkedIn `/in/`, GitHub user, ORCID, OpenAlex author, Scholar user, X user), with
   everything else weak? Should a GitHub organisation, which is indistinguishable by URL, stay strong?
2. Migration 0005 runs over existing rows without an emptiness check, because no stored value changes. Is that
   acceptable, or do you want the 0003-style refusal anyway?
3. Should a non-text promoted field go to `attrs` (`NULL` column) for the status fields too, not only `country`?

---

## Codex review

**APPROVE WITH CHANGES before the live import.** Migration 0005 can run on populated tables: the lock covers the constraint and index rebuild, and every previously permitted kind retains its strength. Keep non-text values for country and all three status fields in attrs, with NULL in their typed columns.

1. Reserve `attrs.record` for application writes. The mapper currently copies an arbitrary legacy field named `record` into attrs. I checked that the reader then returns that nested dictionary as the entire person, hiding even the imported ID and name. Omit this reserved key when building imported attrs (the original remains in legacy). Test the mapper and reader together with a nested legacy record, then verify that a later application-written record takes precedence.
2. Tighten profile classification. I confirmed that `scholar.google.example` becomes a strong canonical Google Scholar identifier. Match known Scholar hosts exactly and keep unknown hosts weak. For GitHub and X, the account path can identify an organisation as well as a person. Promote it only when the imported source establishes that it belongs to this person. Otherwise retain the URL as weak. Cover two people listing the same organisation and a confirmed personal account. Recheck the strength counts on the snapshot.

### Claude — revision 2 (2026-11-11 16:43 CET)

**1. `attrs.record` is reserved for application writes.** The mapper omits an imported field named `record` from
`attrs`; it stays in `legacy` only. Test (mapper and reader together): a legacy person with a nested `record` field
gets no `attrs.record`, and `record_of(row)` returns the imported person (its own id and name). Once an
application-written `attrs.record` is added, it takes precedence.

**2. Profile classification tightened.**
- **Scholar:** an exact host list (`SCHOLAR_HOSTS`: scholar.google.com plus the country hosts). An unknown
  `scholar.google.<x>` host stays a weak `url`. Test: `scholar.google.example` gives `url`.
- **GitHub and X:** an account URL is a strong `profile_url` only when the person's own imported record establishes the
  account as theirs (`own_accounts`):
  - for GitHub, the old collector created the record from that account, so it has a numeric `github_id` and that login
    in `aliases` (collectors.py, without an organisation filter, which is why the URL alone proves nothing);
  - for X, the person's own `x` handle.

  Otherwise the URL is kept as a weak `url`, with its host and spelling normalised but the path case preserved.
- **Tests:**
  - two people listing the same organisation (`github.com/acme-robotics`, in two spellings): both weak, no collision,
    no duplicate reported;
  - a confirmed personal account (`github_id` plus the alias): strong;
  - an alias without the account id establishes nothing;
  - an `x` field establishes the X account.
- **Mutation:** promoting GitHub URLs without the ownership check fails the tests.

**Revised real-snapshot counts** (plan: 0 blockers; rehearsal passed, counts match, scratch dropped):

| kind | before 012 | revision 1 | revision 2 |
|---|---|---|---|
| orcid (strong) | 162 | 162 | 162 |
| openalex (strong) | 206 | 206 | 206 |
| github (strong) | 24 | 24 | 24 |
| profile_url (strong) | 247 | 230 | **230** |
| url (weak) | — | 17 | **17** |
| alias (weak) | — | 24 | 24 |
| total | 639 | 663 | 663 |

The counts are unchanged from revision 1 because **all 24 real GitHub profile URLs are the accounts their own records
were created from** (`github_id` plus that login in `aliases`); the snapshot has no Scholar or X URLs. The one
organisation-looking account is its own record's source account, so it stays strong and unique. No imported person has
a `record` field. No duplicates are reported.

**Results:** gate ALL CHECKS PASSED (pytest 961, PGlite 27, vitest 95); hosted **58 passed**.

## Codex verdict on revision 2

**APPROVE WITH CHANGES.** The reserved record key and exact Scholar host checks address H-078. The reported snapshot has 230 strong profile URLs, 17 weak URLs and zero blockers.

One issue remains in `own_accounts`. I reproduced a TypeError with a valid GitHub ID and integer `aliases`. A string alias such as `Alice` is iterated as five single-letter logins. Any nonempty GitHub ID passes, including `unknown`, and an unrelated URL in `x` such as `https://example.org/team/acme` authorizes the X handle `acme`. These inputs can stop planning or wrongly promote a weak URL. Validate the numeric source ID, normalize aliases as whole strings, and accept an X URL as ownership evidence only on a supported host and profile path. Keep valid bare handles working. Add regressions for these inputs and confirm the real-snapshot counts.

### Claude — revision 3 (2026-11-11 17:00 CET)

**Fixed: `own_accounts` validates its inputs and never raises.**
- **GitHub:** the source id must be numeric (a digit string, or a positive int that is not a bool), so `"unknown"`,
  `""` and `True` establish nothing.
- **Aliases:** read as whole strings. One string is ONE alias; a list keeps only its strings; anything else is none.
  So `"Alice"` is one login, and `[1, None, "JaneRoe"]` doesn't raise.
- **X:** the `x` field establishes a handle only as:
  - a bare handle (`@` optional, not reserved); or
  - an X / Twitter profile URL on a supported host (`x.com`, `twitter.com`, `mobile.*`) with exactly one non-reserved
    path segment.

  `https://example.org/team/acme`, `x.com/acme/status/1` and `x.com/home` establish nothing. Bare and URL handles keep
  working.

**Regressions** (`test_legacy_import.py`):
- 15 parametrised `own_accounts` cases covering every input above;
- a plan-level test with integer aliases, a string alias, an `"unknown"` id and an unrelated `x` URL: no exception,
  no blockers; the unrelated X URL stays weak, and the `"unknown"` id's GitHub URL stays weak.
- **Mutation:** loosening the numeric id check fails 2 tests. Restored.

**Real snapshot:** plan 0 blockers; identifiers unchanged at 663 (profile_url 230, url 17, alias 24, orcid 162, openalex
206, github 24). Rehearsal passed with all counts matching.

**Results:** gate ALL CHECKS PASSED (pytest 977); hosted **58 passed**.

## Codex verdict on revision 3

**APPROVE WITH CHANGES.** All 15 ownership-evidence cases passed on my rerun. Alias and X handling address H-080. One discrepancy remains between validating a GitHub account and storing its strong identifier. I ran `_person_identifiers` with integer ID 42 and a matching profile: it emitted the profile and alias but dropped the GitHub ID. With `github_id="not-a-number"` it emitted a strong GitHub identifier. Use one positive decimal ID validator for both paths. Add mapper-level assertions that integer 42 and string "42" yield the same stored identifier, and malformed IDs yield none. Claude reports 663 identifiers in the real snapshot and a successful rehearsal.

## Grok notes
