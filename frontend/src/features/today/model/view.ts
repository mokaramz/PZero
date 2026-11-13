/**
 * Today's page logic, pure (review 030a): the readings the old `TodayPage.tsx` made inline, moved here unchanged so they
 * can be tested — the mission board (groups, briefing, flow), the Machine line, the exceptions line and the footer —
 * plus the snapshot note of decision f. Nothing here judges, ranks or calls anything: the order is the server's.
 */
import { asRole } from "@/lib/roles";
import { type Company, type Mission, mission, plural, type Triage } from "../missions";
import type { Only, SnapshotNote, TodayView } from "./types";

/** "Friday, 13 Nov · 09:30" (en-GB, the browser's clock), as before. */
export function heroDate(now: Date): string {
  const day = now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" }).replace(" ", ", ");
  return `${day} · ${now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

export type Board = {
  /** the pipeline without dropped companies (the tiles count these) */
  signals: Company[];
  /** company and signal missions, in the server's order */
  missions: Mission[];
  events: Mission[];
  manager: Mission[];
  /** the missions the filter shows */
  shown: Mission[];
  nCompany: number;
  /** the briefing's one mission: the first mission, else the first event, else the first Manager decision */
  top: Mission | undefined;
  /** "N priority missions · N Manager decisions due · N event decisions", or the quiet line */
  brief: string;
};

export const NOTHING = "Nothing needs you today";

/** The actions joined with the cached pipeline and grouped, as the old page did on every render. */
export function board(d: TodayView, pipeline: Company[] | undefined, only: Only): Board {
  const signals = (pipeline ?? []).filter((e) => e.status !== "dropped");
  const all = d.actions.map((a) => mission(a, signals));
  const missions = all.filter((m) => m.k.group === "company" || m.k.group === "signal");
  const events = all.filter((m) => m.k.group === "event");
  const manager = all.filter((m) => m.k.group === "manager");
  const parts = [
    missions.length && plural(missions.length, "priority mission"),
    manager.length && `${plural(manager.length, "Manager decision")} due`,
    events.length && plural(events.length, "event decision"),
  ].filter(Boolean);
  return {
    signals,
    missions,
    events,
    manager,
    shown: missions.filter((m) => only === "all" || m.k.group === only),
    nCompany: missions.filter((m) => m.k.group === "company").length,
    top: missions[0] ?? events[0] ?? manager[0],
    brief: parts.length ? parts.join(" · ") : NOTHING,
  };
}

/** The flow graphic's accessible name, from the page's real counts. */
export function flowLabel(missions: number, decisions: number, handled?: number): string {
  return `Today's flow: ${handled !== undefined ? `${handled} signals handled by the machine → ` : ""}${missions} missions for review → ${decisions} decisions due`;
}

/** The folded Machine line: the compression counts, or "working" before any compression run. */
export function machineLine(t: Triage | null | undefined): string {
  if (!t) return "working";
  const c = t.counts ?? {};
  return `${t.total} handled · ${c.BACKGROUND_RESEARCH ?? 0} researching · ${(c.MACHINE_WATCH ?? 0) + (c.DEFERRED_LOW_PRIORITY ?? 0)} watching`;
}

/** How many proposals "Review N" opens: the attention budget caps what needs you plus the calibration samples. */
export const reviewCount = (t: Triage | null | undefined): number => (t ? Math.min(t.limit, t.needs_mohamed + t.calibration) : 0);

export const HANDLED = "Project Zero is handling the rest.";

/** The exceptions in role wording, joined — the old backend texts as they are ("… for Omars" stays: decision h). */
export function exceptionsLine(d: TodayView): string {
  return d.exceptions?.length ? d.exceptions.map((x) => asRole(x.text)).join(" · ") : HANDLED;
}

/** The footer: what was not shown, the rule, and every section the server considered (only the keys it sent). */
export function footerLine(d: TodayView): string {
  const considered = Object.entries(d.considered)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");
  return `${d.more ? `${d.more} lower-priority action(s) not shown. ` : ""}${d.rules} Sources considered: ${considered}.`;
}

/** "2026-11-12T23:05:10" → "2026-11-12 23:05" (the stored run time as it stands: no time-zone conversion). */
export function stamp(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]}` : iso;
}

/** The snapshot note with the original run timestamps (decision f), or null when the server sent none. */
export function snapshotLine(note: SnapshotNote | null | undefined): string | null {
  if (!note?.note) return null;
  const stamps = [
    note.triage_at && `triage run ${stamp(note.triage_at)}`,
    note.cases_prepared_at && `newest prepared case ${stamp(note.cases_prepared_at)}`,
  ].filter(Boolean);
  const text = note.note.replace(/\.\s*$/, "");
  return stamps.length ? `${text} (${stamps.join(" · ")}).` : `${text}.`;
}
