/**
 * The story page's pure logic, ported line for line from the old `features/news/NewsPage.tsx`. Rendering stays in
 * ../components; every string the page builds lives here.
 */
import type { Tone } from "@/components/ui";
import type { Check, Disagreement, Independence, NewsPayload, Story } from "./types";

/** The state badges, in the old wording (the page keeps its own map; the payload's `state_labels` is not read). */
export const STATE: Record<string, { label: string; tone: Tone }> = {
  CAUGHT_EARLY: { label: "EARLY CATCH", tone: "green" },
  KNOWN_LATE: { label: "KNOWN, BUT LATE", tone: "amber" },
  MISSED: { label: "MISSED", tone: "red" },
  HISTORICAL: { label: "HISTORICAL CASE", tone: "purple" },
  NOT_RELEVANT: { label: "NOT RELEVANT TO PZ", tone: "neutral" },
  UNKNOWN: { label: "NOT SEEN BY PZ", tone: "neutral" },
};
export const stateBadge = (state: string) => STATE[state] || STATE.UNKNOWN;

/** The nine sections, in the old order (the active one is local state, as before — no query param). */
export const TABS = [
  { value: "today", label: "Today" },
  { value: "all", label: "All stories" },
  { value: "caught", label: "Caught early" },
  { value: "misses", label: "Misses" },
  { value: "historical", label: "Historical cases" },
  { value: "themes", label: "What's moving" },
  { value: "mine", label: "My companies" },
  { value: "weekly", label: "Weekly review" },
  { value: "sources", label: "News sources" },
] as const;
export type Tab = (typeof TABS)[number]["value"];
export type StoryTab = Exclude<Tab, "themes" | "weekly" | "sources">;
export const isStoryTab = (t: Tab): t is StoryTab => t !== "themes" && t !== "weekly" && t !== "sources";

/** What each story section says when it is empty. */
export const EMPTY: Record<StoryTab, string> = {
  today: "No important story yet today. A quiet day with nothing material is normal — click Refresh news, or read the Weekly review.",
  all: "No stories yet — click Refresh news.",
  caught: "No early catches yet. When a company Project Zero found earlier appears in the news, it shows up here with the lead time.",
  misses: "No misses or unreviewed important stories. Stories about companies Project Zero never saw appear here until you review them.",
  historical: "No historical cases yet.",
  mine: "None of your Deal Flow or Conviction companies is in the news right now.",
};
export const THEMES_EMPTY = "No pattern with enough evidence yet (at least 3 companies in 30 days). Two articles are not a trend.";

/** The stories a section lists (the payload's lists, unchanged). */
export function storiesFor(tab: StoryTab, d: NewsPayload): Story[] {
  switch (tab) {
    case "today":
      return d.today;
    case "all":
      return d.stories;
    case "caught":
      return d.caught_early;
    case "misses":
      return d.misses;
    case "historical":
      return d.historical;
    case "mine":
      return d.my_companies;
  }
}

/** "2021" stays a year, "2021-06" is "Jun 2021", a date is "5 Oct 2026"; anything unreadable is shown as it is. */
export const fmt = (d: string) => {
  if (/^\d{4}$/.test(d)) return d;
  const dt = new Date(d.length === 7 ? `${d}-01` : d);
  return Number.isNaN(dt.getTime())
    ? d
    : dt.toLocaleDateString("en-GB", d.length === 7 ? { month: "short", year: "numeric" } : { day: "numeric", month: "short", year: "numeric" });
};

/* ------------------------------------------------------------------ the intro cards and the footer */
export const NOTICE_EMPTY = "Once a story has a backcast (what signals existed before it), its lesson appears here.";

/** "Last refresh: 2026-11-12 07:00 · 5 feeds · 3 new events · 1 feed(s) failed (retried tomorrow). Project Zero started on …" */
export function footerLine(d: Pick<NewsPayload, "last_run" | "pz_start">): string {
  const r = d.last_run;
  const last = r ? `${r.at.slice(0, 16).replace("T", " ")} · ${r.sources_ok} feeds · ${r.new} new events` : "not yet";
  const failed = r?.sources_failed.length ? ` · ${r.sources_failed.length} feed(s) failed (retried tomorrow)` : "";
  return `Last refresh: ${last}${failed}. Project Zero started on ${fmt(d.pz_start)}.`;
}

/* ------------------------------------------------------------------ a story card */
export const metaLine = (s: Story) => `${s.type_label} · ${fmt(s.event_date)} · ${s.sources.length} source${s.sources.length === 1 ? "" : "s"}`;
export const whatHappened = (s: Story) => s.card?.what_happened || s.summary || "Only the headline is available — open the source.";

/** "amount: Alpine Wire 18.4M vs Isar Startup Post 18M (settled by primary source); round: …" */
export const disagreementLine = (list: Disagreement[]) =>
  list
    .map(
      (x) =>
        `${x.field === "amount_m" ? "amount" : "round"}: ${Object.entries(x.values)
          .map(([p, v]) => `${p} ${x.field === "amount_m" ? `${v}M` : v}`)
          .join(" vs ")}${x.status === "RESOLVED" ? ` (settled by ${x.basis})` : " (not settled yet)"}`,
    )
    .join("; ");

/** The outcome proposal shows until a decision is recorded. */
export const showsProposal = (s: Story) => !!s.outcome_proposal && !s.outcome_decision;
export const proposalText = (s: Story) =>
  s.outcome_proposal
    ? ` this looks like a real-world ${s.outcome_proposal.kind.replace(/_/g, " ")} for ${s.company}. ${s.outcome_proposal.effect}. Only your confirmation records it in Validation.`
    : "";

export const analysisLabel = (s: Story, open: boolean) => (open ? "Hide analysis" : s.backcast ? "Backcast & sources" : "Sources & learning");
/** A miss (or a possible one) with a named company and no audit yet can be audited. */
export const canAudit = (s: Story) => (s.state === "MISSED" || !!s.check.possible_miss) && !s.audit_id && !!s.company;
/** An important story about a named company can take an early signal. */
export const takesSignals = (s: Story) => s.materiality === "HIGH" && !!s.company;
/** The old line also offered "or prepare research" — the Scout Bridge research job, which is not part of the rewrite. */
export const NO_BACKCAST = "No backcast yet: what public signals existed before this story? Add one signal with its source.";

export const INDEPENDENCE: Record<Independence, { label: string; tone: Tone }> = {
  syndicated: { label: "copy of another article", tone: "neutral" },
  primary: { label: "primary source", tone: "blue" },
  independent: { label: "independent media", tone: "green" },
};
export const independence = (x: Independence | string) => INDEPENDENCE[x as Independence] ?? INDEPENDENCE.independent;

/** Who wrote the card: rules, a curated case or a model. */
export const provenance = (generatedBy: string) =>
  generatedBy === "rules"
    ? "Summary built by rules (no model) from the article text."
    : generatedBy.startsWith("curated")
      ? "Curated from the linked sources."
      : `Summary written by ${generatedBy} from the article text only.`;

export const signalBadge = (kind: string) =>
  kind === "known_early_signal" ? { label: "known early signal", tone: "green" as Tone } : { label: "only clear in retrospect", tone: "neutral" as Tone };

/** The "Project Zero check" sentence per state: an optional bold lead, then the rest. */
export function checkText(s: Pick<Story, "state" | "company"> & { check: Check }, pzStart: string): { strong?: string; text: string } {
  const k = s.check;
  if (s.state === "CAUGHT_EARLY")
    return {
      strong: `Project Zero edge: detected ${k.lead_days} days before this event.`,
      text:
        `First seen ${fmt(k.pz_first_seen || "")} via ${k.first_source || "a scan"}` +
        `${k.first_tier ? ` (${k.first_tier.replace("_", "-")})` : ""}` +
        `${k.capital_stage ? `, capital stage then: ${k.capital_stage.replace(/_/g, " ").toLowerCase()}` : ""}. Machine said ${k.machine || "—"}` +
        `${k.mohamed ? `, you decided ${k.mohamed}` : ""}.`,
    };
  if (s.state === "KNOWN_LATE")
    return {
      text:
        `Project Zero knew ${s.company}, but only ${k.lead_days !== undefined && k.lead_days > 0 ? `${k.lead_days} days` : "at the time of"} this news` +
        `${k.first_tier === "announcement" ? " — it was found through funding news itself" : ""}. No sourcing edge claimed.`,
    };
  if (s.state === "HISTORICAL") return { text: `Its early signals predate Project Zero (started ${fmt(pzStart)}) — a learning case, not a miss.` };
  if (s.state === "MISSED") return { text: "A public signal existed while Project Zero was running, and Project Zero did not detect it." };
  if (s.state === "NOT_RELEVANT") return { text: "Outside Project Zero's geography or themes — context only." };
  return {
    text: `Project Zero has not seen ${s.company || "this company"}. ${
      k.possible_miss ? "Not yet reviewed — it may be a miss, or the early signals may predate Project Zero. Add a backcast or audit it." : ""
    }`,
  };
}

/* ------------------------------------------------------------------ What's moving */
export const companiesLine = (n: number) => `Project Zero already holds ${n} compan${n === 1 ? "y" : "ies"} with this theme.`;
