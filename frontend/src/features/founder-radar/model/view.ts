/**
 * What the Founder Radar shows, as pure functions over the GET body: the views and segments the URL opens, the counts
 * line, the Research Queue list, the links out, the review drawer's selections and every toast text. The wording is the
 * old page's (`features/founders/*`), unchanged.
 */
import { companyMatch, frMatch, inSegment, radarPeople, segmentCounts, sortPeople, type Filters, type Seg, type View } from "./logic";
import { plainText } from "@/lib/activity";
import type { CallContext, Company, FounderRadar, Health, ImportResult, Lead, Person, ProposalGroup, ResearchResult, ReviewResult, ScanResult } from "./types";

/* ------------------------------------------------------------------ the URL */

export const VIEWS: View[] = ["top", "near", "research", "diag"];

/** `?view=` (default Top Founder Leads). */
export const viewOf = (params: URLSearchParams): View => (VIEWS.includes(params.get("view") as View) ? (params.get("view") as View) : "top");

/** `?seg=`, else the Research Queue opens on the company qualification queue (claim) and the rest on Gold. */
export const initialSeg = (params: URLSearchParams, view: View): Seg => (params.get("seg") as Seg) || (view === "research" ? "claim" : "gold");

/** The URL after switching views: Top Founder Leads drops `view`, every other key stays. */
export function withView(params: URLSearchParams, v: View): URLSearchParams {
  const n = new URLSearchParams(params);
  if (v === "top") n.delete("view");
  else n.set("view", v);
  return n;
}

/* ------------------------------------------------------------------ counts and lists */

/** v1 frCounts: the bucket counts, or the company-queue reconciliation line while the claim segment is active. */
export function countsLine(data: FounderRadar, seg: Seg, q: string): string {
  if (seg === "claim") {
    const C = (data.companies ?? []).filter((c) => companyMatch(c, q, data.people));
    const qc = data.queue_counts ?? {};
    return (
      `Company leads ${qc.company_leads ?? C.length} · claimed founders ${qc.claimed_founder_refs ?? C.reduce((a, c) => a + c.founders.length, 0)} · ` +
      `separately: ${qc.claim_bucket_people ?? "—"} people currently in Founder claim bucket`
    );
  }
  const n = segmentCounts(radarPeople(data), data.network_states ?? []);
  return (
    `${n.gold} deserve attention first (Gold + Strong) · ${n.claim} founder claims unresolved · ${n.research} research & spinout talent · ` +
    `${n.insuf} insufficient · ${n.watchlist} watchlisted · ${n.network} in Network`
  );
}

/** The Research Queue's people: the segment (or, while searching, every bucket), the filters, the old order, a cap of
 *  20 for Gold and 200 elsewhere. */
export function researchList(data: FounderRadar, seg: Seg, filters: Filters, q: string): { list: Person[]; hidden: number } {
  const ns = data.network_states ?? [];
  const P = radarPeople(data);
  const L = sortPeople((q ? P : P.filter((p) => inSegment(p, seg, ns))).filter((p) => frMatch(p, filters, q)));
  const cap = seg === "gold" ? 20 : 200;
  return { list: L.slice(0, cap), hidden: Math.max(0, L.length - cap) };
}

/** The company leads the search keeps (company name, claimed / scout-reported / linked founder names). */
export const matchingCompanies = (data: FounderRadar, q: string): Company[] => (data.companies ?? []).filter((c) => companyMatch(c, q, data.people));

/** The "Truthful counts" rail: every metric but the date, `null` shown as "—". */
export const metricRows = (m: FounderRadar["metrics"]): Array<{ key: string; value: string; label: string }> =>
  Object.entries(m ?? {})
    .filter(([k]) => k !== "date")
    .map(([k, v]) => ({ key: k, value: v == null ? "—" : String(v), label: k.replace(/_/g, " ") }));

/* ------------------------------------------------------------------ links out */

/** "Log founder call" → Founder Calls' new-call form, prefilled (it reads these keys). */
export function callLink(c: CallContext): string {
  const u = new URLSearchParams({ new: "1", person_id: c.person_id, name: c.name, company: c.company || "", radar_key: c.radar_key || "" });
  return `/founder-calls?${u.toString()}`;
}

/** The Scout Packet identity review (the app redirects `/scout-intake` to Deal Flow). */
export const scoutReviewLink = (itemId: string) => `/scout-intake?item=${encodeURIComponent(itemId)}&review=identity&from=founders`;

/** External searches: never evidence. */
export const webSearchLink = (company: string) => `https://duckduckgo.com/?q=${encodeURIComponent(company + " founders")}`;
export const linkedinCompanySearch = (company: string) => `https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(company)}`;
export const linkedinPeopleSearch = (p: Pick<Person, "name" | "company">) =>
  `https://www.linkedin.com/search/results/people/?keywords=${encodeURIComponent(p.name + " " + (p.company || ""))}`;

/* ------------------------------------------------------------------ cards */

/** A lead's access pill. */
export const leadAccessText = (l: Pick<Lead, "access" | "access_label">) =>
  l.access === "none" ? "no access path recorded" : l.access + (l.access_label ? " — " + l.access_label.replace(/^(Warm path|Contact route): /, "") : "");

/** A company card's domain badge (none for a pipeline website). */
export function domainTag(c: Pick<Company, "domain" | "domain_source">): string | null {
  if (!c.domain_source || c.domain_source === "pipeline website") return null;
  if (c.domain === "UNKNOWN") return "domain UNKNOWN";
  return c.domain_source.startsWith("candidate") ? "candidate domain" : "confirmed domain";
}

export const priorityFactorsLine = (c: Pick<Company, "priority_factors" | "research_priority">) =>
  `${(c.priority_factors ?? []).map((f) => `${f.factor} ${f.points >= 0 ? "+" : ""}${f.points}`).join(" · ")} · total ${c.research_priority ?? 0}`;

/* ------------------------------------------------------------------ review drawer */

/** "Confirm recommended facts": the recommended rows still pending (never a founder identity — the server never
 *  recommends one, and the page sends only what it recommends). */
export const recommendedPending = (groups: ProposalGroup[], recommended: string[]): string[] => {
  const rec = new Set(recommended);
  return groups.filter((g) => rec.has(g.best.id) && g.best.status === "pending").map((g) => g.best.id);
};

/** The per-row founder selectors start from the stored binding. */
export function storedBindings(groups: ProposalGroup[]): Record<string, string> {
  const b: Record<string, string> = {};
  for (const g of groups) if (g.field === "founder" && g.best.bound_person) b[g.best.id] = g.best.bound_person;
  return b;
}

/** The bindings a review sends: only rows with a chosen founder. */
export const chosenBindings = (bind: Record<string, string>): Record<string, string> => Object.fromEntries(Object.entries(bind).filter(([, v]) => v));

export const recommendedToast = (x: ReviewResult) => `Confirmed ${(x.facts ?? []).length} recommended fact(s): ${(x.facts ?? []).join(", ")}`;

export const reviewToast = (mode: "confirm" | "reject", x: ReviewResult) =>
  `${mode === "confirm" ? "Confirmed" : "Rejected"} · facts: ${(x.facts ?? []).join(", ") || "none"}` +
  ((x.identity_bound ?? []).length ? " · identity: " + x.identity_bound!.map((b) => b.name + " ✓").join("; ") : "") +
  ((x.still_pending ?? []).length ? " · still pending: " + x.still_pending!.length : "") +
  ((x.conflicts ?? []).length ? " · conflicts: " + x.conflicts!.length : "") +
  ((x.refused ?? []).length ? " · refused: " + x.refused!.join(", ") : "");

/* ------------------------------------------------------------------ import */

export const importToast = (r: ImportResult) =>
  `${r.format === "linkedin_connections" ? "LinkedIn Connections export" : "custom CSV"}: ${r.new || 0} new · ${r.merged || 0} merged${
    (r.skipped ?? []).length ? " · " + r.skipped!.length + " skipped" : ""
  } — ${r.note || ""}`;

/** The file note after a pick. */
export const fileNote = (name: string, size: number) => `${name} loaded (${Math.round(size / 1024)} KB) — review, then Import`;

/* ------------------------------------------------------------------ the scan and company research (026b) */

/** A synchronous scan answers the health report; anything else (`{started: true}`) is polled until the scan time changes. */
export const scanFinished = (h: ScanResult): boolean => !!(h.totals && h.scan_time);

export const scanToast = (h: Health) => {
  const t = h.totals ?? {};
  return `Scan done: ${t.ok ?? 0} ok · ${t.failed ?? 0} failed · ${t.new ?? 0} new · ${t.merged ?? 0} merged`;
};

/** The first (only) company of a `{key}` research run; a missing row is a failure without a reason. */
const firstResearched = (r: ResearchResult) => r.researched?.[0] ?? { ok: false, error: "" };

/** "Research company": the toast and whether proposals are ready to review. */
export function researchCompanyToast(r: ResearchResult): { ok: boolean; text: string } {
  const x = firstResearched(r);
  return { ok: !!x.ok, text: x.ok ? `${x.pages} page(s) retrieved · ${x.proposals} proposal(s) — review before anything counts` : plainText(x.error) || "research failed" };
}

/** "Refresh research" (decisions kept). */
export function refreshToast(r: ResearchResult): { ok: boolean; text: string } {
  const x = firstResearched(r);
  return { ok: !!x.ok, text: x.ok ? `${x.pages} page(s) · ${x.new || 0} new proposal(s)` : plainText(x.error) || "refresh failed" };
}

/** "Research next 5 leads": one part per company. */
export const researchLeadsToast = (r: ResearchResult) =>
  (r.researched ?? []).map((x) => `${x.name}: ${x.ok ? x.proposals + " proposals" : plainText(x.error)}`).join(" · ") || "nothing left to research";
