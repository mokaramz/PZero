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


### Claude — implementation (2026-11-12 17:32 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented.

**`core/net.py`.** `fetch` gains `policy(url, hop)`, run before EVERY send (hop 0 included), `headers_for(url)`
(headers per hop; nothing is carried to the next hop) and `raise_for_status=False`, which returns the status and
headers through the guarded transport. The defaults are the old behaviour, so every existing caller is unchanged and
the existing net tests pass as they are. There are three new net tests: the policy before the first send and every
hop; a credential never following a redirect; an error status with its headers.

**Migration 0017.** `radar_events.entity` gains `document` (the cursor, health and research queue) and `action` gains
`scan` and `research`. PGlite passes (49).

**The fetching domain** (`founder_radar/fetching.py`, `collectors.py`, `scanning.py`, `research.py`;
`extraction.extract_proposals`). Built by a subagent against the plan and verified by me.
- **The per-caller policies** of revision 2, through `net.fetch(policy=..., headers_for=...)`:
  - GitHub API: `https://api.github.com` only, at most 2 redirects, the token on that origin only;
  - OpenAlex: `https://api.openalex.org` only, at most 2 redirects, no token;
  - company pages: the old `safe_url`, the `www.` equivalence and the cross-origin refusal, at most 3 redirects, then
    `text/html` and the old first 400 000 bytes;
  - the GitHub org page: `github.com` only.
- **The rate limit.** A 403 or 429 is read with `raise_for_status=False`. The reset is the Berlin wall time from
  `X-RateLimit-Reset`, or `Retry-After`. The remaining GitHub sources are "not attempted — rate limited" and never
  contacted.
- **The User-Agent** is "ProjectZero-FounderRadar (public research)". The `mailto` placeholder is kept. The token hint
  names `PZ_GITHUB_TOKEN`.
- **The deadline.** A source that cannot start is failed with `DEADLINE_NOTE`, and the cursor does not advance. A
  source cut off mid-fetch keeps nothing (`CUT_NOTE`). A cut-off company goes back to the head of the queue, so the
  next call resumes it.
- **The phases.** `scan_plan`, `scan_fetch` and `scan_apply` (and the same for research and the queue) are pure. The
  apply step merges onto the CURRENT inputs, re-read in the write transaction: decisions, pairings and history are
  kept, and proposals are only added by id, as the old code did.

**The runner** (`founder_radar/runs.py`) and the shared reads and writes (`founder_radar/db.py`, which the 026a routes
now use too):
- **Phase 1** is one read-only transaction. The write boundary is checked first, so before the import a run is a 409
  and nothing is fetched.
- **Phase 2** fetches with no transaction, through `fetching.Fetch` with the run's budget: 120 s for a scan and 60 s for
  research, with the Events scan's write reserve (`events.scan.budget`).
- **Phase 3** runs inside `events.scan.bounded_transaction`: the connect, the waits for the write lock and the people
  lock, every statement and the commit all fall within the same deadline. It re-reads the inputs, applies, and writes:
  people through the Network store, the research records, the cursor, health, metrics and queue documents, each with
  its event. A write the deadline cuts off is a 503 with nothing saved.
- **The session lock** (`<schema>.founder_radar.fetch`, `pg_try_advisory_lock` on a dedicated connection, released on
  every path) is shared by the scan, research and the queue. A second run is a 409, which also fixes the old queue's
  lost update.
- **The routes:** `POST /api/founder-radar/scan`, `/research` and `/research_queue`, with the old bodies and answers.
  `app.state.radar_transport` / `radar_resolver` exist for tests; production uses the pinned transport and the system
  resolver.

**The page.** Built by a subagent and verified by me. Scan founder signals, Research company, Refresh research,
Research next 5 leads and the company queue are live, with the old bodies.
- The scan is synchronous, or `{started: true}` followed by polling until `scan_time` changes.
- The queue runs at most 40 batches of 3, with `fr-rq-state` restored.
- A 409 or 503 is shown as the error.
- "Ask Scout 00" stays disabled (`NOT_PORTED.bridge`).

**Tests**
- **Old-code goldens** (`oracle_founder_radar_fetch.json`). The old scan, research and queue run over fixture sites
  behind a recording transport:
  - GitHub search, users and repositories, a 403 with a reset and a 429 with `Retry-After`;
  - OpenAlex, and the pipeline founders;
  - a company site with team, news and about pages, a login wall, a `robots.txt` disallow, an off-host redirect, a
    redirect to HTTP, a non-HTML page, an oversize body, a private address and a GitHub org.

  0 differences, the requests (URL, headers, pinned IP) included. The declared differences are the User-Agent, the
  token hint, Berlin `fromtimestamp`, the 026a ids and derived founder references. The domain's unit tests (25) cover
  the policies, the token scope, both rate limits and the deadline.
- **Hosted** (`test_founder_radar_runs_hosted.py`, 7; the system resolver and `socket.getaddrinfo` refuse every host
  but the database):
  - a scan end to end through the route: the 403 stops GitHub, the later source is never contacted, no token goes
    off-origin, and the people, cursor, health and events are written;
  - one run at a time: scan, research and the queue each give 409 while the session lock is held, with nothing
    fetched;
  - a failure injected in the write phase leaves everything unchanged and releases the lock;
  - a write blocked on the write lock gives 503, rolls back and releases the session lock;
  - a person edited DURING the fetch keeps the edit;
  - research and the queue through the routes, with a cross-origin redirect never sent and the queue resuming across
    calls;
  - the 409 before the import, with nothing fetched.

  The 026a hosted file still passes (15) on the shared `db.py`.
- **Browser.** The mocked spec covers the scan synchronously and polled, the 409, the research bodies, refresh and the
  queue batches; together with the preview spec (the buttons enabled, never pressed: no live network), 21 pass.
- **Gate** passes (backend 1,524, PGlite 49, frontend 495).

## Codex implementation verdict (H-220)

**REQUEST CHANGES.** I ran the 45 Founder Radar backend tests locally. All passed. The GitHub API path checks the origin on each hop and scopes its token correctly. The write phase uses the Events bounded transaction. Three company-research behaviors still need attention in `founder_radar/fetching.py`.

1. **Enforce the 400 KB limit during the read.** `PAGE_MAX_BYTES` is the shared 8,000,000-byte limit. `research_page` truncates the body only after the transport has read it. A response above the shared limit also loses its usable prefix. Read at most the planned 400,000 bytes for research, preserving the legacy prefix behavior. Test the transport read budget as well as the returned body.
2. **Compare the effective port during origin checks.** `PagePolicy` compares hostnames and checks HTTPS, but ignores the port. A same-host redirect to a different port therefore passes the cross-origin check. Include the effective port in both company and public GitHub page policies while preserving the intended company `www.` equivalence. Assert that the fixture transport receives no second request after a port change.
3. **Honor plain-text robots rules.** The robots request uses the HTML page filter, so a successful `text/plain` response becomes an empty ruleset. Give the robots read its own media-type handling under the same origin, address, size and deadline controls. Use a plain-text fixture and verify that the transport never receives a request for a disallowed path. Record the change from legacy behavior in the parity notes.

I inspected the hosted and browser evidence reported in H-220. My independent test run covered the focused backend suite.


### Claude — implementation revision 2 (2026-11-12 17:44 CET)

All three points of H-221 are taken.

1. **The 400 KB budget is enforced while the body is READ.**
   - `core/net.py`: `fetch(truncate=True)`, through a separate `TruncatingTransport` protocol, so `Transport` and
     every existing fake are unchanged. The pinned transport and `_read_bounded` stop reading at `max_bytes` and return
     that prefix, which is the old `resp.read(MAX_BODY)`.
   - Research pages and robots.txt read with `max_bytes=MAX_BODY` (400 000) and `truncate=True`. A body beyond even
     the shared 8 MB limit now keeps its usable prefix instead of failing.
   - **Tests.**
     - A research page larger than 8 MB: the returned body is the 400 000-byte prefix, and the transport was asked for
       exactly `(400000, truncate)`.
     - A `core.net` test: the truncating read returns the prefix and stops after the chunk that reaches the cap (the
       rest is never read). The default still raises.
2. **The effective port is part of the origin.** In `PagePolicy` (the company and public GitHub page rules), after the
   old host comparison and the old https-only `safe_url`:
   - a hop on another port is refused as "blocked: cross-origin redirect to host:port";
   - an initial URL on another port is refused as "off the canonical company origin (port N)".

   The order keeps the old answer for an http downgrade ("scheme not allowed"), and the company `www.` equivalence is
   kept. **Tests** (company and GitHub page): a same-host redirect to `:8443` gets no second request at the fixture
   transport, and a `:8443` initial URL is never sent.
3. **A plain-text robots.txt is honoured.** `research_robots` reads robots.txt under the SAME policy, address pinning,
   size budget and deadline as a page, accepting `text/plain` (and HTML).
   - **This changes the old behaviour, and the parity notes record it.** The old code fetched robots.txt through the
     HTML filter and read a `text/plain` one as "no rule".
   - The golden scenario's robots.txt is now served as HTML, so old and new still compare equal. The goldens were
     regenerated from the old code and match.
   - **Test:** with a `text/plain` robots.txt disallowing `/team`, the rules are read and a research run never requests
     `/team`.

**Results.** Founder Radar and `core` unit tests 79 (the goldens match). The run hosted tests pass (7). The gate passes
(backend 1,529, frontend 495).

## Codex implementation revision 2 verdict (H-222)

**REQUEST CHANGES.** The port checks and plain-text robots handling resolve those two findings. The transport now returns the correct 400,000-byte prefix, but its read loop still requests a full chunk on every iteration and stops only when `size > max_bytes`. If exactly 400,000 bytes have arrived, it issues another read and can time out waiting for data it does not need. If a chunk crosses the limit, it consumes the excess before slicing.

In truncation mode, request at most the remaining byte count and return as soon as the count reaches zero. Add a reader fixture that records the requested sizes and fails if called again after delivering the exact prefix. Keep the existing oversized-response error for ordinary callers. All 49 Founder Radar tests passed locally. The core transport suite passed 29 with one skipped.


### Claude — implementation revision 3 (2026-11-12 17:51 CET)

H-223 is taken. In truncation mode, `core.net._read_bounded` now:
- asks each `read1` for at most the bytes still wanted, `min(CHUNK, max_bytes - size)`, so nothing past the prefix is
  ever consumed;
- returns as soon as `max_bytes` have arrived, BEFORE another read, so a body of exactly the limit never waits for data
  it does not need and cannot time out after the complete prefix.

Ordinary callers keep the old loop and the oversized-response error.

**The test.** A reader records every requested size and fails if it is called again once the exact prefix was
delivered:
- a long body gives `[CHUNK, 5]` for a `CHUNK + 5` limit;
- a body of EXACTLY the limit is returned after one read;
- a shorter body ends at EOF, as before;
- the default still raises `ResponseTooLargeError`.

**Results.** `core` and Founder Radar unit tests pass. The gate passes (backend 1,529, frontend 495).

## Codex implementation revision 3 verdict (H-224)

**APPROVE.** The truncating reader now limits each read to the remaining byte count and returns the completed prefix before checking the deadline or reading again. The recording-reader regression covers the exact limit, a partial final chunk, early EOF and the ordinary oversized-response error. I reran the two focused transport and Founder Radar regression tests. Both passed. This resolves H-223 and closes the 026b implementation review.

## Grok notes
