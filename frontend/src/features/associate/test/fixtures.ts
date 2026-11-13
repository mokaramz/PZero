/**
 * The PZ Associate test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/associate/`, byte-identical copies). The shapes are the old `services/associate` answers under
 * the new paths (review 033a), with no Scout tool, page or link (decision c):
 * - `status_offline.json`: paid AI switched off and no key — the offline banner; `status_ready.json`: a ready model;
 * - `conversations.json`: two saved conversations, newest first;
 * - `conversation.json`: the first one — a question and a model answer with every part: three tool calls (one failed),
 *   a linked and an unlinked source, a documentation section, an open and a save_draft action, two notes, Markdown
 *   with an internal and an external link;
 * - `ask_offline.json`: an offline answer from the documentation (a new conversation);
 * - `ask_unsaved.json`: an answer the server could not save (`saved: false` and its notice, revision 2);
 * - `profile.json`: the six profile fields, three filled; `drafts.json`: two drafts, newest first.
 */
import type { AskRes, Conversation, Conversations, Drafts, Profile, Status } from "../model/types";
import askOfflineJson from "./ask_offline.json";
import askUnsavedJson from "./ask_unsaved.json";
import conversationJson from "./conversation.json";
import conversationsJson from "./conversations.json";
import draftsJson from "./drafts.json";
import profileJson from "./profile.json";
import statusOfflineJson from "./status_offline.json";
import statusReadyJson from "./status_ready.json";

export const statusOffline = (): Status => structuredClone(statusOfflineJson) as unknown as Status;
export const statusReady = (): Status => structuredClone(statusReadyJson) as unknown as Status;
export const conversations = (): Conversations => structuredClone(conversationsJson) as unknown as Conversations;
export const conversation = (): Conversation => structuredClone(conversationJson) as unknown as Conversation;
export const askOffline = (): AskRes => structuredClone(askOfflineJson) as unknown as AskRes;
export const askUnsaved = (): AskRes => structuredClone(askUnsavedJson) as unknown as AskRes;
export const profile = (): Profile => structuredClone(profileJson) as unknown as Profile;
export const drafts = (): Drafts => structuredClone(draftsJson) as unknown as Drafts;

/** The second saved conversation (opened from the drawer in the tests). */
export const radarConversation = (): Conversation => ({
  id: "c-1f2e3d4c5b6a",
  title: "Explain how a company reaches Radar.",
  updated: "2026-11-10T08:05:00Z",
  messages: [
    { role: "user", at: "2026-11-10T08:04:30Z", text: "Explain how a company reaches Radar." },
    { ...askUnsaved().message, at: "2026-11-10T08:05:00Z" },
  ],
});
