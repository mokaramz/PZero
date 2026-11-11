/** A small Conviction set: every group, the score boundaries the client rules pin, a dropped entry and the meta tables. */
import type { CaseView } from "../model/case";
import type { Meta, Pipeline, Signal } from "../model/types";

export function sig(slug: string, prov: number, extra: Partial<Signal> = {}): Signal {
  return {
    slug,
    company: slug[0].toUpperCase() + slug.slice(1),
    status: "new",
    conflict: "none",
    one_liner: `What ${slug} does.`,
    location: "Berlin, Germany",
    discovery_source: "EU-Startups",
    discovery_date: "2026-10-01",
    earliness: "pre_seed",
    archetype: 1,
    scores: { founder: 15, venture_scale: 15, why_now: 10, taste: 10, insight: 10 },
    verified: { founders: false, traction: false, funding: false },
    founders: [{ name: `${slug} founder`, background: "ex-somewhere" }],
    next_action: `Call ${slug}`,
    sc: {
      provisional: prov,
      verified: Math.max(0, prov - 30),
      missing: ["founders", "traction", "funding"],
      fully_verified: false,
      verdict: prov >= 65 ? "INVESTIGATE" : "WATCH",
      timing_label: "timing unknown",
      timing_action: "",
    },
    ...extra,
  };
}

export function pipeline(): Pipeline {
  return {
    week: "2026-W46",
    signals: [
      sig("alpha", 70, {
        sources: ["https://tech.eu/a", "https://sifted.eu/b"],
        imq_eval: { state: "NOT YET IMQ", blockers: ["founders unverified"], route: "", verified_score: 40, reason: "", timing: { established: false } },
      }),
      sig("gamma", 62),
      sig("beta", 63),
      sig("held", 75, { op: { status: "WATCHING", action: "Re-check in March", why: "on hold", tone: "neutral", source: "human outcome", score_band: "INVESTIGATE" } }),
      sig("gate", 80, { conflict: "potential_conflict", twin: "Portfolio Co" }),
      sig("unclear", 66, { conflict: "unclear" }),
      sig("gone", 90, { status: "dropped" }),
    ],
  };
}

const ladder = (...steps: number[]): Array<[string, number]> => steps.map((p) => [`step ${p}`, p]);

export function meta(): Meta {
  return {
    archetypes: [
      { id: 1, name: "Vertical AI agent" },
      { id: 15, name: "Outlier" },
    ],
    ladders: {
      founder: ladder(0, 5, 10, 15, 20, 25),
      venture_scale: ladder(0, 5, 10, 15, 20),
      why_now: ladder(0, 5, 10, 15),
      taste: ladder(0, 5, 10, 15),
      insight: ladder(0, 5, 10),
    },
    earliness: { unknown: "Unknown", pre_company: "Pre-company", pre_seed: "Pre-seed", seed: "Seed" },
    timing: { unknown: "Unknown", raising_now: "Raising now" },
    conflict: { none: "None", similar: "Similar taste", complementary: "Complementary", potential_conflict: "Potential conflict", unclear: "Unclear" },
    penalties: { consumer: "Consumer (−20)", wrapper: "Thin wrapper (−10)" },
    tiers: { manual: "Manual — found by hand", announcement: "Announcement — public news" },
    portfolio: [{ name: "Portfolio Co", what: "Does things" }],
  };
}

/** An imported prepared case whose next move is a founder contact (a deferred move) with open decisions. */
export function preparedCase(): CaseView {
  return {
    state: "READY FOR MOHAMED",
    why: "prepared from public pages",
    prepared_at: "2026-11-01T10:00:00",
    steps: [{ step: "read", note: "3 pages" }],
    usd: 0.02,
    audit: [{ ts: "2026-11-01T10:00:00", actor: "machine", action: "case_prepare", result: "ok", human_confirmed: false }],
    card: {
      company: "Alpha",
      why_pz_cares: ["Strong technical founder"],
      known: [{ label: "Founders", text: "two named", state: "PUBLIC", evidence: [] }],
      unknown: [{ label: "Funding", text: "round size unknown", who: "the founder" }],
      contradictions: [],
      machine: { triage: null, analyst: null, red_team: null, reviewer: null, advisory: "advisory only" },
      brief: null,
      score: { provisional: 70, verified: 40, verdict: "INVESTIGATE", explain: "your scores", rubric: [] },
      blockers: ["founders unverified"],
      decisions: [
        { kind: "verify_founders", text: "Accept the founders evidence", action: { type: "verify", flag: "founders" } },
        { kind: "archetype", text: "Check the archetype", action: { type: "edit" } },
      ],
      more_decisions: [{ kind: "committee", text: "Hard case", action: { type: "committee", role: "chair" } }],
      next_action: { code: "CONTACT_FOUNDER", label: "Contact the founder", why: "Ready — the founder is reachable. Use the warm intro.", link: "" },
      archetype: { status: "OK", stored: "#1", why: "fits" },
      conflict: { state: "none", adjacent: [], rule: "Manager decides" },
      contact: { state: "NOT_CONTACTED", label: "Not contacted — nothing recorded", history: [] },
    },
  };
}
