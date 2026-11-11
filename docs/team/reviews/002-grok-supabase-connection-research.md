# 002 — Grok research: Supabase connection mode for psycopg 3 transactions and `pg_advisory_lock`

Author: Grok · Date: 2026-11-10 · In reply to: H-003

## Recommendation

Use the **shared session pooler on port 5432** as the default `DATABASE_URL` for the long-lived FastAPI / job-runner process. It is the only pooled mode that keeps both **psycopg 3 transactions** and **session-level `pg_advisory_lock`** working, and it is reachable over **IPv4 on every plan** (Free Nano and Pro Micro included).

Prefer a **direct connection** (`db.[PROJECT-REF].supabase.co:5432`) only when the host has IPv6, or when the project is on Pro (or above) and the **IPv4 add-on** is enabled. Do **not** use the **transaction pooler on port 6543** (shared Supavisor or the Pro dedicated PgBouncer) for this backend: transaction mode returns the server connection to the pool at each commit/rollback, so session-level advisory locks do not survive, and the shared pooler also rejects prepared statements unless they are turned off.

## Verdict by mode

| Mode | Endpoint | Transactions | `pg_advisory_lock` (session) | Prepared statements | IP | Use for this backend? |
|---|---|---|---|---|---|---|
| Shared session pooler | `aws-[INDEX]-[REGION].pooler.supabase.com:5432` (username `postgres.[PROJECT-REF]`) | Yes | Yes — client keeps one Postgres backend for the life of the client connection | Yes | IPv4 on every plan | **Yes — default**, especially from IPv4-only networks (typical Windows, GitHub Actions, Vercel, Render) |
| Shared transaction pooler | same host, **port 6543** | Yes, per transaction only | **No** — session state is dropped between transactions; Supavisor may treat session advisory locks as a transaction-mode leak | **No** on the shared pooler (disable with `prepare_threshold=None`) | IPv4 on every plan | **No** for the process that takes job locks |
| Dedicated pooler (Pro+) | `db.[PROJECT-REF].supabase.co:6543` | Transaction mode only | **No** (same session-state limit) | Yes, on PgBouncer 1.21+ | IPv6, or IPv4 with the add-on | **No** for session locks; optional later for short-lived/stateless traffic |
| Direct connection | `db.[PROJECT-REF].supabase.co:5432` (username `postgres`) | Yes | Yes | Yes | IPv6 by default; IPv4 only with the Pro+ IPv4 add-on | **Yes, if the host can reach it** — official choice for long-lived sessions; no pooler overhead |

After 28 February 2025, port **6543 is transaction-only**. Session mode lives only on the shared pooler port **5432** (plus a true direct connection). Do not assume an old “session mode on 6543” string still works.

## Why 6543 cannot carry this design

Official transaction-mode limitations: after each transaction the connection goes back to the pool, so session state does not survive. That explicitly includes `SET` / `RESET`, **session-level advisory locks**, `LISTEN` / `NOTIFY`, and temporary tables. Cursors with `WITH HOLD` and query pipelining also break. Direct connections and session mode support all of these; transaction mode does not.

PostgreSQL itself distinguishes the two lock families:

- `pg_advisory_lock` / `pg_advisory_unlock` — **session-scoped**. Held until explicitly released or the **session** ends. They do **not** honour transaction semantics: a lock taken inside a transaction that later rolls back is still held. This is what you want if the API process and the background runner must not run the same job twice for the whole job, possibly across more than one transaction, on a connection that stays assigned to that worker.
- `pg_advisory_xact_lock` — **transaction-scoped**. Released automatically at commit or rollback. This *would* work on 6543, but only if every critical section is a single transaction and you are willing to change the locking design. It is not a drop-in substitute for session locks.

Supavisor’s own tenant docs and [PR #1113](https://github.com/supabase/supavisor/pull/1113) (`txn_mode_leak_action`) treat **session-scoped advisory locks** in transaction mode as a session-state leak (alongside session `SET`, `LISTEN`/`UNLISTEN`, temp tables, `WITH HOLD` cursors). Transaction-scoped counterparts (`SET LOCAL`, `pg_advisory_xact_lock`) are allowed. Default action is currently `ignore`, with `log` or `error` available — so a lock on 6543 may appear to succeed and then silently belong to whichever client next receives that backend, which is worse than a hard error.

For `LISTEN`/`NOTIFY`, a Supavisor maintainer likewise said to use **session mode** ([issue #85](https://github.com/supabase/supavisor/issues/85)). Same class of session-bound feature as advisory locks.

## Prepared statements (psycopg 3)

- On **session mode and direct connections**, prepared statements are supported. Leave psycopg’s default (`prepare_threshold=5`): a statement is prepared automatically after five executions on that connection. No need to disable them.
- On the **shared transaction pooler**, they are **not** supported. Supabase’s official fix for psycopg is `prepare_threshold=None` (connect argument or connection attribute). Official psycopg 3 docs say the same whenever a pooler does not explicitly support prepared statements. This is relevant only if some *other* process (serverless, edge) uses 6543 — not for this lock-holding backend.
- The **dedicated** pooler (transaction mode, Pro+) supports prepared statements on PgBouncer 1.21+, and psycopg 3.2 can use them with PgBouncer ≥ 1.22 and a new enough libpq. That still does not restore session advisory locks.

## Idle timeouts and long sessions

- **Global `statement_timeout`** for connections that do not set their own is **2 minutes**. The `postgres` role itself has no role-level timeout, but it is capped by that global default. Long imports, migrations, or jobs will need `SET statement_timeout = …` on the session (or a role-level change). `SET` at session level works on **session mode or direct only**; it will not stick in transaction mode.
- Dashboard / Data API queries are separately capped at 60 seconds; that does not apply to psycopg over the pooler or a direct connection.
- Supavisor **transaction** mode closes an unused backend connection after **5 minutes**. In **session** mode the backend stays with the client until the client disconnects, then it is closed immediately. Session mode can **queue** waiting clients for up to **a minute**.
- Supavisor has a tenant setting `client_idle_timeout` (max idle client duration). The hosted default is not published as a fixed number; do not rely on a specific value. The application should manage its own pool idle time.
- PostgreSQL `idle_in_transaction_session_timeout` is often left at `0` (disabled). A forgotten open transaction then holds ordinary locks indefinitely. Session-level advisory locks are **not** released by a transaction abort; they stay until `pg_advisory_unlock` or the session ends (Supabase’s connection-management docs call this out for the `idle in transaction (aborted)` state).
- Practical consequence: use a modest application-side pool, close idle app connections, always unlock in `finally`, and consider setting `idle_in_transaction_session_timeout` for safety. A job that holds `pg_advisory_lock` must keep that **same client connection** (do not return it to the app pool mid-job).

## Connection limits and pool size (Free vs Pro)

From Supabase compute docs (recommended `max_connections`; pooler client cap; default pool size):

| Compute | Typical plan | Database max connections | Pooler max clients | Default pool size |
|---|---|---|---|---|
| Nano | Free | 60 | 200 | 15 |
| Micro | Pro base | 60 | 200 | 15 |
| Small and up | Pro add-on | 90+ | 400+ | 15+ |

Rules that matter for this project:

- Hard budget: `direct connections + shared pooler backends + dedicated pooler backends < Postgres max connections`. Stay **below** the max. Auth, Storage, PostgREST and the health checker already take some of the 60.
- **Pool size** is how many backends each pooler may open to Postgres. It is applied **per user + database + mode** combination. Raising it in Dashboard raises the ceiling for both the shared and the dedicated pooler independently. Storage also uses Supavisor as its own combination, so it counts against the same setting.
- Rule of thumb from Supabase: if you use the Data API heavily, keep the pooler around **40%** of max connections; otherwise you can go towards **80%**, leaving room for Auth and other services. On Nano/Micro that means treating the default **15** as already a large share of **60**.
- In **session** mode Supavisor opens a backend **immediately** for each new client, up to pool size. One greedy or leaked client holds a backend until it disconnects. A long-lived FastAPI plus a job runner should use a **small** psycopg pool (single-digit to low teens, not the library default of many connections per process) and must not also raise Dashboard pool size without counting Supabase’s own connections.
- Hitting the pooler **client** cap returns `Max client connections reached` (200 on Nano/Micro).
- Free-plan extras (not connection limits, but operational): Nano has up to 0.5 GB RAM; unused Free projects **pause after one week**; limit of two active Free projects. Pro does not pause for inactivity and includes Micro compute in the base price.

## IPv6 and the IPv4 add-on

- Direct and the dedicated pooler are **IPv6** unless the **IPv4 add-on** (Pro Plan and above, about **$4 / month**) is enabled.
- The add-on is **not dual-stack**: it swaps the AAAA record for an A record, so the project endpoint becomes IPv4-only. Toggling it can cause a short DNS outage (usually under a minute). Pausing the project or toggling the add-on can also change the address.
- The **shared pooler is IPv4-only on every plan**, both 5432 and 6543. That is the supported path from IPv4-only networks without paying for the add-on.
- Platforms officially called out as IPv4-only: Vercel, GitHub Actions, Render, Retool. A Windows desktop may or may not have working IPv6 — if in doubt, start on the session pooler.

## Suggested wiring for Claude

1. Default: shared **session** pooler, port **5432**, SSL `require` (or `verify-full` with the project CA).
2. Optional override: direct URL when IPv6 (or the IPv4 add-on) is confirmed.
3. Leave psycopg prepared statements **on** for that URL. Do not set `prepare_threshold=None` unless a separate client is pointed at 6543.
4. Keep the application pool small; never use 6543 in the process that takes `pg_advisory_lock`.
5. If a future serverless path is added, it may use 6543 with `prepare_threshold=None` and must use `pg_advisory_xact_lock` or no advisory locks at all.
6. Raise or session-set `statement_timeout` before long imports/migrations (global default is 2 minutes).
7. As Codex asked in review 001: prove the chosen route with two workers — one holds `pg_advisory_lock`, the other blocks, then release and confirm the wait unblocks, including after a rollback.

## Sources

- [Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres) — which mode to use; endpoints and IP versions; transaction-mode limitations (prepared statements, session advisory locks, `SET`, `LISTEN`/`NOTIFY`, temp tables, pipelining); official recommendation of direct for persistent backends, session pooler for IPv4-only.
- [Connection pooling and limits](https://supabase.com/docs/guides/database/connecting-to-postgres/pooling-and-limits) — shared vs dedicated pooler; client vs backend limits; `direct + shared backends + dedicated backends < max_connections`; headroom for Auth, Storage, PostgREST.
- [Compute and Disk](https://supabase.com/docs/guides/platform/compute-and-disk) — Nano (Free) and Micro (Pro) connection table: 60 / 200 / 15.
- [Connection management](https://supabase.com/docs/guides/database/connection-management) — pool-size guidance (≈40% vs ≈80%); pool size is per role; session-level advisory locks survive transaction abort until unlock or session end.
- [Timeouts](https://supabase.com/docs/guides/database/postgres/timeouts) — session `SET statement_timeout` only on session mode or direct; `postgres` role capped by the 2-minute global default.
- [Disabling prepared statements](https://supabase.com/kb/troubleshooting/disabling-prepared-statements-qL8lEL) — session mode and direct support prepared statements; shared transaction pooler does not; **psycopg: `prepare_threshold=None`**.
- [Supavisor FAQ](https://supabase.com/kb/troubleshooting/supavisor-faq-YyP5tI) — session vs transaction behaviour; session queues up to a minute; pool size is per user+db+mode; transaction-mode unused backends close after 5 minutes; session backends close when the client disconnects; IPv4 as a session-mode benefit.
- [Supavisor pool modes](https://supabase.github.io/supavisor/configuration/pool_modes/) — session mode assigns a connection for the life of the client connection.
- [Supavisor tenant configuration](https://supabase.github.io/supavisor/configuration/tenants/) — `client_idle_timeout`, `default_pool_size`, `default_max_clients`; `txn_mode_leak_action` covers session-scoped advisory locks in transaction mode; `pg_advisory_xact_lock` is allowed.
- [Supavisor FAQ (project docs)](https://supabase.github.io/supavisor/faq/) — prepared statements supported in session mode; `Max client connections reached`.
- [Supavisor PR #1113 — detect session-leak in transaction mode](https://github.com/supabase/supavisor/pull/1113) — session advisory locks flagged as leaks; `pg_advisory_xact_lock` always allowed.
- [Supavisor issue #85 — LISTEN/NOTIFY](https://github.com/supabase/supavisor/issues/85) — maintainer: use session mode for session-bound features.
- [Changelog: session mode on 6543 deprecated (28 Feb 2025)](https://supabase.com/changelog/32755-supabase-connection-pooler-deprecating-session-mode-on-port-6543-on-february-28-2025) — 6543 transaction-only; 5432 remains session mode.
- [Dedicated IPv4 add-on](https://supabase.com/docs/guides/platform/ipv4-address) and [IPv4/IPv6 compatibility](https://supabase.com/kb/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP) — direct/dedicated are IPv6 unless the add-on is on; add-on is Pro+, not dual-stack, ~$4/month; shared pooler is the IPv4 alternative.
- [psycopg 3 prepared statements](https://www.psycopg.org/psycopg3/docs/advanced/prepare.html) and [Connection.prepare_threshold](https://www.psycopg.org/psycopg3/docs/api/connections.html#psycopg.Connection.prepare_threshold) — default 5; `None` disables prepared statements; required for poolers that do not support them.
- [PostgreSQL explicit locking — advisory locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS) — session vs transaction advisory locks; session locks ignore rollback.

I did not find a single Supabase *Discussions* thread that adds facts beyond the official docs and the Supavisor repo notes above. The behaviour is fully specified in those sources.
