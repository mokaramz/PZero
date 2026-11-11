/**
 * Pure view logic of the v1 Conviction page (pipeGroups, live score preview, labels) — PROTECTED: ported verbatim
 * (review 011). The server score (`sc`, taste.py) is the authority; these client rules only group and preview.
 * Three known differences from the server are kept on purpose (011 decision c) and pinned by boundary tests:
 *   - `liveScore` does not zero the resemblance bonus for archetype #15 (the server does);
 *   - "Investigate" is provisional ≥ 63 (the server bands are 65 and 80);
 *   - `isGated` covers only `potential_conflict` (the server also gates `unclear`).
 * Fixing any of them moves what the Smooth Operator sees, so it needs its own decision record.
 */
import { asRole } from "@/lib/roles";
import type { Meta, Signal } from "./types";

export type Seg = "all" | "inv" | "watch" | "gated";

export const isGated = (e: Signal) => e.conflict === "potential_conflict";
export const human = (s: string | undefined, fallback = "unknown") => (s || fallback).replace(/_/g, " ");

/** v1 pipeGroups(): dropped hidden; gated = potential conflict; Investigate = provisional ≥ 63; Watch below. */
export function pipeGroups(signals: Signal[], q: string) {
  const s = q.trim().toLowerCase();
  const L = signals.filter((e) => e.status !== "dropped").filter((e) => !s || JSON.stringify(e).toLowerCase().includes(s));
  const byProv = (a: Signal, b: Signal) => b.sc.provisional - a.sc.provisional;
  return {
    // a company on hold (human outcome: WATCHING) is listed under Watch whatever its score band
    inv: L.filter((e) => !isGated(e) && e.sc.provisional >= 63 && e.op?.status !== "WATCHING").sort(byProv),
    watch: L.filter((e) => !isGated(e) && (e.sc.provisional < 63 || e.op?.status === "WATCHING")).sort(byProv),
    gated: L.filter(isGated),
  };
}

export function archetypeOf(meta: Meta | undefined, id: number | undefined) {
  return (meta?.archetypes ?? []).find((a) => a.id === id);
}

export function verifyListText(v: Signal["verify_list"]): string {
  if (!v) return "";
  return Array.isArray(v) ? v.join(", ") : v;
}

/** Live Provisional / Verified preview of the Edit & verify form — mirrors v1 live() (taste.py is the authority on save). */
export type LiveInput = {
  founder: number;
  venture_scale: number;
  why_now: number;
  taste: number;
  insight: number;
  earliness: string;
  conflict: string;
  penalties: string[];
  v_founders: boolean;
  v_traction: boolean;
  v_funding: boolean;
};

const EARL: Record<string, number> = { pre_company: 10, grant_angel: 8, pre_seed: 6, seed: 3, series_a_plus: 0, unknown: 0 };
const PEN: Record<string, number> = { consumer: -20, non_eu: -15, known: -15, wrapper: -10 };
const clamp = (n: number) => Math.max(0, Math.min(100, n));

export function liveScore(f: LiveInput) {
  const earl = EARL[f.earliness] ?? 0;
  const res = f.conflict === "complementary" ? 5 : f.conflict === "similar" ? 4 : 0;
  let pen = f.penalties.reduce((a, k) => a + (PEN[k] ?? 0), 0);
  if (f.conflict === "potential_conflict") pen -= 25;
  const prov = clamp(f.founder + f.venture_scale + f.why_now + f.taste + earl + f.insight + res + pen);
  const ver = clamp(
    (f.v_founders ? f.founder : 0) +
      f.venture_scale +
      f.why_now +
      f.taste +
      (f.v_funding ? earl : 0) +
      (f.v_traction ? f.insight : Math.floor(f.insight / 2)) +
      res +
      pen,
  );
  const miss = [!f.v_founders && "founders", !f.v_traction && "traction", !f.v_funding && "funding"].filter(Boolean) as string[];
  return { prov, ver, missLabel: miss.length ? `unverified: ${miss.join(", ")}` : "fully verified" };
}

export const today = () => new Date().toISOString().slice(0, 10);

/* ------------------------------------------------------------------ Conviction executive workspace (presentation only) */

/** "AWAITING FOUNDER RESPONSE" → "Awaiting founder response" (the label carries the meaning, not the case). */
export const sentence = (s: string | undefined) => {
  const t = (s || "").replace(/_/g, " ").trim().toLowerCase();
  return t ? t[0].toUpperCase() + t.slice(1) : "";
};

/** CURRENT STATE — the workflow condition the company is in (backend operator_status), never the investment view. */
export function currentState(e: Signal): { label: string; why: string; tone: "attention" | "risk" | "progress" | "neutral" } {
  const op = e.op;
  if (op && op.source !== "score band") {
    const tone = op.status === "CONFLICT GATED" ? "risk" : op.status === "READY FOR MOHAMED" || op.status === "WAITING FOR HUMAN" ? "attention" : "neutral";
    return { label: asRole(sentence(op.status)), why: asRole(stateReason(op.why, op.source)), tone };
  }
  if (isGated(e)) return { label: "Conflict gated", why: `possible overlap with ${e.twin || "the portfolio"} — Manager first`, tone: "risk" };
  return { label: e.status && e.status !== "new" ? sentence(e.status) : "Case not prepared yet", why: "", tone: "neutral" };
}

/** PZ VIEW — what Project Zero thinks of the company as an investment (the score band), kept apart from the workflow. */
export function pzView(e: Signal): string {
  if (e.op?.status === "WATCHING") return "Watch — no active work";
  if (isGated(e) || e.op?.status === "CONFLICT GATED") return "Hold until Manager answers the conflict";
  return sentence(e.sc.verdict) || "Not assessed";
}

/** The one contextual primary action for a prepared-case next-action code (labels only; every target is an existing gate). */
export type PrimaryKind = "contact" | "omar" | "link" | "edit" | "section" | "whynow" | "none";
export type Section = "case" | "evidence" | "founders" | "funding" | "risks" | "omar" | "audit";
export const PRIMARY: Record<string, { label: string; kind: PrimaryKind; contact?: string; section?: Section }> = {
  NO_ACTIVE_WORK: { label: "", kind: "none" },
  ASK_OMAR: { label: "Ask Manager…", kind: "omar" },
  CONSIDER_OMAR: { label: "Review for Manager", kind: "omar" },
  DECIDE_WATCH_OR_DROP: { label: "Decide…", kind: "edit" },
  RECORD_CALL_OUTCOME: { label: "Record call outcome", kind: "link" },
  AWAIT_FOUNDER_RESPONSE: { label: "Record reply…", kind: "contact", contact: "reply_received" },
  FOLLOW_UP_ONCE: { label: "Record follow-up…", kind: "contact", contact: "follow_up_sent" },
  PREPARE_FOUNDER_CALL: { label: "Open call prep", kind: "link" },
  CONTACT_FOUNDER: { label: "Record outreach…", kind: "contact", contact: "outreach_sent" },
  ACCEPT_VERIFICATION: { label: "Review verification", kind: "section", section: "evidence" },
  ADVANCE_INVESTIGATION: { label: "Open the evidence", kind: "section", section: "evidence" },
  RECORD_WHY_NOW: { label: "Review & record why-now…", kind: "whynow" },
  AUTHOR_SCORE: { label: "Author the score", kind: "edit" },
};

/** The one deeper section the current workflow needs open (none when the next move is not Mohamed's). */
export const AUTO_OPEN: Record<string, Section> = {
  ASK_OMAR: "omar",
  CONSIDER_OMAR: "omar",
  ACCEPT_VERIFICATION: "evidence",
  ADVANCE_INVESTIGATION: "evidence",
  CONTACT_FOUNDER: "founders",
  PREPARE_FOUNDER_CALL: "founders",
  RECORD_WHY_NOW: "funding",
};

/** Verified critical facts (founders / traction / funding) — the Evidence & verification summary line. */
export function verifiedCount(e: Signal) {
  const v = (e.verified ?? {}) as Record<string, boolean>;
  return ["founders", "traction", "funding"].filter((k) => v[k]).length;
}

/** The short reason a company is in its state — not the full move rationale (that sits under YOUR MOVE). */
function stateReason(why: string, source: string): string {
  const w = (why || "").replace(/_/g, " ");
  if (source !== "prepared case") return w;
  const first = w.split(/(?<=\.)\s/)[0].replace(/\.$/, "");
  const tail = first.includes(" — ") ? first.slice(first.indexOf(" — ") + 3) : "";
  return tail ? sentence(tail) : "";
}

/** The rest of a move rationale once its first clause already explains the current state. */
export function moveDetail(why: string): string {
  const parts = (why || "").split(/(?<=\.)\s/);
  return parts.length > 1 && parts[0].includes(" — ") ? parts.slice(1).join(" ") : why;
}

/** "NOT YET IMQ" → "Not yet IMQ" */
export const imqLabel = (s: string) => sentence(s.replace(/^IMQ — /, "IMQ ")).replace(/\bimq\b/gi, "IMQ");

/** The REAL independent inputs behind a company — its discovery source, its recorded sources (as domains) and each
 *  Scout 00 cycle that reported it. Feeds the Convergence Trace; never invents an input. */
export function convergenceSources(e: Signal): string[] {
  const dom = (u: string) => {
    const m = String(u).match(/^https?:\/\/(?:www\.)?([^/]+)/i);
    return m ? m[1] : String(u);
  };
  const out: string[] = [];
  if (e.discovery_source) out.push(e.discovery_source);
  for (const s of e.sources ?? []) if (s) out.push(dom(s));
  const raw: unknown = e.scout_provenance;
  for (const v of Array.isArray(raw) ? raw : raw ? [raw] : [])
    if (v && typeof v === "object" && (v as { scout_cycle_id?: string }).scout_cycle_id)
      out.push(`Scout 00 · cycle ${(v as { scout_cycle_id: string }).scout_cycle_id}`);
  // one publication counted once: "ArcticStartup announcements" and "arcticstartup.com" are the SAME input
  const base = (x: string) => {
    const t = x.trim().toLowerCase();
    if (t.startsWith("scout 00")) return t;
    const host = t.match(/^[a-z0-9-]+(?:\.[a-z0-9-]+)+$/) ? t.split(".").slice(-2, -1)[0] : t.split(/[\s·—(]/)[0];
    return host.replace(/[^a-z0-9]/g, "");
  };
  const keys: string[] = [];
  return out.filter((x) => {
    const k = base(x);
    if (!k || keys.some((y) => y === k || (y.length >= 5 && k.includes(y)) || (k.length >= 5 && y.includes(k)))) return false;
    keys.push(k);
    return true;
  });
}
