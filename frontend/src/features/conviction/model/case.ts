/**
 * The prepared case (`GET /api/conviction/case?slug=`, the old `/api/case` shape). Read-only in 011: an imported case is
 * shown, a new one is never started. The endpoint may not exist yet — a 404 is the "not started" state.
 */

export type Ev = { url: string; label: string; source_type: string };
export type Fact = {
  label: string;
  text: string;
  state?: string;
  how?: string;
  who?: string;
  evidence?: Ev[];
};
export type Decision = {
  kind: string;
  text: string;
  action:
    | null
    | { type: "verify"; flag: string }
    | { type: "open"; link: string }
    | { type: "edit" }
    | { type: "reviewer" }
    | { type: "committee"; role: "chair" | "outside" }
    | { type: "outreach"; kind: string }
    | ({ type: "imq_trigger" } & WhyNow);
};
export type WhyNow = { kind: string; date: string; url: string; fact: string };
export type Brief = {
  source: string;
  why_exceptional: string;
  why_fail: string;
  disagreements: string[];
  verified: string[];
  unknown: string[];
  mohamed_decides: string;
  next_action: string;
  routing: string;
  confidence: string;
  human_conflict: string;
  contrarian?: {
    interpretation: string;
    still_false: string;
    suggests: string;
  } | null;
};
export type CommitteeRec = {
  at?: string;
  state?: string;
  model?: string;
  error?: string;
  review?: Record<string, unknown> | null;
};
export type Rubric = {
  key: string;
  label: string;
  max: number;
  yours: number;
  evidence: string[];
  machine: string | null;
};
export type Card = {
  company: string;
  why_pz_cares: string[];
  known: Fact[];
  unknown: Fact[];
  contradictions: Fact[];
  machine: {
    triage: { proposal: string; reasons: string[] } | null;
    analyst: {
      recommendation?: string;
      for: string[];
      against: string[];
      proposed_provisional?: number | null;
      at?: string;
      model?: string;
    } | null;
    red_team: { verdict?: string; summary?: string; at?: string } | null;
    reviewer: {
      at?: string;
      state?: string;
      review?: { verdict?: string; summary?: string };
    } | null;
    committee?: { chair?: CommitteeRec; outside?: CommitteeRec };
    run_note?: string;
    advisory: string;
  };
  brief?: Brief | null;
  score: {
    provisional: number;
    verified: number;
    verdict: string;
    explain: string;
    rubric: Rubric[];
  };
  blockers: string[];
  decisions: Decision[];
  more_decisions: Decision[];
  next_action: { code: string; label: string; why: string; link: string };
  archetype: { status: string; stored: string | null; why: string };
  conflict: { state: string; adjacent: string[]; rule: string };
  contact?: {
    state: string;
    label: string;
    history: Array<{
      kind: string;
      date: string;
      channel: string;
      note: string;
    }>;
  };
  human?: {
    calls: Array<{
      id: string;
      date: string;
      outcome: string;
      recommendation: string;
      next_action: string;
      observations: string;
    }>;
    last_outcome: string;
    omar: { outcome: string; feedback: string; at: string };
    hold: boolean;
    reasons: string[];
    reopen_evidence: string[];
    reopen_triggers: string[];
    label: string;
  };
};
export type CaseView = {
  state: string;
  why: string;
  prepared_at?: string;
  prepared_for?: string;
  card?: Card;
  steps: Array<{ step: string; note: string }>;
  usd: number;
  audit: Array<{
    ts: string;
    actor: string;
    action: string;
    result: string;
    human_confirmed: boolean;
  }>;
};
