/**
 * The PZ Associate payloads (review 033a): the old `services/associate` answers, field for field, under the new
 * `associate/*` paths. Only the fields the page reads are typed; the rest (a message's `usd` and `model`, a draft's
 * `ref` and `conversation_id`, the status `max_steps` and `docs_missing`) pass through unread.
 */

/** Ardea's four restrained states (components/Ardea). */
export type ArdeaState = "ready" | "thinking" | "done" | "uncertain";

/** A record reference the tools returned (grounded): `kind:id`, its label and, when it has a page, its in-app link. */
export type Ref = { kind: string; id: string; label: string; link?: string };

/** What an answer offers: open an in-app page, or save the answer as a draft (only after the confirmation Modal). */
export type Action = { kind: "open" | "save_draft"; label: string; link?: string; title?: string };

export type Msg = {
  role: "user" | "assistant";
  at: string;
  text: string;
  context?: Record<string, string> | null;
  /** the tool trace: each read tool the model called this turn, and whether it answered */
  tools?: Array<{ tool: string; ok: boolean }>;
  /** "<doc> › <section>" the answer relied on */
  docs?: string[];
  sources?: Ref[];
  focus?: Ref[];
  actions?: Action[];
  notes?: string[];
  mode?: "model" | "offline";
};

export type Conversation = { id: string; title: string; updated?: string; messages: Msg[] };
export type ConvRow = { id: string; title: string; updated?: string };
export type Conversations = { conversations: ConvRow[] };

export type Status = {
  role: string;
  kill_switch: string | null;
  model: { ready?: boolean; problem?: string | null; model?: string };
  docs_indexed: number;
  tools: Array<{ name: string; purpose: string }>;
};

/**
 * One answer. `saved: false` (revision 2): the conversation was deleted or evicted while the answer was being prepared,
 * so the server did NOT store this turn and did not recreate the conversation; `notice` says so. Absent means saved.
 */
export type AskRes = { conversation: { id: string; title: string } | null; message: Msg; saved?: boolean; notice?: string };
export type AskBody = { message: string; conversation_id?: string | null; context?: Record<string, string> | null };

export type Draft = { id: string; title: string; body: string; created: string };
export type Drafts = { drafts: Draft[] };
export type DraftBody = { title: string; body: string; ref?: Ref; conversation_id: string | null; confirm: true };

export type Profile = { profile: Record<string, string | null>; fields: Array<{ key: string; label: string }> };
