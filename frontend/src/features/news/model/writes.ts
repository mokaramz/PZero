/**
 * The News writes' pure logic (review 028b), ported from the old `features/news/NewsPage.tsx`: the bodies the three
 * decision controls post, the early-signal form (its shape, the rule that enables "Add", its options), the answers and
 * the old toasts. Rendering stays in ../components; the endpoints in ../api.
 */

/* ------------------------------------------------------------------ the outcome proposal */

export type Decision = "confirm" | "reject" | "not_enough";
/** The old `news_outcome` body. */
export type OutcomeBody = { event_id: string; decision: Decision };
export const outcomeBody = (eventId: string, decision: Decision): OutcomeBody => ({ event_id: eventId, decision });

/** The old answer: the appended action line (`outcome_id` only for a confirm). Once the latest decision for the event is
 *  a confirm, any next decision answers that confirmation with `already: true` and writes nothing — the page treats it
 *  like any other success, as before. */
export type OutcomeAnswer = {
  ok: true;
  already?: true;
  kind: "outcome_decision";
  event_id: string;
  decision: Decision;
  at: string;
  outcome_id?: string;
};

/** What "Confirm outcome" asks on its first click (the old `confirmText`). */
export const CONFIRM_TEXT = "records a verified outcome in Validation";

/** Which decisions also write a Validation row: only a confirm records an outcome. */
export const writesValidation = (d: Decision) => d === "confirm";

/* ------------------------------------------------------------------ the miss audit */

/** The old page sent the event alone; the server prefills the audit from what News knows. */
export type AuditMissBody = { event_id: string };
export const auditMissBody = (eventId: string): AuditMissBody => ({
  event_id: eventId,
});
export type AuditMissAnswer = {
  ok: true;
  audit: Record<string, unknown> & { id: string };
};

/* ------------------------------------------------------------------ the early signal */

/** The old form, in its key order (the posted body is the form, then `event_id`). */
export type SignalFields = {
  date: string;
  text: string;
  url: string;
  family: string;
  kind: SignalKindValue;
};
export type SignalKindValue = "known_early_signal" | "in_retrospect";
export const SIGNAL_FORM: SignalFields = {
  date: "",
  text: "",
  url: "",
  family: "university_lab",
  kind: "known_early_signal",
};

/** "Add" needs a date and a URL that starts with "http" (the old check; the server checks the rest). */
export const signalReady = (f: SignalFields) => !!f.date && f.url.startsWith("http");
export type SignalBody = SignalFields & { event_id: string };
export const signalBody = (f: SignalFields, eventId: string): SignalBody => ({
  ...f,
  event_id: eventId,
});
export type SignalAnswer = {
  ok: true;
  signal: {
    date: string;
    precision: string;
    text: string;
    family: string;
    url: string;
    kind: SignalKindValue;
    added_by: string;
    added_at: string;
  };
};

export const familyLabel = (family: string) => family.replace(/_/g, " ");
export const SIGNAL_KINDS: Array<{ value: SignalKindValue; label: string }> = [
  { value: "known_early_signal", label: "Yes — a known early signal" },
  { value: "in_retrospect", label: "No — only clear in retrospect" },
];
export const SIGNAL_HELP =
  "A public signal that existed BEFORE the story, with its source. Mark honestly whether it was knowable then, or only important in hindsight.";

/* ------------------------------------------------------------------ the old toasts and activity labels */

export const SUCCESS = {
  outcome: "Recorded",
  audit: "Miss audit created in Validation (prefilled)",
  signal: "Signal added to the backcast",
} as const;

/** The old action labels (Background activity and the "✕ … failed" toast). */
export const LABEL = {
  outcome: "Recording the outcome",
  audit: "Creating the miss audit",
  signal: "Adding the early signal",
} as const;
