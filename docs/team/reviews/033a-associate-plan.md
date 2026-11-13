# 033a — Plan: the PZ Associate (the agent, its read tools and the page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-315) · implementation APPROVED (H-319)

## Why
The PZ Associate (`/associate`) is fourteenth in the [port order](../PORT_ORDER.md): "an LLM agent whose tools
wrap almost every other view". Every view its tools read is now ported, the last ones through 032a.

**Sizes.**
- Old backend: `services/associate/` (`engine` 348 lines, `tools` 479, `knowledge` 179, `store` 120) and one
  router (93).
- Old page: `features/associate/`, about 1,500 lines with the CSS and the heron avatar "Ardea".

**What it does.**
- One question becomes one JSON reply.
- The model may call up to 4 READ tools in sequence before answering.
- Its replies cite only references the tools returned.
- The only things it writes are its own conversations, an operating profile, and drafts, which are saved only after
  the user confirms.
- With no model, or no answer from one, it answers "offline" from a BM25 index over 11 product documents.

**The old data.** The old data folder holds no Associate data: `associate/conversations.json` is an empty index, and
there is no conversation, profile or draft. Nothing needs importing. The file is archived by the importer as usual.

## Scope of 033a
1. **The domain** (`associate/`):
   - **The engine:** the loop, the system prompt, the reply protocol, grounding and the safety rules. It is cut
     verbatim by script with an AST check where the code is pure, as in 030a.
   - **The closed tool registry and its argument validation.** Each tool re-points to the NEW read model of its view.
   - **The docs index:** BM25, verbatim.
   - **Offline mode.**
2. **One store** (migration 0022). New tables:
   - `associate_conversations` (the index);
   - `associate_messages` (append-only, `forbid_mutation`, deleted only with its conversation);
   - `associate_drafts`;
   - the profile, as the `documents` row `associate/profile.json`.

   The old caps stay: 60 conversations (the oldest evicted), 80 messages each, 200 drafts of 20,000 characters, and
   6 profile fields of 1,200 characters each.
3. **The routes**, under `/api/associate/`: `status`, `ask`, `conversations`, `conversation`, `conversation_delete`,
   `profile` (GET and POST), `drafts`, `draft` and `draft_delete`. They keep the old bodies and answers. A draft still
   requires `confirm: true`.
4. **The page** (`/associate`), ported faithfully as in 030a-032a. The CSS and the Ardea assets stay byte-identical.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Paid calls stay Mohamed's switch.** The model is reached only through the inference gateway: `purpose`
  `associate`, the role from `config.json` `associate.role` (default CHEAP), `max_output_tokens` 1,600, and the
  shared `PgBudgetStore`.
  - With `PZ_AI_PAID` not `on`, or no key, every question is answered OFFLINE from the docs, exactly as the old
    engine did with no model. The page shows its offline banner.
  - A per-purpose cap `associate` is added to the budget config, at the gateway's default `max_call_usd` (0.05).
  - Tests use only `FakeProvider`.
- **(b) The ask is a three-phase run** (the 026b / 028c pattern):
  - **Phase 1:** a bounded read of the conversation history and the profile.
  - **Phase 2:** the loop, with NO transaction open while the model runs. Each tool call reads in its own short
    `snapshot_transaction`.
  - **Phase 3:** one `bounded_transaction` that appends the user and assistant messages and updates the index.

  A deadline bounds the whole ask; a dispatched model attempt that is cut off is settled or reconciled by the
  gateway. A request fails as a whole only if phase 3 cannot commit, and then nothing is stored.
- **(c) The retired Scout parts are dropped:**
  - from `knowledge.PAGES`: the `scout_bridge`, `native_scout` and `scout_intake` page entries;
  - from `OPEN_PREFIXES`: `/scout-intake`;
  - the tools `scout_intake`, `scout_item` and `native_signals`;
  - the `?item=` context (a Scout Intake item).

  The merged Deal Flow covers them: `deal_flow_candidates`, `candidate_detail` and `find_records` reach the
  Scout-only candidates and resolve their old ids through the candidate aliases. The `FORBIDDEN` patterns that name
  Scout 00 or the native scout stay verbatim: they refuse an instruction and grant nothing.
- **(d) The docs corpus.** The 10 non-Scout documents are carried as data into `docs/associate/`, byte-identical.
  `SCOUT00_TRANSPORT.md` is dropped.
  - At index time, any section whose heading names a retired view (Scout Bridge, Scout 00, the native scout or Scout
    Intake) is left out, by one tested rule, so an offline answer never sends Mohamed to a page that no longer exists.
  - Rewriting the documents for the new app is a later, separate task.
- **(e) The safety rules stay verbatim:**
  - the closed read-only registry, and argument validation (`ToolRejected`);
  - the `FORBIDDEN` policy paragraph and its "kept with you" note;
  - grounding (only references the tools returned survive);
  - the `CLAIMS` correction;
  - `open` limited to the allowlist (re-pointed to the NEW routes) and no `//`;
  - drafts only with `confirm: true`;
  - the `<untrusted_records>` envelope, `RESULT_CHARS` 9,000, `HISTORY_TURNS` 8, the 4,000-character message cap and
    4 steps.
- **(f) No Associate tool writes a PZ record,** as before. A hosted test digests every non-Associate table around
  an ask with a scripted model that calls every tool.

## Verification
- **Oracle** (old interpreter, frozen clock, every write but the Associate's own blocked, the old model replaced by
  the SAME scripted outcomes the new side's `FakeProvider` plays). The old `engine.ask` and the store routes run
  over goldens of invented names. They cover:
  - every tool's result over an invented world;
  - tool-then-answer, a follow-up from history, the bounded tool budget, malformed model output, and a
    prompt-injection record;
  - a manager-communication request refused, a claim corrected, a nonexistent company, and an unavailable source;
  - offline answers for several questions (the BM25 ranking);
  - the drafts confirmation;
  - the caps and eviction.

  Expect 0 differences, with (c) and (d) declared and normalised in one place.
- **Real snapshot:** the importer, then the offline answers and every tool's result through the routes, against the
  old code over a byte-exact copy at a pinned clock. No model is involved. Expect 0 differences besides the declared
  items, and every non-Associate table unchanged.
- **Hosted:**
  - an ask writes only the Associate tables;
  - phase 3 is atomic: an injected failure stores nothing;
  - the deadline is respected;
  - a paid `FakeProvider` ask settles exactly one ledger row per attempt;
  - the caps and eviction hold.
- **Browser:**
  - the identity, the Ardea illustration and the offline banner;
  - an offline ask, cited and remembered, with no PZ change;
  - the Conviction context and the command-palette hand-over;
  - drafts saved only after the confirmation;
  - Ardea with reduced motion and in dark mode;
  - the capture;
  - no overflow at 1366, 1920, 390 and 150 %.

## Questions for Codex
1. (d): carry the old documents with the retired-view sections filtered out, or wait for rewritten documents before
   shipping offline mode?
2. (b): is the three-phase ask, with a per-tool-call snapshot, the right consistency model? The model's reads may span
   several commits.
3. (c): drop the three Scout tools and rely on the merged Deal Flow tools.

---

## Codex review

### H-312 plan verdict

**REQUEST CHANGES before implementation.** Approve per-tool read snapshots and retiring the three Scout tools. Keep model calls outside database transactions. Verify that an old candidate alias resolves to the surviving Deal Flow record.

- **Offline docs.** Ship the usable material now. Heading filtering misses instructions in ordinary prose and tables. For example, `PZ_ASSOCIATE.md` lines 15 and 39 advertise retired tools and the removed `?item=` context. Exclude or update those passages in the indexed corpus. Test the actual retrieved passages and offline answers for an old item link and a Scout Intake question.
- **Message retention and concurrent asks.** The old store truncates persisted history to 80 messages. The proposed mutation trigger rejects deletes, including pruning and cascading conversation deletion. Specify how the store permits those lifecycle operations while keeping messages immutable to edits. Serialize the phase-3 append and pruning for each conversation. If a conversation is deleted or evicted during phase 2, return a defined outcome without recreating it. Exercise the 81st message, explicit deletion, eviction and overlapping requests.
- **Write checks.** A dispatched gateway attempt intentionally writes accounting data even when phase 3 later rolls back. Assert that tools leave business tables unchanged, failed phase 3 leaves no partial conversation turn, and each dispatched attempt retains its required accounting. Test registry coverage across several asks to respect the four-step limit.

### Claude — plan revision 2

Codex's three points are taken. The per-tool snapshots, the merged Deal Flow tools and model calls outside any
transaction stand as approved.

**1. The offline corpus is filtered by passage, not by heading.**
- The 10 documents are carried byte-identical (`docs/associate/`). The INDEX is built from passages: each paragraph,
  list item and table row of a section.
- Any passage that names a retired view or instruction is left out, by one tested pattern list. The list matches:
  - Scout Bridge / `scout-bridge`, Scout 00 / `scout00`, the native scout, Scout Intake / `scout-intake`;
  - the Grok search bridge;
  - the tools `scout_intake`, `scout_item` and `native_signals`;
  - the `?item=` context.
- That covers Codex's examples (`PZ_ASSOCIATE.md` lines 15 and 39) and every other occurrence. A section left with
  no passage is left out whole.
- **Tests:**
  - No indexed passage matches the pattern list, and the list is checked against the raw documents: every retired
    mention found by a plain search is excluded.
  - The retrieved passages and the offline answer for "open the scout item link" (the old `?item=` flow) and for
    "where is Scout Intake?" name no retired page, tool or link. They are checked on the goldens and on the real
    corpus.
  - Every other passage is indexed unchanged. The BM25 ranking of the remaining corpus is compared with the old
    index restricted to the same passages, with 0 differences.

**2. Retention and concurrent asks.**
- **The tables:**
  - `associate_conversations (id, title, created_at, updated_at, message_count)`;
  - `associate_messages (conversation_id … on delete cascade, seq, role, body, created_at)`.
  - Messages are immutable to edits: a trigger rejects every UPDATE.
  - DELETE is allowed only through the store's two lifecycle operations, pruning and conversation deletion
    (including eviction). The trigger rejects a delete unless the transaction set
    `pz.associate_lifecycle = 'on'` (`set_config(..., true)`, local to that transaction), which only those operations
    do. A cascade from a conversation delete runs in the same transaction.
- **Phase 3 is serialized per conversation.** It takes the conversation row `FOR UPDATE`, appends the user and
  assistant messages, then prunes the oldest beyond 80, exactly as the old store truncated.
  - Creating a conversation (no id) first takes the Associate index lock (one advisory lock). It then evicts the
    oldest beyond 60 with their messages, and inserts.
  - The lock order is the index lock, then the conversation row. A delete takes the same row lock.
- **A conversation deleted or evicted during phase 2:** phase 3 finds no row and does NOT recreate it.
  - The ask returns 200 with the reply, `"saved": false` and the notice "This conversation was deleted while the
    answer was being prepared; the answer was not saved."
  - The page shows the reply and that notice.
  - The model's accounting stays recorded by the gateway.
- **Hosted tests:**
  - The 81st message prunes exactly the oldest: 80 kept, in order.
  - An explicit delete cascades its messages.
  - The 61st conversation evicts the oldest with its messages.
  - An UPDATE of a message is rejected, and so is a DELETE outside the lifecycle operations.
  - Two overlapping asks on one conversation, held at phase 3 by a test seam, both append in commit order with
    nothing lost or duplicated, and the pruning stays correct.
  - A delete during phase 2 gives `saved: false`, with the conversation not recreated.

**3. The write checks separate business data from accounting.**
- **Business tables** (every table except the Associate's and the gateway's `model_ledger`, `model_reservations` and
  `model_cache`) are digested around asks that, together, call EVERY tool. Several asks each stay within the 4-step
  limit and cover the whole registry. They must be unchanged.
- **A failed phase 3** (an injected failure after the appends) leaves the Associate tables unchanged: no partial turn.
- **Each dispatched attempt keeps its accounting:** one settled ledger row, or a reservation that reconciles to one
  `abandoned` row (the 029a rules). This holds for a successful ask and for a failed phase 3 alike.
- **Aliases:** an old candidate id (an absorbed inbox record, and a Scout-only record's old id) resolves through
  `candidate_detail` / `find_records` to the surviving Deal Flow record.

### H-314 revision 2 verdict

**APPROVE for implementation.** Passage filtering covers the retired instructions identified in H-313. Row locking, pruning and the unsaved-reply path define what happens when asks overlap or a conversation disappears. The rollback tests now distinguish conversation persistence from accounting for a dispatched attempt.

For the retention trigger, treat an unset lifecycle flag as off and exercise a direct delete on a fresh connection. When assigning message sequence numbers after pruning, use the highest retained sequence rather than the capped message count. Verify that a further append to an already-pruned conversation preserves order.

### Claude — implementation

**Domain** (`associate/`)
- **The engine, the tools, the docs index and the store caps:**
  - Cut by script with AST checks where pure (`parity_associate cuts`). The cuts are `knowledge` BM25, the tool
    helpers and `run`, the engine's constants, `FORBIDDEN`, `CLAIMS`, `_system`, `_validate`, `_history`, `_offline`,
    and the store caps.
  - The rest is hand-ported line for line.
- **`ask(...)` is pure.** The model call is injected (`ModelReply.of(gateway.complete(...))`), and so is the tool
  runner (`tools.runner(DbReader(...))`).
- **Each tool reads its own snapshot** through `DbReader`, over the new read models:
  - Today: `today.inputs.load` and `view`;
  - Conviction: `pipeline_view` and `case_view`;
  - Radar: `radar_of`. The Associate never credits the Radar.
  - Deal Flow: `inbox_view`, with old ids resolved through `DealFlowStore.resolve_id`;
  - Events: `events_payload`.
- **The docs corpus:** the 10 documents are byte-identical in `docs/associate/` (marked `-text`), and
  `SCOUT00_TRANSPORT.md` is dropped. The index leaves out every passage that `RETIRED` matches, and drops a section
  whose heading names a retired view. Sections are still what is ranked and cited, so nothing changes on screen.
- **Added after the build, under (c):** the old open-action allowlist contains `/`, so it lets every internal link
  through. `RETIRED_LINKS` now removes an open action to `/scout-intake`, `/scout-bridge` or `/native-scout`, and
  notes it like any unsupported action.
- **Budget:** `associate` has a per-purpose cap of 0.05 in `purpose_max_call_usd`.

**Store and routes**
- **Migration 0022:** `associate_conversations`, `associate_messages` and `associate_drafts`, plus the profile as
  the `documents` row `associate/profile.json`.
  - Messages and drafts are stored as `json`, because `jsonb` would reorder the old keys.
  - The messages' trigger refuses every UPDATE. It refuses a DELETE unless the transaction set
    `associate.lifecycle = 'on'`; an unset flag is off.
  - **Renamed during the build:** revision 2 named the flag `pz.associate_lifecycle`. The scratch schemas are made
    by rewriting the word `pz`, which rewrote the name inside the trigger, so it became `associate.lifecycle`.
- **`AssociateStore`:**
  - `save_turn` takes the conversation row `FOR UPDATE`. It appends after the HIGHEST retained `seq`, then prunes to
    80 messages.
  - Creating a conversation takes the index lock first, then evicts beyond 60.
  - A conversation that vanished mid-ask is never recreated.
  - Drafts are capped at 200, under their own lock.
- **`/api/associate/*` (9 routes), with the old bodies and answers.** The ask has three phases:
  - **phase 1:** a bounded read;
  - **phase 2:** the loop, with no transaction open while the model runs;
  - **phase 3:** one `bounded_transaction`, under a 240-second deadline for the whole ask.

  An ask that existed at the start but is gone at phase 3 answers the reply plus `saved: false` and the notice. An
  unknown id at phase 1 starts a new conversation, as before.

**Page** (`features/associate/`): a faithful port. The CSS and the Ardea assets are byte-identical.
- The `?item=` context is ignored.
- **One suggestion chip is reworded.** The old "How does Native Scout differ from Scout 00?" now reads "How does
  Deal Flow find and triage new candidates?".
- No link to a retired view is rendered.
- The unsaved notice shows under the reply, and the drawer never gets the conversation back.

**Declared differences** (all in `parity_associate.normalise`)
- **(c)** the Scout pages, tools, prefixes and the open actions to retired routes.
- **(d)** the Scout document.
- **The paid-switch reason in an offline text**, under 029a decision c: `(PZ_AI_PAID=off)` becomes
  `(PZ_AI_PAID is not 'on')`.
- **The merged Deal Flow population**, as the desk's (j) and H-309.
  - The Deal Flow tools list what the Deal Flow inbox lists. The merged-in Scout-only records are identified from
    `candidate_aliases`, never by name.
  - The remaining rows must equal the old rows in order, or be a prefix of them where a merged-in record took a place
    under the limit.

**For Mohamed (wording, not changed): data location.** The page says "Your conversations stay on this machine", and
the shell says "data stays local". Both are verbatim, but the data now lives in the hosted database. Rewording them
is a product decision.

**Verification (all pass)**
- **Goldens** (`parity_associate check`): 24 scripted cases plus the store cases, against the old `engine.ask` with
  the SAME scripted model outcomes: 0 differences.
- **Tools, hosted** (`parity_associate tools`): every listed tool call over the golden worlds, through the
  production importer and `DbReader`, against the oracle: 0 differences. Both old ids resolve to their survivor.
- **Real snapshot** (`parity_associate real`): 2,227 files and 1,485 aliases. 51 tool calls (49 compared, 2 through
  aliases) and 7 offline asks through the route, including both Scout questions: 0 differences besides the declared
  items.
  - Merged-in records removed per view: attention 34, watch 20, kept 1.
  - The 46 non-Associate tables are unchanged. Writes went only to the Associate tables and `model_ledger` (one
    `disabled` row per offline call, as the old gateway recorded).
- **Hosted** (`test_associate_hosted.py`, 9 tests):
  - the 81st message, then an append after pruning (the order is kept);
  - UPDATE and DELETE are refused on a fresh connection;
  - the cascade on delete, and eviction at 61 conversations;
  - asks covering all 10 tools, each within 4 steps, leave every business table unchanged;
  - a failed phase 3 leaves no partial turn, and the dispatched attempt keeps its accounting;
  - overlapping asks append whole turns in commit order;
  - a delete during phase 2 answers `saved: false`, and the conversation is not recreated;
  - offline mode; drafts need the confirmation.
- **PGlite:** the three new 0022 tests (immutability, the lifecycle flag local to its transaction, the id and role
  checks).
- **Backend unit:** 48 Associate tests, including the passage filter against the raw documents, the two Scout
  offline answers, and registry coverage.
- **Vitest:** 50 Associate tests.
- **E2e:** `associate-mocked.spec.ts` (11 tests) and `associate.spec.ts` (10 tests, on the preview database, offline,
  writing only `associate/*`).
- **Capture old vs new** (1366 and 1920, light and dark, 150 %): the same page. The one difference is the offline
  banner: paid calls are off here, while the old app's scratch copy runs a fake model.
- **Gate** (`scripts\check.ps1`): backend 1,858, frontend 876, PGlite: all pass.

## Codex implementation review

**REQUEST CHANGES (H-316).**

1. Enforce the 240-second deadline across the whole ask. In `post_ask`, only the gateway receives `done_by`. The tool reader opens snapshots without the ask deadline, and the final save starts a fresh 30-second window. A slow tool can therefore run past expiry and the route can still append the turn. Bound tool reads and the save by the remaining request time, including lock waits. Add a route test that exhausts the budget during a tool read and verifies that no further model call or partial turn follows and that a dispatched attempt keeps its accounting.
2. Correct the privacy wording before release. The conversation list promises on-device storage and the top bar says “data stays local.” Conversations are saved in the Project Zero database. When model access is enabled, the configured provider receives the context used to answer. Use those facts in the UI, update the two empty-state assertions, and filter or correct the same claims in the searchable manual and product notes so offline answers agree with the UI.

I reran all 48 backend Associate unit tests successfully. The hosted, browser and full-suite results above are Claude’s reported runs.

### Claude — implementation revision 2 (H-317)

Both of Codex's points are taken.

**1. ONE deadline bounds the whole ask** (`done_by` = 240 s from the request).
- **Phase 1** reads under `min(done_by, now + 30 s)`. **Phase 3** saves under `done_by` itself: the ask's time left,
  never a fresh window.
- **Every tool read is bounded.** `DbReader(..., done_by=, clock=)` reads each tool's snapshot through a
  `bounded_transaction` with the ask's deadline: the connect, the lock and statement waits, and a read still running
  at the deadline are all cut. Inside it, `set transaction isolation level repeatable read, read only` runs before
  any query.
- **The route checks the deadline around the engine.** The tools report a failed source as data (the verbatim
  `run()`), so the route's `run_tool` checks the deadline before AND after each read. `call_model` checks it before
  each model call.
  - Past the deadline the route raises `AskExpired`, which the engine does not catch.
  - The ask then answers 503 "the answer took longer than the time allowed; nothing was saved": there is no further
    model call, no tool read and no save.
  - The gateway still gets `deadline=done_by`.
- **Regression** (hosted, `test_the_ask_deadline_cut_during_a_tool_read_ends_the_ask_with_nothing_saved`): a fake
  monotonic clock jumps 300 s inside the `today_missions` read, so the read's bounded snapshot is refused. The test
  checks four things:
  - the answer is 503;
  - `FakeProvider.dispatches == 1`, so no model call follows;
  - the Associate tables are unchanged, so there is no partial turn;
  - exactly one ledger row or reservation was added for the dispatched attempt.

**2. The privacy wording now states the facts.**
- **The UI:**
  - the top bar reads "data in your Project Zero database";
  - the empty conversation list reads "Nothing yet. Your conversations are saved in the Project Zero database.";
  - the draft confirmation reads "Saved only to your PZ Associate drafts in the Project Zero database. It is not sent
    to anyone and changes no record.";
  - the input hint reads "Read-only: nothing in Project Zero is changed. With paid model access on, your question and
    the records used to answer go to the configured model provider."
  - The two empty-state assertions and the hint and draft assertions are updated.
- **The searchable help.** The documents stay byte-identical; `knowledge.CORRECTIONS` rewrites their local-data
  claims at index time, for both sides of the parity:
  - "all data stays local" in the product overview;
  - "data stays local" in the user manual's top-bar line;
  - "Conversations are kept locally" in the PZ Associate notes.
  - The new `tests/associate/test_associate_privacy.py` checks that no indexed passage matches `LOCAL_CLAIM` and that
    each claim is corrected rather than dropped. The goldens are regenerated (MATCH).
- **Left as written, because they are true:** "remembered on this computer" for the theme and focus mode, which are
  browser storage.
- **Noted for 032c:** `CatchUpBanner` ("Project Zero runs on your computer …") belongs to the background-jobs runner
  and is reworded when that runner is ported.

**Re-run, all pass:**
- the goldens (MATCH);
- `tools` (MATCH);
- `real` (MATCH: 0 differences besides the declared items, 7 asks with the paid-switch reason declared);
- the Associate hosted tests (10, with the deadline case) and unit tests (51);
- 21 e2e tests;
- the gate: backend 1,861, frontend 876, PGlite.

## H-318 implementation verdict

**APPROVE revision 2.** The route passes the same absolute deadline to the gateway, each read-only tool snapshot and the final save. The transaction helper limits lock and statement waits and checks expiry before commit. The hosted regression advances the clock before the tool opens its snapshot and checks the 503 response, one dispatch, unchanged conversation tables and retained accounting.

The UI identifies database storage and discloses provider access when paid calls are enabled. The search index corrects all three legacy local-storage claims. I reran all 51 Associate unit tests successfully and inspected the hosted regression. Claude reports the hosted, browser and full-suite runs in H-318.

## Grok notes
