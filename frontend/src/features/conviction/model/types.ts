/**
 * Conviction payload types: `GET /api/conviction/pipeline` (the old `/api/pipeline` shape), `GET /api/conviction/meta`
 * (the old `/api/meta`) and the save body (review 011). Field names are the old ones on purpose: the protected client
 * rules in `logic.ts` read them as they are.
 */

export type Ladder = Array<[string, number]>;

export type Meta = {
  archetypes: Array<{ id: number; name: string; test?: string }>;
  ladders: { founder: Ladder; venture_scale: Ladder; why_now: Ladder; taste: Ladder; insight: Ladder };
  earliness: Record<string, string>;
  timing: Record<string, string>;
  conflict: Record<string, string>;
  penalties: Record<string, string>;
  tiers: Record<string, string>;
  portfolio: Array<{ name: string; what: string }>;
};

export type Founder = { name: string; role?: string; background?: string };
export type Verified = { founders?: boolean; traction?: boolean; funding?: boolean };
export type Scores = { founder?: number; venture_scale?: number; why_now?: number; taste?: number; insight?: number };

export type Sc = {
  provisional: number;
  verified: number;
  missing: string[];
  fully_verified: boolean;
  verdict: string;
  outlier_ok?: boolean;
  breakdown?: Record<string, number>;
  timing_label: string;
  timing_action: string;
};

export type ImqEval = {
  state: string;
  blockers: string[];
  route: string;
  verified_score: number;
  provisional_score?: number;
  fully_verified?: boolean;
  founder_identities?: Array<{ name: string; status: string; resolved?: boolean; person_id?: string }>;
  timing?: { established?: boolean; label?: string; date?: string; origin?: string; why?: string };
  conflict_status?: string;
  reason: string;
  persisted?: { qualified_at?: string; verified_score_at_qualification?: number; stale_since?: string };
  stale_reasons?: string[];
  never_auto_sends?: boolean;
};

export type ScoutProvenance = {
  scout_cycle_id: string;
  source_scouts?: string[];
  attention_state?: string;
  key_fact?: string;
  key_unknown?: string;
  evidence_urls?: string[];
};

export type BridgeFinding = { category: string; claim: string; url: string; date?: string; job_id: string };

export type OperatorStatus = {
  status: string;
  action: string;
  why: string;
  tone: "neutral" | "amber" | "red" | "green" | "blue";
  source: "human outcome" | "conflict gate" | "prepared case" | "score band";
  score_band: string;
};

export type Signal = {
  slug: string;
  company: string;
  status?: string;
  one_liner?: string;
  location?: string;
  country?: string;
  website?: string;
  discovery_source?: string;
  discovery_tier?: string;
  discovery_date?: string;
  discovery_status?: string;
  discovered_run?: string;
  archetype?: number;
  archetype_name?: string;
  emerging?: boolean;
  founders?: Founder[];
  scores?: Scores;
  earliness?: string;
  funding_status?: string;
  fundraising_timing?: string;
  penalties?: string[];
  twin?: string;
  conflict?: string;
  verified?: Verified;
  why_found?: string;
  why_project_a?: string;
  why_now_text?: string;
  founder_signal?: string;
  venture_scale_text?: string;
  bull?: string;
  bear?: string;
  verify_list?: string[] | string;
  next_action?: string;
  sources?: string[];
  sent_to_omar?: string;
  omar_feedback?: string;
  omar_outcome?: "positive" | "negative";
  days_old?: number;
  sc: Sc;
  /** ONE current operator state (backend case_prep.operator_status): human / case state > gate > next action > score band */
  op?: OperatorStatus;
  imq_eval?: ImqEval;
  scout_provenance?: ScoutProvenance[];
  bridge_findings?: BridgeFinding[];
};

export type Pipeline = { week?: string; signals: Signal[] };

/** Body of `POST /api/conviction/save` (Keep & score / Edit & verify / Add company / the checklist). `inbox_id` is the
 *  Deal Flow candidate a Keep decides; `slug` names the entry an edit changes. */
export type SaveBody = Partial<Omit<Signal, "sc" | "imq_eval" | "slug">> & { slug?: string; inbox_id?: string };

export const STATUSES = ["new", "contacted", "replied", "forwarded", "dropped"] as const;
