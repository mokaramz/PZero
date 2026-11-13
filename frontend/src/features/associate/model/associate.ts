/**
 * The PZ Associate page's pure logic (review 033a), ported from the old `AssociatePage.tsx`: the suggested questions,
 * the page context read from the URL, Ardea's state for an answer, the offline banner's reason, the tool trace and the
 * in-app links an answer may carry.
 *
 * Changes (decision c): the `?item=` context (a Scout Intake item) is gone, and so is the Scout suggestion; a link to a
 * retired view (Scout Intake, its native-scout tab, Scout Bridge) is never rendered as a link.
 */
import type { ArdeaState, Msg, Status } from "./types";

/** The six suggestion chips. The old "How does Native Scout differ from Scout 00?" named two retired views: it asks
 *  about Deal Flow, which absorbed them, instead. */
export const SUGGESTIONS = [
  "What should I focus on today?",
  "Which Conviction companies are waiting on a Manager decision?",
  "How does Deal Flow find and triage new candidates?",
  "Explain how a company reaches Radar.",
  "Show me the strongest Deal Flow candidates this week.",
  "Which events are coming up?",
] as const;

/** The record a question is about, from the page that sent it (Conviction → `?company=`, Deal Flow → `?candidate=`). */
export const CONTEXT_KEYS = ["company", "candidate"] as const;
export const CONTEXT_LABEL: Record<(typeof CONTEXT_KEYS)[number], string> = { company: "Company", candidate: "Deal Flow candidate" };

export type Context = { key: (typeof CONTEXT_KEYS)[number]; value: string };

/** The first context parameter present, in the old order; anything else (the retired `?item=`) is ignored. */
export function readContext(params: URLSearchParams): Context | null {
  for (const key of CONTEXT_KEYS) {
    const value = params.get(key);
    if (value) return { key, value };
  }
  return null;
}

/** The body's `context`, as the old page sent it (`{company: "<slug>"}`), or null. */
export const contextBody = (c: Context | null): Record<string, string> | null => (c ? { [c.key]: c.value } : null);

/** Ardea after an answer: uncertain when it came from the documentation only, or a note says something was dropped. */
export function stateFor(m: Msg): ArdeaState {
  if (m.mode === "offline" || (m.notes ?? []).some((n) => /uncited|not found|unsupported/.test(n))) return "uncertain";
  return "done";
}

/** The header avatar: thinking while a question is out, else the latest answer's state, else ready. */
export function headerState(pending: boolean, lastAssistant: Msg | undefined): ArdeaState {
  if (pending) return "thinking";
  return lastAssistant ? stateFor(lastAssistant) : "ready";
}

/** "Nov 13, 09:30" in the viewer's locale; "" for a missing or unreadable timestamp. */
export function when(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The offline banner: shown when paid AI is switched off or no model is ready (never before the status arrives). */
export const isOffline = (st: Status | undefined): boolean => (st ? !!st.kill_switch || !st.model?.ready : false);

export function offlineReason(st: Status | undefined): string {
  return st?.kill_switch ? "paid AI is switched off" : st?.model?.problem || "no model is configured";
}

/** The tool trace in words: `company_detail` → "company detail". */
export const toolsUsed = (m: Msg): string[] => (m.tools ?? []).map((t) => t.tool.replace(/_/g, " "));

/** Views retired with the Deal Flow merge: Scout Intake (and its native-scout tab) and Scout Bridge. */
const RETIRED = /^\/(scout-intake|scout-bridge)(?=[/?#]|$)/i;

/** An in-app link the page may render: internal ("/…", never "//…") and not a retired view. Anything else → null. */
export function inAppLink(link: string | undefined | null): string | null {
  if (!link || !link.startsWith("/") || link.startsWith("//")) return null;
  return RETIRED.test(link) ? null : link;
}

export const isRetiredLink = (href: string): boolean => RETIRED.test(href);

/** The last assistant message (the one whose state the header shows). */
export const lastAssistantOf = (messages: Msg[]): Msg | undefined => [...messages].reverse().find((m) => m.role === "assistant");

/** Shown when the server answers `saved: false` without its own notice (it always sends one; this is a fallback). */
export const UNSAVED_NOTICE = "This conversation was deleted while the answer was being prepared; the answer was not saved.";
