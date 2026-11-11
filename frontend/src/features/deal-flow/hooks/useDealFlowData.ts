import { isMissingEndpoint } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { TriagePayload } from "../model/triage";
import type { InboxPayload } from "../model/types";

export const INBOX = "deal-flow/inbox";
export const TRIAGE = "deal-flow/triage";
/** `useApi` keys a GET as `[path, query ?? {}]`. */
export const INBOX_KEY = [INBOX, {}] as const;

/** The whole Deal Flow in one read (≈ 1 MB): the page ranks it on the client, so it stays fresh for a minute. */
export function useInbox() {
  return useApi<InboxPayload>(INBOX, undefined, { staleTime: 60_000 });
}

/** The machine-triage proposals. A missing endpoint or an empty payload means "no proposals": the list then behaves
 *  exactly as it does without triage records. */
export function useTriage() {
  const q = useApi<TriagePayload>(TRIAGE, undefined, { staleTime: 60_000, retry: (n, e) => !isMissingEndpoint(e) && n < 1 });
  return { data: q.data, proposals: q.data?.proposals };
}
