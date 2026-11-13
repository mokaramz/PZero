/**
 * The PZ Associate endpoints (review 033a) — the ONE place their paths live. New paths, the old bodies and answers:
 *
 * - `GET associate/status` → the role, the kill switch, the model's readiness, the docs indexed and the tool catalogue;
 * - `POST associate/ask {message, conversation_id?, context?: {company|candidate}}` → `{conversation, message}`, plus
 *   `saved: false` and a `notice` when the conversation was deleted while the answer was prepared (revision 2);
 * - `GET associate/conversations`, `GET associate/conversation?id=`, `POST associate/conversation_delete {id}`;
 * - `GET associate/profile` (the six fields) and `POST associate/profile` (their values);
 * - `GET associate/drafts`, `POST associate/draft {title, body, ref?, conversation_id?, confirm: true}` (sent only from
 *   the confirmation Modal) and `POST associate/draft_delete {id}`.
 *
 * Every write here touches the Associate's own store only, so each invalidates only the Associate's own keys.
 */
import { useApi } from "@/lib/hooks";
import type { Conversation, Conversations, Drafts, Profile, Status } from "./model/types";

export const ASSOCIATE = {
  status: "associate/status",
  ask: "associate/ask",
  conversations: "associate/conversations",
  conversation: "associate/conversation",
  conversationDelete: "associate/conversation_delete",
  profile: "associate/profile",
  drafts: "associate/drafts",
  draft: "associate/draft",
  draftDelete: "associate/draft_delete",
} as const;

export const useStatus = () => useApi<Status>(ASSOCIATE.status);
export const useConversations = () => useApi<Conversations>(ASSOCIATE.conversations);
export const useConversation = (id: string | null) => useApi<Conversation>(ASSOCIATE.conversation, { id: id ?? "" }, { enabled: !!id });
export const useProfile = (open: boolean) => useApi<Profile>(ASSOCIATE.profile, undefined, { enabled: open });
export const useDrafts = (open: boolean) => useApi<Drafts>(ASSOCIATE.drafts, undefined, { enabled: open });
