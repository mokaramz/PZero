/** The WATCH panel's pure rules (the old `WatchedCompanies` / `TriggerList` / `WatchSection`, review 037a). */
import type { Tone } from "@/components/ui";
import type { PageCheck, Trigger, WatchPayload, WatchedCompany } from "./types";

/**
 * Why "Check now" is visible but does nothing yet: the two sensors (scan re-hits and official-page diffs) arrive in
 * review 037b. ONE wording, on the Watchlist and on the Deal Flow WATCH section.
 */
export const PAGE_CHECKS_DEFERRED = "Page checks arrive with the WATCH sensors port";

/** The textarea's pages, split on any whitespace (the old rule; the server keeps the first 6 and checks each). */
export const splitUrls = (text: string): string[] => text.split(/\s+/).filter(Boolean);

/** A decided trigger is neutral; an open one is red when high-value, amber otherwise. */
export const triggerTone = (t: Pick<Trigger, "status" | "high_value">): Tone => (t.status !== "new" ? "neutral" : t.high_value ? "red" : "amber");

/**
 * Where a trigger came from. Kept as the old app wrote it (decision e): anything that is not a scan re-hit is "page
 * check" — news triggers too, revisited in 037b once news triggers exist.
 */
export const triggerSource = (t: Pick<Trigger, "source_kind">): string => (t.source_kind === "scan_rehit" ? "new source in a scan" : "page check");

/** The evidence as the list shows it (its first 160 characters). */
export const evidenceText = (t: Pick<Trigger, "evidence">): string => (t.evidence ?? "").slice(0, 160);

/** "{url}: {state} · {checked} · {n} failure(s) in a row: {error}" — one watched page's last check. */
export function checkLine(url: string, k: PageCheck): string {
  return (
    `${url}: ${k.last_state || "not checked"} ${k.last_checked ? `· ${k.last_checked}` : ""}` +
    (k.failures_in_row ? ` · ${k.failures_in_row} failure(s) in a row: ${k.last_error || ""}` : "")
  );
}

/** The Deal Flow section's summary line. */
export const pagesLine = (c: Pick<WatchedCompany, "urls">): string =>
  c.urls.length ? `${c.urls.length} official page(s) watched` : "No official pages attached yet — scans still watch for new sources";

/** The watched company of a Deal Flow candidate, if the view lists it. */
export const companyOf = (w: WatchPayload | undefined, candidateId: string): WatchedCompany | undefined =>
  w?.companies.find((x) => x.candidate_id === candidateId);
