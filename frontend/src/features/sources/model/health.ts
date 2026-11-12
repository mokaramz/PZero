/** The source registry's pure rules (old `health.ts` plus the rules the old table and detail kept inline). */
import type { Workspace } from "@/features/deal-flow/model/geo";
import type { ReportRow, WsGeos } from "@/features/deal-flow/model/types";
import type { Health, Source, SourceFeedback, SourcesPayload } from "./types";

/** v1 srcHealth — health state + operator label. */
export function srcHealth(s: Source): [Health, string] {
  if (s.enabled === false) return ["off", "Disabled"];
  const f = s.failures_in_row || 0;
  if (f >= 3) return ["failed", `Failing — ${f} consecutive failures`];
  if (f > 0) return ["warn", `Warning — ${f} recent failure${f > 1 ? "s" : ""}`];
  if (!s.last_ok) return ["warn", "Not yet scanned"];
  return ["ok", "Healthy"];
}

/** The table's short health word. */
export const HEALTH_SHORT: Record<Health, string> = { ok: "ok", warn: "warn", failed: "fail", off: "off" };

export function healthCounts(sources: Source[]): Record<Health, number> {
  const h: Record<Health, number> = { ok: 0, warn: 0, failed: 0, off: 0 };
  for (const s of sources) h[srcHealth(s)[0]]++;
  return h;
}

/** Sources offers Europe / North America / all; the Deal Flow-only "Unresolved" view shows all here. */
export type SrcWorkspace = Exclude<Workspace, "unk">;
export const srcWs = (ws: Workspace): SrcWorkspace => (ws === "unk" ? "all" : ws);

/** v1 wsGeoSet: the geo tags a workspace covers (server-provided ws_geos, data-driven). */
export function wsGeoSet(ws: SrcWorkspace, m: SourcesPayload, geos: WsGeos): string[] {
  return ws === "na" ? geos.na : ws === "eu" ? geos.eu : m.geos;
}

export function sourcesInWs(m: SourcesPayload, ws: SrcWorkspace, set: string[]): Source[] {
  return m.sources.filter((s) => ws === "all" || (s.geo || []).some((g) => set.includes(g)));
}

export const WS_NOTE: Record<SrcWorkspace, string> = { all: "all workspaces", na: "North America workspace", eu: "Europe workspace" };

/** "+2" / "-1" / "0" */
export const signed = (n: number): string => `${n > 0 ? "+" : ""}${n}`;

/** The table's Fb. prio cell: the adjustment once active, else "0" with the reviewed / needed count. */
export function fbPrio(fb: SourceFeedback, minReviewed = 5): { value: string; progress?: string } {
  if (fb.active) return { value: signed(fb.adjustment ?? 0) };
  return { value: "0", progress: `${fb.reviewed || 0}/${minReviewed}` };
}

/** The detail's quality funnel rows, in the old order. */
export function funnel(s: Source): Array<[string, number]> {
  const q = s.quality || {};
  return [
    ["found", q.candidates_found || 0],
    ["attention", q.attention_queue || 0],
    ["researched", q.researched || 0],
    ["kept", q.kept || 0],
    ["radar", q.radar || 0],
    ["sent to team", q.sent_to_omar || 0],
    ["Manager +", q.omar_positive || 0],
    ["Manager −", q.omar_negative || 0],
  ];
}

/** "Limitations / known issues": the notes when they call the source partial / lazy / js-only, else a sentence for a
 *  failing or warning source, else null (nothing recorded). */
export function limitation(s: Source): string | null {
  const notes = (s.notes || "").toLowerCase();
  if (notes.includes("partial") || notes.includes("lazy") || notes.includes("js-only")) return s.notes || "";
  const [h] = srcHealth(s);
  if (h === "failed") return "Consecutive failures — the site may have changed or be unreachable; the scan retries automatically and nothing is invented.";
  if (h === "warn") return "A recent failure or no scan yet; monitored on the next run.";
  return null;
}

/** The source's row in the last scan report: its exact name, or the first row containing the name before " (". */
export function latestScan(s: Source, report: ReportRow[]): ReportRow | undefined {
  const base = (s.name || "").split(" (")[0];
  return report.find((r) => (r.source || "") === s.name || (r.source || "").includes(base));
}

export function scanTone(status: string | undefined): "green" | "red" | "amber" {
  return status === "ok" ? "green" : status === "fail" || status === "error" ? "red" : "amber";
}

/** A coverage cell's level from its VERIFIED weight. */
export type CoverageLevel = "none" | "weak" | "ok" | "strong";
export const coverageLevel = (v: number): CoverageLevel => (v <= 0 ? "none" : v < 2 ? "weak" : v < 4 ? "ok" : "strong");
