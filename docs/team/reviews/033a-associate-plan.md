# 033a — Plan: the PZ Associate (the agent, its read tools and the page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-315) — implementation next

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

## Grok notes
