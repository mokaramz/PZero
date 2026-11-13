/**
 * The Investment Desk's page logic, pure (review 031a): the readings the old `HomePage.tsx` made inline on every
 * render, moved here unchanged so they can be tested. The rows, the Manager decisions, the best opportunity, the
 * promising signals, the recent activity, the machine counts and the one situational sentence. Nothing here scores,
 * ranks or calls anything: the missions keep Today's order, the best opportunity is the server's pick and the signals
 * keep the server's attention ranking.
 */
import { type Company, mission, type Mission, plural, short } from "@/features/today/missions";
import type { Candidate, Ev, HomePayload, Inbox, Pipeline, ReviewRow, Row, Signal, Sources, TodayView } from "./types";

export const tierL = (c: Candidate) => (c.discovery_tier === "pre_company" ? "Pre-company" : c.discovery_tier === "grant" ? "Grant" : "Announcement");
/** The analyst's recommendation as a phrase: "STRONG_MAYBE" → "strong maybe". */
export const rec = (s?: string) => (s ?? "").replace(/_/g, " ").toLowerCase();
export const candidateLink = (id: string) => `/deal-flow?candidate=${encodeURIComponent(id)}`;
/** A review row's link. Only review rows build it, and the desk passes none while the queue is deferred (decision d). */
export const reviewLink = (id: string) => `/deal-flow?review=${encodeURIComponent(id)}`;
export const companyLink = (slug: string) => `/conviction?company=${encodeURIComponent(slug)}`;
export const personLink = (id: string) => `/network?person=${encodeURIComponent(id)}`;
/** The desk's own gate (decision f): a possible portfolio conflict OR the operator state CONFLICT GATED. Wider than
 *  Conviction's `isGated` on purpose. */
export const gatedOf = (e: Signal) => e.conflict === "potential_conflict" || e.op?.status === "CONFLICT GATED";

export const SHOWN_MISSIONS = 5;
export const NOTHING = "Nothing needs your judgment right now — the machine is handling the rest.";

export type DeskInput = {
  h: HomePayload;
  ib?: Inbox;
  pipe?: Pipeline;
  today?: TodayView;
  rows: ReviewRow[];
  sources?: Sources;
};

export type DeskView = {
  /** every candidate of the inbox */
  C: Candidate[];
  /** the candidates still to decide */
  news: Candidate[];
  /** Conviction without the dropped companies */
  sig: Signal[];
  /** what needs the Smooth Operator: Today's company and signal missions, then reviews awaiting judgment, then due
   *  follow-ups */
  human: Row[];
  shownMissions: Row[];
  /** blocked on the Manager */
  gated: Signal[];
  /** founders who hold the ball */
  awaiting: Signal[];
  pr: HomePayload["priority"];
  prSig: Signal | undefined;
  /** the best six of the attention queue */
  att6: Candidate[];
  /** the recent activity, newest first */
  activity: Ev[];
  /** analyses completed */
  done: number;
  /** enabled sources with a warning */
  warn: number;
  summary: string;
};

const fieldTone = (m: Mission): Row["tone"] => (m.k.field(m.a) === "risk" ? "risk" : m.k.field(m.a) === "progress" ? "progress" : "neutral");

/** The rows of Priority missions, in order: Today's company and signal missions, the new reviews, the due follow-ups. */
export function missionRows(today: TodayView | undefined, sig: Signal[], rows: ReviewRow[], due: HomePayload["due"] | undefined): Row[] {
  const ms: Mission[] = (today?.actions ?? []).map((a) => mission(a, sig as Company[]));
  const human: Row[] = ms
    .filter((m) => m.k.group === "company" || m.k.group === "signal")
    .map((m) => ({
      key: `t-${m.a.type}-${m.name}`,
      name: m.name,
      reason: m.whyNow || m.line,
      unknown: m.unknown,
      state: m.state,
      tone: fieldTone(m),
      action: "Open",
      to: m.a.link,
    }));
  for (const r of rows.filter((x) => x.decision === "new"))
    human.push({
      key: `r-${r.id}`,
      name: r.name,
      reason: short(r.thesis || "", 9),
      unknown: r.proposed == null ? "Not yet scorable — entity unverified" : `Analyst: ${rec(r.recommendation)} · proposed ${r.proposed}/100`,
      state: "Review",
      tone: "attention",
      action: "Open review",
      to: reviewLink(r.id),
    });
  for (const x of due ?? [])
    human.push({ key: `f-${x.id}`, name: x.name, reason: x.action, unknown: x.date ? `due ${x.date}` : "no date set", state: "Follow-up", tone: "neutral", action: "Open", to: personLink(x.id) });
  return human;
}

/** The promising signals: the new candidates the attention queue does not gate, by the server's final score, then by
 *  priority; six at most. */
export function promising(news: Candidate[]): Candidate[] {
  return news
    .filter((c) => c.attention_v2 && !c.attention_v2.gated)
    .sort((a, b) => (b.attention_v2?.final ?? 0) - (a.attention_v2?.final ?? 0) || (b.priority ?? 0) - (a.priority ?? 0))
    .slice(0, 6);
}

/** The recent activity: the top three candidates of the last scan, the three newest reviews and the two newest
 *  companies sent to the Manager, merged newest first (by their stored date text). */
export function activityOf(news: Candidate[], lastRun: string | null | undefined, rows: ReviewRow[], omar: HomePayload["omar"] | undefined): Ev[] {
  const activity: Ev[] = [];
  news
    .filter((c) => c.run_id && c.run_id === lastRun)
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
    .slice(0, 3)
    .forEach((c) => activity.push({ key: `c-${c.id}`, t: c.first_seen || c.detected_on || "", title: `${c.name} surfaced`, sub: `via ${c.source ?? "a source"}`, to: candidateLink(c.id) }));
  rows
    .slice()
    .sort((a, b) => String(b.created).localeCompare(String(a.created)))
    .slice(0, 3)
    .forEach((r) => activity.push({ key: `r-${r.id}`, t: r.created ?? "", title: `${r.name} analysed — ${rec(r.recommendation)}`, sub: short(r.thesis || "", 8), to: reviewLink(r.id) }));
  (omar ?? []).slice(0, 2).forEach((x) =>
    activity.push({ key: `o-${x.company}`, t: x.sent ?? "", title: `${x.company} sent to Manager`, sub: x.feedback ? "feedback logged" : "awaiting feedback", to: "/conviction" }),
  );
  activity.sort((a, b) => String(b.t).localeCompare(String(a.t)));
  return activity;
}

/**
 * The enabled sources with a warning: failures in a row, or `last_ok === false` (the old check, kept as it was). The
 * old and the new Sources payloads both send `last_ok` as a time string or null — never false — so a source that was
 * never scanned (null) is not a warning here, exactly as before.
 */
export function sourceWarnings(sources: Sources | undefined): number {
  return (sources?.sources ?? []).filter((s) => s.enabled !== false && ((s.failures_in_row ?? 0) > 0 || (s.last_ok as unknown) === false)).length;
}

/** One deterministic situational sentence (no model call). */
export function summaryOf(missions: number, gated: number, awaiting: number): string {
  const parts = [
    missions && `${plural(missions, "mission")} need${missions === 1 ? "s" : ""} judgment`,
    gated && `${plural(gated, "Manager decision")} ${gated === 1 ? "is" : "are"} blocked`,
    awaiting && `${plural(awaiting, "founder")} ${awaiting === 1 ? "holds" : "hold"} the ball`,
  ].filter(Boolean) as string[];
  return parts.length ? `Deal flow is active: ${parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0]}.` : NOTHING;
}

/** Everything the desk shows, from its five reads (`rows` is the deferred review queue: none). */
export function deskView({ h, ib, pipe, today, rows, sources }: DeskInput): DeskView {
  const C = ib?.candidates ?? [];
  const news = C.filter((c) => c.decision === "new");
  const sig = (pipe?.signals ?? []).filter((e) => e.status !== "dropped");
  const human = missionRows(today, sig, rows, h.due);
  const shownMissions = human.slice(0, SHOWN_MISSIONS);
  const gated = sig.filter(gatedOf);
  const awaiting = sig.filter((e) => e.op?.status === "AWAITING FOUNDER RESPONSE");
  const pr = h.priority;
  return {
    C,
    news,
    sig,
    human,
    shownMissions,
    gated,
    awaiting,
    pr,
    prSig: pr ? sig.find((e) => e.slug === pr.slug) : undefined,
    att6: promising(news),
    activity: activityOf(news, ib?.last_run, rows, h.omar),
    done: C.filter((c) => c.analysis_state === "ANALYZED").length,
    warn: sourceWarnings(sources),
    // the old sentence counted every mission, but only once one was shown
    summary: summaryOf(shownMissions.length ? human.length : 0, gated.length, awaiting.length),
  };
}

/** The folded Machine line: new in the last scan · analyses · source warnings. */
export function machineLine(ib: Inbox | undefined, progress: HomePayload["progress"] | undefined, done: number, warn: number): string {
  return `${ib?.last_summary?.new ?? progress?.found ?? 0} new in the last scan · ${done} analyses · ${warn} source warning${warn === 1 ? "" : "s"}`;
}

/** "Last scan <run>: N genuinely new (N from pre-company channels) · N noise set aside.", or null before any scan. */
export function lastScanLine(ib: Inbox | undefined): string | null {
  if (!ib?.last_run) return null;
  const s = ib.last_summary;
  return `Last scan ${ib.last_run}: ${s?.new ?? 0} genuinely new${s?.pre_company_new ? ` (${s.pre_company_new} from pre-company channels)` : ""}${s?.noise ? ` · ${s.noise} noise set aside` : ""}.`;
}

/** "2026-11-02 18:57" → "18:57"; a plain date → "2 Nov". */
export function timeOf(t: string): string {
  const m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (!m) return t;
  if (m[4]) return `${m[4]}:${m[5]}`;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** The event's start day (a local date), or null when the start is not a YYYY-MM-DD date. */
export function eventDate(start: string | undefined): Date | null {
  const d = start?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return d ? new Date(Number(d[1]), Number(d[2]) - 1, Number(d[3])) : null;
}
