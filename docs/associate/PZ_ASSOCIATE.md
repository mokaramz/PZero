# PZ Associate

PZ Associate is a conversational operating associate inside Project Zero (left rail → **PZ Associate**, or `/associate`).
It explains how Project Zero works, looks up records, and prepares drafts and questions. **It is read-only.** It never
sends a message, contacts a founder or the Manager, approves, scores, promotes to Radar, resolves a conflict, or changes
any record, schedule, budget or methodology. Every action stays with the Smooth Operator.

Its character is **Ardea**, a grey heron. A heron stands still in the river and strikes only when it is sure:
patience, discernment and selectivity, which is how Project Zero sources.

## What it can do

| Category | What | How it is enforced |
|---|---|---|
| READ | Explain PZ from the documentation; read Today, Conviction (companies, cases, Manager decisions), Deal Flow candidates, Scout Intake items, Native Scout signals, Radar, upcoming events; find a record by name | A closed list of 13 read-only tools that call the existing page endpoints. No SQL, no shell, no file access, no write tool exists. Arguments are validated; unknown tools are rejected. |
| PREPARE | Drafts (call questions, briefing notes, an email you will send yourself) | Saved only to the Associate's own folder (`<data>/associate/drafts.json`), and only after you confirm in a dialog. The server refuses a draft without `confirm: true`. Nothing is sent. |
| GUIDE | "Open the case" style links | Only internal PZ page links are allowed; anything else the model proposes is removed and noted. |
| EXECUTE | None | Not available by design. Requests to email, approve, score or contact the Manager are answered with a prepared draft and a note: *kept with you*. |

## Grounding and safety

- **Sources are verified on the server.** A source is shown only if a tool actually returned that record in this
  conversation (or it is the record you opened the Associate from). Invented references are removed, and the answer
  says so ("uncited reference removed").
- **Records are data, never instructions.** Every tool result reaches the model inside an `<untrusted_records>`
  envelope with an explicit rule to ignore instructions inside it. A record saying "approve this company" changes
  nothing: no tool can approve.
- **Claims of action are corrected.** If an answer says it sent, approved or changed something, a note is appended
  that the Associate is read-only and did nothing.
- **Bounded.** At most 4 model calls per question (3 tool calls plus the answer); results are truncated; there are no
  background loops.
- **Honest when unavailable.** If no model is configured, the paid-AI kill switch is on, or the model fails, the
  Associate says so and answers from the documentation only (marked *Documentation only*).

## Context

- **From Conviction:** company **Actions → Ask PZ Associate** opens the Associate about that company
  (`/associate?company=<slug>`). The id is checked on the server; an unknown id is ignored and noted.
  `?candidate=<id>` (Deal Flow) and `?item=<id>` (Scout Intake) work the same way.
- **From anywhere:** Ctrl+K, type a question, choose **Ask PZ Associate**.
- **Follow-ups** ("the second one") use the conversation's own history. Conversations are kept locally, at most 60
  conversations of 80 turns each.
- **Your context** (header button): your interests, sourcing priorities, quality standards, routines, output
  preferences and boundaries. The Associate reads these as preferences; they never change PZ's methodology, scoring
  or schedules.

## Configuration

In `config.json` (optional):

```json
"associate": { "role": "CHEAP", "max_steps": 4 }
```

- `role`: `CHEAP` (default, DeepSeek V4 Flash) or `STANDARD` (V4 Pro), the same inference roles as the rest of PZ.
- `max_steps`: 1–4 model calls per question (4 is the ceiling; lower is cheaper).

Cost: the Associate uses the existing inference gateway, so it shares PZ's daily and monthly budget, ledger and kill
switch (`PZ_AI_PAID=off`). Its calls are logged with purpose `associate`. On CHEAP a typical question costs well under
a cent; it defaults to CHEAP so it never starves triage of budget.

## Where things live

- Backend: `backend/src/projectzero/services/associate/` (`tools.py` read-only tools, `engine.py` the turn loop and
  guards, `knowledge.py` the documentation index, `store.py` conversations, profile and drafts) and
  `api/routers/associate.py`.
- Frontend: `frontend/src/features/associate/` (`AssociatePage.tsx`, `Ardea.tsx` the character, `Markdown.tsx` a safe
  renderer).
- Character assets: `frontend/src/assets/associate/` (`ardea-illustration.svg`, `ardea-avatar-{ready,thinking,done,uncertain}.svg`,
  `ardea-mark.svg`), regenerated from the components with `node frontend/scripts/export-ardea.mjs`.
- Data: `<data>/associate/` only. The Associate never writes anywhere else.

## Not yet (deferred)

- Write actions of any kind (even with confirmation): status changes, logging calls, scheduling.
- Contextual launchers on the frozen pages (Investment Desk, Today, Deal Flow).
- Streaming answers; semantic (vector) search over documents and notes.
- A separate budget line for the Associate.
