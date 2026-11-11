import { useSyncExternalStore } from "react";

/* ================================================================== client action store
 * Every operator action in flight (acknowledged the moment it is clicked) and the outcome of the last few. Read by the
 * Background activity dock on every page. Module state, no provider needed. */

export type ActionState = "RUNNING" | "COMPLETE" | "PARTIAL" | "FAILED";
export type ActionItem = { id: number; label: string; state: ActionState; detail?: string; at: number };

const KEEP_MS = 60_000; // a routine success stays a minute
const KEEP_PROBLEM_MS = 10 * 60_000; // failures / partials stay 10 minutes unless dismissed
const MAX_KEPT = 12;

let items: ActionItem[] = [];
let seq = 0;
const subscribers = new Set<() => void>();

function emit() {
  items = [...items];
  subscribers.forEach((notify) => notify());
}

function isFresh(x: ActionItem): boolean {
  return x.state === "RUNNING" || Date.now() - x.at < (x.state === "COMPLETE" ? KEEP_MS : KEEP_PROBLEM_MS);
}

export const actions = {
  start(label: string): number {
    const id = ++seq;
    items = [...items.filter(isFresh).slice(-MAX_KEPT), { id, label, state: "RUNNING", at: Date.now() }];
    emit();
    return id;
  },
  finish(id: number, state: Exclude<ActionState, "RUNNING">, detail?: string) {
    items = items.map((x) => (x.id === id ? { ...x, state, detail, at: Date.now() } : x));
    emit();
    window.setTimeout(emit, (state === "COMPLETE" ? KEEP_MS : KEEP_PROBLEM_MS) + 50); // age out of the dock
  },
  dismiss(id: number) {
    items = items.filter((x) => x.id !== id);
    emit();
  },
};

function subscribe(notify: () => void) {
  subscribers.add(notify);
  return () => {
    subscribers.delete(notify);
  };
}

export function useClientActions(): ActionItem[] {
  return useSyncExternalStore(subscribe, () => items).filter(isFresh);
}

/* ================================================================== action labels */

/** "news_refresh" → "Refreshing news". Verbs Mohamed sees the instant he clicks (never developer wording). */
export const ACTION_LABEL: Record<string, string> = {
  news_refresh: "Refreshing news",
  news_outcome: "Recording the outcome",
  news_audit_miss: "Creating the miss audit",
  news_backcast: "Adding the early signal",
  news_sources_evaluate: "Re-measuring news sources",
  find: "Scanning sources",
  decide: "Saving your decision",
  triage: "Saving your triage decision",
  analyze: "Analyzing",
  analysis_submit: "Saving the analysis",
  batch_preview: "Preparing the batch",
  batch_start: "Starting batch analysis",
  analyst_shadow_run: "Starting the shadow analyst",
  red_team_run: "Running Red Team",
  reviewer_run: "Running the independent reviewer",
  reviewer_request: "Requesting a review",
  backup: "Creating backup",
  backup_restore_test: "Testing backup",
  integrity_repair: "Repairing",
  catchup_run: "Running overdue jobs",
  source_network_run: "Looking for new sources",
  source_decision: "Saving the source decision",
  source_candidate: "Adding the source candidate",
  source_toggle: "Switching the source",
  scout_preview: "Reading packet",
  scout_import: "Importing packet",
  scout_action: "Saving the Scout decision",
  scout_event: "Saving the Scout event",
  scout_feedback: "Saving feedback",
  scout_brief: "Saving the brief",
  sourcing_day: "Building plan",
  weekend: "Building weekend plan",
  event_find: "Searching for events",
  event_verify: "Checking the event",
  event_save: "Saving the event",
  event_lead: "Saving the lead",
  event_debrief: "Saving the debrief",
  radar_scan: "Scanning founders",
  radar_research: "Starting founder research",
  radar_import: "Importing",
  radar_promote: "Promoting",
  radar_review: "Saving the review",
  radar_pair: "Pairing",
  radar_action: "Saving",
  radar_company: "Saving the company link",
  research_run: "Checking evidence",
  verification_decide: "Applying verification",
  registry_lookup: "Looking up the official register",
  registry_paste: "Reading the register extract",
  registry_link: "Linking the register record",
  identity_review: "Saving the identity decision",
  watch_check: "Checking watched pages",
  watch_target: "Saving watched pages",
  watch_ack: "Acknowledging",
  watch_log: "Logging the signal",
  validation_outcome: "Recording the outcome",
  validation_audit: "Recording the audit",
  validation_retract: "Retracting",
  validation_scout_packet: "Preparing the Scout 00 packet",
  validation_benchmark_import: "Importing benchmark",
  imq_trigger: "Recording the why-now trigger",
  case_prepare: "Preparing the case",
  outreach_log: "Recording founder contact",
  case_reviewer: "Asking the independent Reviewer",
  case_committee: "Convening the Investment Committee",
  case_committee_request: "Asking the committee to look",
  case_external_job: "Creating the external research job",
  eval_start: "Starting the evaluator",
  bridge_create: "Creating research job",
  bridge_response: "Reading the response",
  bridge_action: "Saving",
  coverage_adopt: "Adopting the source",
  call_save: "Saving the call",
  call_followup: "Saving the follow-up",
  person_save: "Saving the person",
  omar_mark: "Recording Manager's feedback",
  weekly: "Preparing the weekly update",
  content_save: "Saving",
  content_delete: "Deleting",
};

export const labelFor = (path: string) => ACTION_LABEL[path] ?? "Working";

/* ================================================================== plain-language errors */

/** Plain-English failure text (no stack traces / status codes as the headline). */
export function friendlyError(message: string, status?: number): string {
  let m = message || "";
  // a provider / server payload must never be shown raw: keep only its human message
  const j = m.indexOf("{");
  if (j >= 0) {
    try {
      const body = JSON.parse(m.slice(j)) as { error?: { message?: string; code?: string } | string; detail?: string };
      const e = typeof body.error === "string" ? body.error : body.error?.message || body.detail;
      if (e) m = `${m.slice(0, j).replace(/[:\s]+$/, "")} ${e}`.trim();
    } catch {
      m = m.slice(0, j).trim() || "unexpected reply";
    }
  }
  if (/engine_overloaded|model busy|overloaded/i.test(m)) return "The AI provider is temporarily overloaded — the work was kept and will be retried. No data was lost.";
  m = m.replace(/Traceback[\s\S]*/i, "").replace(/\b[A-Z][A-Za-z]+(Error|Exception): /g, "");
  if (status === 429 || /\b429\b|rate.?limit/i.test(m)) return "The provider rate-limited us — Project Zero will retry later. No data was lost.";
  if (/budget|cap reached|kill switch/i.test(m)) return `Stopped by the AI budget cap — nothing was changed. (${m})`;
  if (/failed to fetch|networkerror|load failed/i.test(m)) return "Project Zero's local server did not answer — is the app still running? Nothing was changed.";
  if (/timed? ?out|timeout/i.test(m)) return "It took too long and was stopped — nothing was changed. You can retry.";
  if (status && status >= 500) return `Something failed inside Project Zero — your data was not changed. (${m.slice(0, 120)})`;
  return m;
}

/** Any backend / provider error text as Mohamed may read it (empty stays empty). */
export const plainText = (s?: string | null): string => (s ? friendlyError(String(s)) : "");

/** Why a source / feed could not be fetched, in plain words (shared by Deal Flow scans and News feeds). */
export function plainSourceProblem(err: string): string {
  const e = err || "";
  if (/no longer offers|became a web app|external change/i.test(e)) return "the site changed (external) — this source needs a new data path";
  if (/fetched but no|no commercial participants/i.test(e)) return "fetched, but no usable companies in it — needs a parser check";
  if (/\b429\b|rate.?limit|too many/i.test(e)) return "asked us to slow down (rate limit) — retried next time";
  if (/\b40[13]\b|forbidden|refuses automated/i.test(e)) return "refused automated access — not bypassed";
  if (/\b404\b|not found/i.test(e)) return "page / feed address not found (moved?)";
  if (/\b5\d\d\b/.test(e)) return "the publisher's server had an error";
  if (/getaddrinfo|Name or service|\bDNS\b|could not resolve|failed to resolve|11001/i.test(e)) return "address could not be found (DNS)";
  if (/timed? ?out|timeout|deadline|\b408\b/i.test(e)) return "did not answer in time";
  if (/connection (reset|aborted|refused)|remote ?end closed|RemoteDisconnected/i.test(e)) return "dropped the connection — retried next time";
  if (/javascript|js-only|script-rendered/i.test(e)) return "the page only renders in a browser (JavaScript) — needs a different data path";
  if (/empty (response|page|body)/i.test(e)) return "answered with an empty page — retried next time";
  if (/ParseError|not well-formed|junk|layout|parse|no (items|results)/i.test(e)) return "page layout / feed format changed — needs a parser check";
  if (/SSL|certificate/i.test(e)) return "secure connection could not be established";
  return "could not be fetched";
}
