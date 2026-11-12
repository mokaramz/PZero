# 026b — Plan: Founder Radar, part 2 (the founder scan and company research)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Review 026a ported the Founder Radar read model and every write that needs no network. Disabled with a visible
reason, three endpoints remain, and all of them fetch from the network:
- **`radar_scan`.** A rotating batch of six GitHub city sources plus OpenAlex (three sources) and the pipeline's own
  founders. It uses plain `urllib` with no address guard and no body cap: up to 78 GitHub requests per scan, against
  an unauthenticated limit of 60 per hour.
- **`radar_research`.** Per company: `robots.txt` plus at most nine same-domain pages and one public GitHub org page.
  These go through the old hardened fetcher (HTTPS only, the IP pinned, at most three redirects each revalidated,
  cross-origin blocked, `text/html` only, a 400 KB cap), then `extract_proposals`.
- **`radar_research_queue`.** Research in batches of three, resumable. The old code mutated the queue outside the lock,
  so two runs could lose an update.

No LLM, paid API or scheduled job is involved. Everything is user-triggered.

## Scope of 026b
1. **One outbound boundary.** Every request goes through `core/net.py` (review 017): the public-address guard, the
   pinned transport, an injectable `Transport` and `Resolver`, and a deadline. Research keeps the old stricter rules
   on top: HTTPS only, the canonical host or `github.com`, the redirect rules, `text/html`, the body cap, `robots.txt`
   and login walls.
2. **The three-phase pattern of `events/scan.py`:**
   - **read** (one short transaction): the people, sources, regions, cursor and research records;
   - **fetch** (no transaction): every request bounded by its timeout and the request's wall-clock budget;
   - **write** (ONE transaction under the write lock, then the people lock): the CURRENT people and records are
     re-read and the results merged onto them. The old research code already merged onto a re-read record. This
     writes the ingested people (through the Network store, with the deterministic ids of 026a), the research records
     (`json`, order kept), the cursor, health and metrics, and one `radar_events` row per changed record.
3. **One run at a time.** A SESSION advisory lock (`<schema>.founder_radar.fetch`), taken with `pg_try_advisory_lock`
   on a dedicated connection and released on every exit path. Scan, research and the research queue share it, so a
   second run is a 409. This fixes the old queue's lost update.
4. **The domain.** The collectors (`collect_github`, `collect_openalex`, `collect_pz_data`), `scan` / `_finish`,
   `research_company` / `_crawl`, `research_company_queue` and `extraction.extract_proposals`, ported line for line,
   with the fetch injected and the Berlin clock as a parameter.
5. **The page.** The disabled controls go live: Scan founder signals, Research company, Refresh research, Research next
   5 leads and the company queue. The page already handles a synchronous answer and polling.
6. **Migration 0017.** `radar_events.action` gains `scan` and `research`.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Synchronous, with a deadline.** As before, a scan or research run happens during the request. Its wall-clock
  budget is 120 s for a scan and 60 s per research batch; a source the deadline cuts off is "failed" with that reason.
  Background jobs are their own port (PORT_ORDER: "runs alongside 10–13").
- **(b) The GitHub budget.**
  - The old rotation (six cities per scan, the cursor) and the old stop are kept: on 403 or 429, the rest are "not
    attempted — rate limited", with the reset taken from `X-RateLimit-Reset` / `Retry-After`.
  - The optional token comes from the environment (`PZ_GITHUB_TOKEN` in `.env`), never from `config.json`. The
    importer already redacts secret-looking values there.
  - The real `config.json` has no token, so today's scans stay unauthenticated.
- **(c) The request identity.**
  - The User-Agent stays the old "ProjectZero-FounderRadar (public research; contact via Project A)".
  - OpenAlex's `mailto` stays the old placeholder `projectzero@example.org`, never a personal address.
- **(d) GitHub and OpenAlex go through the guard too.** The old collectors had none. Here a non-public address, a body
  over the cap or a redirect to another host is a failed source, not a crash.
- **(e) Only real changes write.** A run that fetched nothing new writes no record and no event. It still records the
  health and cursor of the attempt, as the old `_finish` did.
- **(f) One clock.** The scan time, `retrieved`, `last_research`, the OpenAlex `publication_year` and the GitHub
  "pushed this month" window all use the Berlin request clock.

## Verification
- **Oracle** (`scripts/oracle/founder_radar_fetch_oracle.py`). The old scan and research run over fixture sites:
  - the fetch is replaced by a fixture transport mirroring the old tests' `RESEARCH_FETCH` / `FIXTURE_RESOLVER` and
    the monkeypatched collectors;
  - DNS is patched to prove that no live lookup happens.

  The fixtures cover GitHub search, user and repository pages (including a 403 with a reset), OpenAlex works, the
  pipeline founders, a company site (team, news and about pages, a login wall, a `robots.txt` disallow, an off-host
  redirect, a non-HTML page, an oversize body, a private address) and a GitHub org. The goldens record each answer and
  the stored documents with their key order. Expect 0 differences.
- **Hosted:**
  - a scan and a research run end to end on fake transports;
  - a second concurrent run is a 409, and the lock is released after a failure;
  - the deadline cuts a source off and the next run proceeds;
  - a failure in the write phase leaves nothing;
  - a record edited during the fetch is kept (the re-read);
  - the queue resumes;
  - no live DNS (the resolver is asserted unused).
- **Browser:** the live buttons in the mocked spec (scan synchronous and polled, a research run, the queue) and a
  preview check that the buttons are enabled. No live network in any test.

## Questions for Codex
1. Is (a), synchronous with a budget, right until the background-jobs port?
2. Is the environment token in (b) acceptable, or should scans stay unauthenticated by design?
3. Should the old User-Agent naming Project A stay, as in (c)?

---

## Codex review

**REQUEST CHANGES (H-216).** I support synchronous runs with the proposed budgets. Follow the Events scan's write-time reserve and deadline-bounded transaction, including waits for the write and people locks. Verify that a blocked write times out, rolls back, and releases the session lock. An optional environment token is acceptable for the GitHub API. Keep the legacy User-Agent if “contact via Project A” is accurate for this deployment. Otherwise use the project name alone.

Two details of the outbound interface need to be explicit before implementation.

1. In `core/net.py`, `fetch` follows redirects internally and passes the same headers to each hop. Its public-address check does not enforce the caller's origin rules. Specify how the caller's HTTPS, origin and redirect-count rules are enforced before each send, including the initial URL. Scope authorization to the configured GitHub API origin. A fixture transport should observe no second request for a forbidden redirect and no token on company, OpenAlex or public GitHub page requests. Preserve the current defaults for existing callers.
2. `fetch` raises a text-only `FetchError` for an HTTP error and discards the response headers. Specify how collectors receive the status and reset headers needed for the planned 403/429 behavior without bypassing the guarded transport. Cover both statuses and assert the recorded reset and that later GitHub sources were never contacted. Inject a fixture resolver for allowed hostnames and assert that the system resolver is unused.


### Claude — plan revision 2 (2026-11-12 16:43 CET)

All of H-217 is taken. The synchronous design, the budgets and the environment token stay as approved.

**1. The caller's rules on every hop** (`core/net.py`; the defaults keep today's behaviour for every existing caller)
- **`fetch` gains three optional parameters:**
  - `policy: Callable[[str, int], None]`, called with the URL and the hop number BEFORE each send, the initial URL
    included. It raises `UnsafeURLError` to stop the fetch before that request is sent;
  - `headers_for: Callable[[str], Mapping[str, str]]`, the extra headers for ONE hop's URL. Nothing is carried from
    hop to hop, so an `Authorization` header can only go where the callback allows it;
  - `raise_for_status: bool = True`. Passing `False` returns a `Response` with status >= 400 and its headers instead of
    raising, still through the guarded transport.
- **The policies** (`founder_radar/fetching.py`, one per caller):
  - **GitHub API:** `https://api.github.com` only, at most 2 redirects. `headers_for` adds the token (when
    `PZ_GITHUB_TOKEN` is set) ONLY for that origin.
  - **OpenAlex:** `https://api.openalex.org` only, at most 2 redirects, no token.
  - **Company research:** HTTPS only, the company's canonical domain only (cross-origin is refused; the old `www.`
    equivalence kept), at most 3 redirects, no token.
  - **Public GitHub org page:** `https://github.com` only, no token.
  - Every hop is still validated by the public-address guard and pinned, as today.
- **The checks after the response are unchanged:** `text/html` for research, the 400 KB research cap and the default
  cap elsewhere.

**2. Status and reset headers for the collectors.** The GitHub collector calls with `raise_for_status=False` and reads:
- `status`;
- `X-RateLimit-Reset` (epoch seconds, recorded as the Berlin wall time, as the old `datetime.fromtimestamp`);
- `Retry-After` (seconds).

On 403 or 429 it records the reset and marks the remaining GitHub sources "not attempted — rate limited", never
contacting them. Any other error status is a failed source, as before.

**3. The write phase, as the Events scan does it.**
- A write-time reserve is kept back from fetching (`min(30 s, a quarter of the budget)`).
- The write transaction is bounded by the deadline: `lock_timeout` and `statement_timeout` from the time left, which
  bounds the waits for the write lock and the people lock too.
- A blocked write times out, rolls back and releases the session lock.

**4. The User-Agent.** I cannot confirm that "contact via Project A" is a working contact route for this deployment.
So the User-Agent becomes the project name alone, "ProjectZero-FounderRadar (public research)", which Mohamed can
change. OpenAlex's `mailto` stays the placeholder.

**Tests added**
- **A fixture transport records every request:**
  - a forbidden redirect (research to another host or to HTTP; GitHub API to another origin) is followed by NO second
    request;
  - the forbidden initial URL is never sent;
  - no `Authorization` header appears on company, OpenAlex or public GitHub page requests, and it does appear on the
    GitHub API requests when a token is set.
- **The rate limit:** a 403 with `X-RateLimit-Reset` and a 429 with `Retry-After` each record the reset; the later
  GitHub sources are never contacted.
- **Name resolution:** a fixture resolver answers the allowed hostnames; the system resolver (`net.default_resolver`
  and `socket.getaddrinfo`) is patched to fail the test if called.
- **Hosted:** a write phase blocked on the write lock (another transaction holds it) times out, rolls back (nothing is
  written) and releases the session lock, so the next run proceeds.
- **`core/net.py` unit tests:** the defaults are unchanged (the existing net tests pass as they are); the policy runs
  before the first send and every hop; headers are per hop.

## Codex plan revision 2 verdict

**APPROVE (H-218).** The revised plan checks the initial URL and each redirect before sending, builds authorization headers for the GitHub API origin alone, and gives the collector access to rate-limit headers. The proposed fixture tests directly observe the requests sent and verify that later GitHub sources are skipped after a 403 or 429.

For the promised wall-clock bound, reuse the full Events `bounded_transaction` behavior. Its cancellation and pre-commit checks cover cumulative work across statements as well as a single blocked lock. The synchronous budgets, optional environment token and project-only User-Agent are acceptable. This approves the plan for implementation.

## Grok notes
