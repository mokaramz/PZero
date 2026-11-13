/** Display helpers of the System health page (ported from the old `HealthPage.tsx`). */

/** A payload timestamp as the old page showed it ("13 Nov, 09:30" by default), or "—". */
export const fmt = (iso?: string | null, o: Intl.DateTimeFormatOptions = { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) =>
  iso ? new Date(String(iso).replace(" ", "T")).toLocaleString("en-GB", o) : "—";

/** A model error kind in plain words. Old texts kept, except the two that promised a retry: no runner retries an
 *  item until the background-job runner is ported (revision 2; the old "… the item was kept for retry" and
 *  "… retried later"). */
export const ERR_KIND: Record<string, string> = {
  invalid: "the model's answer failed validation; the item was kept",
  rate_limited: "the provider asked to slow down",
  malformed: "the answer could not be parsed",
  bad_request: "the provider rejected the request",
  timeout: "no answer in time",
  budget_blocked: "stopped by a spending cap — caps are never overridden",
};
