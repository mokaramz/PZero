/**
 * Today's missions — shared by Today (the full mission board) and the Investment Desk (its top few). One deterministic
 * reading of the /api/today actions joined with the cached pipeline: no new judgement, no new call.
 */
import { type Field } from "@/components/focus";
import { asRole } from "@/lib/roles";

export type Action = {
  type: string;
  title: string;
  why: string;
  next_step: string;
  link: string;
  urgency: "high" | "medium" | "low";
  evidence: string[];
  subject: string;
  conflict: string;
  contact_appropriate: boolean;
};
export type Exception = { key: string; n: number; text: string };
export type Triage = {
  at: string;
  total: number;
  counts: Record<string, number>;
  needs_mohamed: number;
  calibration: number;
  limit: number;
  queued_beyond_budget: number;
  resurfaced: number;
};
export type TodayPayload = {
  date: string;
  actions: Action[];
  more: number;
  considered: Record<string, number | string>;
  rules: string;
  exceptions?: Exception[];
  machine_working?: string;
  triage?: Triage | null;
};

export type Kind = {
  label: string;
  field: (a: Action) => Field;
  group: "company" | "event" | "manager" | "signal";
  move: (a: Action) => string;
};
/** Mission kinds: the card's label, its one semantic field, the header group, and the move in a few words. */
export const KIND: Record<string, Kind> = {
  CASE_READY: {
    label: "Case ready",
    field: (a) => (a.urgency === "high" ? "attention" : "neutral"),
    group: "company",
    move: (a) =>
      a.why.match(/Recommended next action:\s*([^—.]+)/)?.[1]?.trim() ??
      "Open the case",
  },
  CONTACT_FOUNDER: {
    label: "Your move",
    field: () => "neutral",
    group: "company",
    move: () => "Contact the founder",
  },
  PREPARE_FOUNDER_CALL: {
    label: "Founder call",
    field: () => "neutral",
    group: "company",
    move: () => "Prepare the call",
  },
  REVIEW_VERIFICATION: {
    label: "Verification",
    field: () => "neutral",
    group: "company",
    move: () => "Verify the evidence",
  },
  WATCH_TRIGGER: {
    label: "New intel",
    field: () => "progress",
    group: "company",
    move: () => "Review the change",
  },
  NATIVE_INTEL: {
    label: "New intel",
    field: () => "progress",
    group: "signal",
    move: () => "Review and decide",
  },
  SCOUT00_CYCLE: {
    label: "Scout 00",
    field: () => "attention",
    group: "signal",
    move: () => "Review Scout Intake",
  },
  EVENT_ACTION: {
    label: "Event",
    field: () => "neutral",
    group: "event",
    move: () => "Decide: go or skip",
  },
  ASK_OMAR_CONFLICT: {
    label: "Manager decision",
    field: () => "risk",
    group: "manager",
    move: () => "Message Manager",
  },
  TRIAGE_REVIEW: {
    label: "Signal review",
    field: () => "attention",
    group: "signal",
    move: () => "Review the queue",
  },
};
export const kind = (t: string): Kind =>
  KIND[t] ?? {
    label: t,
    field: () => "neutral",
    group: "company",
    move: (a) => clip(firstSentence(a.next_step), 5),
  };

export const firstSentence = (s: string) => s.match(/^(.+?[.!?])(\s|$)/)?.[1] ?? s;
/** A few words, cut at a clause boundary when possible — the full text stays under Details. */
export function clip(s: string, words = 6) {
  const head = s.split(/\s+[—–-]\s+|;\s+|:\s+|\.\s+/)[0].replace(/[.;:]$/, "");
  const w = head.split(/\s+/);
  return w.length <= words ? head : `${w.slice(0, words).join(" ")}…`;
}

/** Name + one short reason, from the action's own fields (no new judgement). */
export function headline(a: Action): { name: string; reason: string } {
  const ev = a.title.match(
    /^Decide on (.+?) \((\d{4})-(\d{2})-(\d{2}),\s*([^)]+)\)$/,
  );
  if (ev) {
    const d = new Date(Number(ev[2]), Number(ev[3]) - 1, Number(ev[4]));
    return {
      name: ev[1],
      reason: `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })} · ${ev[5]}`,
    };
  }
  if (a.type === "CASE_READY") {
    const n = a.title.match(/(\d+) human decision/)?.[1];
    return {
      name: a.subject || a.title.split(" — ")[0],
      reason: n
        ? `${n} decision${n === "1" ? "" : "s"} for you`
        : "Case prepared",
    };
  }
  if (a.type === "ASK_OMAR_CONFLICT")
    return {
      name: clip(asRole(a.title).replace(/^Ask Manager about /, ""), 6),
      reason: "Manager confirms if investable",
    };
  if (a.type === "NATIVE_INTEL")
    return {
      name: a.subject || a.title.split(" — ")[0],
      reason: a.title.split(" — ")[1] ?? "New early venture",
    };
  if (a.type === "SCOUT00_CYCLE")
    return {
      name: a.subject || a.title.split(" — ")[0],
      reason: a.title.split(" — ")[1] ?? "Signals ready",
    };
  if (a.type === "TRIAGE_REVIEW")
    return {
      name: clip(a.title.replace(/^Triage:\s*/, ""), 6),
      reason: "Your judgment, not the machine's",
    };
  return {
    name: a.subject || clip(a.title, 6),
    reason: clip(firstSentence(a.why), 6),
  };
}

export function plural(n: number, one: string, many = one + "s") {
  return `${n} ${n === 1 ? one : many}`;
}

/** Company facts for a mission, joined from the pipeline the page already caches (no new judgement, no new call). */
export type Company = {
  slug: string;
  company: string;
  one_liner?: string;
  why_now_text?: string;
  why_project_a?: string;
  status?: string;
  sc: { verified: number; missing: string[]; fully_verified?: boolean };
  op?: { status: string; source: string };
};

export function companyOf(a: Action, signals: Company[]): Company | undefined {
  const slug = a.link.match(/[?&]company=([^&]+)/)?.[1];
  return signals.find((e) => (slug && e.slug === decodeURIComponent(slug)) || (!!a.subject && e.company === a.subject));
}

export const short = (s: string | undefined, words = 14) => {
  const t = firstSentence(asRole(s ?? "").trim()).replace(/[.;]$/, "");
  const w = t.split(/\s+/);
  return w.length <= words ? t : `${w.slice(0, words).join(" ")}…`;
};
export const sentence = (s: string) => {
  const t = s.replace(/_/g, " ").trim().toLowerCase();
  return t ? t[0].toUpperCase() + t.slice(1) : "";
};

export type Mission = {
  a: Action;
  k: Kind;
  name: string;
  line: string;
  whyNow: string;
  unknown: string;
  state: string;
  score?: number;
};

export function mission(a: Action, signals: Company[]): Mission {
  const k = kind(a.type);
  const h0 = headline(a);
  const name = asRole(h0.name.charAt(0).toUpperCase() + h0.name.slice(1));
  const e = companyOf(a, signals);
  const op = e?.op && e.op.source !== "score band" ? asRole(sentence(e.op.status)) : "";
  return {
    a,
    k,
    name,
    line: e?.one_liner ? short(e.one_liner, 12) : asRole(h0.reason),
    // why NOW: the company's own why-now / why-it-matters; a prepared case without one says what changed (the
    // backend's "Recommended next action: …" is the move, not the reason, so it never fills this column)
    whyNow: short(
      e?.why_now_text || e?.why_project_a || (a.type === "CASE_READY" ? `Case prepared — ${h0.reason}` : a.why.replace(/^Recommended next action:\s*/, "")),
      11,
    ),
    unknown: e ? (e.sc.missing.length ? `Unverified: ${e.sc.missing.join(", ")}` : "Core facts verified") : "",
    state: op || k.label,
    score: e?.sc.verified,
  };
}
