/**
 * The Founder Radar payloads (review 026a): the old `GET founder_radar` body and the old `radar_*` answers, unchanged,
 * now under `/api/founder-radar` (see ../api), including the scan and research answers (review 026b).
 */

export type Band = "HIGH" | "MEDIUM" | "LOW" | "NOT ENOUGH INFORMATION" | string;

export type Evidence = {
  category: string;
  claim: string;
  source: string;
  source_url?: string;
  retrieved?: string;
  activity_date?: string;
  field?: string;
};

export type Access = { kind?: "warm" | "cold" | "none" | string; label?: string; company_route?: boolean; provenance?: string };

export type Signal = {
  bands?: Record<string, Band>;
  factors?: Record<string, unknown>;
  ordering?: number | null;
  ordering_factors?: Array<{ factor: string; points: number }>;
  founder_scorable?: boolean;
  access?: Access;
  queue_label?: string;
  recent_activity?: { recent?: boolean; date?: string; source?: string; reason?: string };
  recent_activity_used?: string;
  founder_eligibility?: { eligible?: boolean; kind?: string; claim_only?: boolean; evidence?: string[] };
  founder_status_class?: string;
  bucket?: string;
  missing?: string[];
};

export type StateChange = { from?: string; to: string; on: string; by?: string; note?: string };

export type Person = {
  id: string;
  name: string;
  role?: string;
  company?: string;
  location?: string;
  country?: string;
  region?: string;
  institutions?: string[];
  aliases?: string[];
  profile_urls?: string[];
  linkedin?: string;
  provenance?: string;
  provenance_label?: string;
  connection_source?: string;
  linkedin_connected_on?: string;
  import_date?: string;
  identity_status?: string;
  identity_evidence?: string[];
  founder_status?: string;
  founder_potential?: string;
  name_attributed?: boolean;
  radar_state?: string;
  relationship_strength?: string;
  relationship_owner?: string;
  why_surfaced?: string;
  why_interesting?: string;
  last_signal?: string;
  last_observed?: string;
  updated?: string;
  sources?: Array<{ source: string; source_id?: string; url?: string }>;
  evidence?: Evidence[];
  state_history?: StateChange[];
  machine_research?: string;
  human_judgment?: string;
  companies?: string[];
  events?: string[];
  ecosystems?: string[];
  intro_route?: string;
  introduced_by_name?: string;
  opportunities?: Array<{ name: string; status: string }>;
  boardy?: { status?: string; brief?: string };
  signal?: Signal;
  proposed_identity?: { name: string; url?: string; source?: string } | null;
  promotion_block?: string | null;
  scout_identity_review?: { ready?: boolean; intake_item_id?: string } | null;
};

export type CompanyFounder = {
  id: string;
  name: string;
  role?: string;
  identity_status?: string;
  bucket?: string;
  name_attributed?: boolean;
  claimed_name?: string;
  claimed_aliases?: string[];
  handle_only?: boolean;
};

export type Company = {
  key: string;
  name: string;
  domain: string;
  domain_source?: string;
  founders: CompanyFounder[];
  description?: string;
  founded?: string;
  status?: string;
  stage?: string;
  funding?: string;
  verified_facts?: Record<string, { value?: unknown; activity_date?: string }>;
  claims?: Record<string, string>;
  project_a_fit?: string;
  early_stage_fit?: string;
  access?: string;
  access_routes?: Array<{ value: string; url: string }>;
  next_action?: string;
  next_missing?: string[];
  evidence: Evidence[];
  in_pipeline?: boolean;
  verified_field_count?: number;
  research_priority?: number;
  priority_factors?: Array<{ factor: string; points: number }>;
  priority_label?: string;
  priority_why?: string;
  proposals_pending?: number;
  researched?: boolean;
};

export type Lead = {
  id: string;
  name: string;
  company: string;
  role: string;
  location: string;
  standout: string;
  proof: Array<{ fact: string; url: string; source?: string; status?: string }>;
  why_now: string;
  project_a: string;
  linkedin: string;
  linkedin_search: string;
  contacts: string[];
  access: "warm" | "cold" | "none" | string;
  access_label?: string;
  unknowns: string[];
  next_action: string;
  machine_qualified: boolean;
  human_gold: boolean;
  identity_status?: string;
  company_key?: string;
};

export type CoverageRow = { name: string; role?: string; status?: string; note?: string; last_ok?: string };

export type HealthSource = {
  id?: string;
  name: string;
  kind?: string;
  status: string;
  raw?: number;
  new?: number;
  merged?: number;
  last_ok?: string;
  note?: string;
};

export type HealthRegion = {
  region: string;
  attempted?: number;
  ok?: number;
  failed?: number;
  ever_ok?: number;
  cities: Array<{ city: string; status?: string; attempted?: boolean; last_attempt?: string; last_ok?: string; next?: string }>;
};

export type Health = {
  scan_time?: string;
  totals?: Record<string, number>;
  sources?: HealthSource[];
  regions?: HealthRegion[];
  batch?: { size?: number; registry_size?: number };
  note?: string;
};

export type GeoCity = { city: string; country: string; people: number; status: string; last_attempt?: string; last_ok?: string };

export type FounderRadar = {
  people: Person[];
  companies?: Company[];
  leads?: { top: Lead[]; near: Lead[]; total_candidates?: number };
  queue_counts?: {
    company_leads?: number;
    claimed_founder_refs?: number;
    claim_bucket_people?: number;
    claim_people_without_lead?: number;
    reconciled?: boolean;
  };
  health?: Health;
  coverage?: Record<string, CoverageRow[]>;
  geo?: {
    regions: Array<{ region: string; people: number; cities: GeoCity[] }>;
    countries: Array<{ country: string; region: string; people: number; cities: number; attempted: number }>;
    cities: GeoCity[];
  };
  metrics?: Record<string, number | string | null>;
  states?: string[];
  network_states?: string[];
  buckets?: string[];
  regions?: string[];
};

export type Proposal = {
  id: string;
  field: string;
  value: unknown;
  passage: string;
  url: string;
  source_label: string;
  source_type?: string;
  source_rank?: number;
  activity_date?: string;
  retrieved?: string;
  confidence: string;
  status: string;
  person?: { name: string; role?: string; company?: string } | null;
  template_text?: boolean;
  why?: string;
  evidence_kind?: string;
  bound_person?: string;
  last_error?: string;
};

export type ProposalGroup = {
  key: string;
  field: string;
  value: unknown;
  best: Proposal;
  alternatives: Proposal[];
  hidden: number;
  disputed: boolean;
  status: string;
};

export type Proposals = {
  ok: boolean;
  groups: ProposalGroup[];
  recommended: string[];
  summary: {
    pages_retrieved?: number;
    pages_blocked?: number;
    facts_proposed?: number;
    founder_candidates?: number;
    hidden_duplicates?: number;
    recommended?: number;
    missing_gate?: string[];
    confirmed?: number;
  };
  history?: Array<{ on: string; proposal: string; from: string; to: string; person?: string }>;
  refreshed_at?: string;
};

export type ReviewResult = {
  ok: boolean;
  facts?: string[];
  identity_bound?: Array<{ name: string }>;
  still_pending?: string[];
  conflicts?: unknown[];
  refused?: string[];
  error?: string;
};

export type ImportResult = { ok: boolean; format: string; rows?: number; new?: number; merged?: number; skipped?: unknown[]; note?: string };

/** `POST founder-radar/action` → `{ok, person}`; a merge that needs confirmation answers `{ok:false, error, needs_confirmation}`. */
export type ActionResult = { ok: boolean; person?: Person; error?: string; needs_confirmation?: boolean };

/** `POST founder-radar/promote` → `{ok, person, error}` (the refusal "Resolve identity before promotion" has `person: null`). */
export type PromoteResult = { ok: boolean; person: Person | null; error?: string | null };

/** `POST founder-radar/boardy_brief` → the operator-controlled brief; nothing is sent. */
export type BoardyResult = { ok: boolean; brief: string; sent?: boolean; note: string };

/** The relationship facts asked by "Add to Network". */
export const PROMOTE_FIELDS = ["how", "introduced_by", "stage", "last_interaction", "next_action", "next_action_date", "channel", "notes"] as const;
export type PromoteForm = Record<(typeof PROMOTE_FIELDS)[number], string>;

/** What "Log founder call" hands to Founder Calls. */
export type CallContext = { person_id: string; name: string; company?: string; radar_key?: string };

/** `POST founder-radar/scan` → the new health report (synchronous). A server may answer `{started: true}` instead; the page
 *  then polls the radar until `health.scan_time` changes. */
export type ScanResult = Health & { ok?: boolean; started?: boolean };

/** `POST founder-radar/research {key | keys | (nothing: the next 5 un-researched), refresh}`. */
export type ResearchResult = {
  ok: boolean;
  researched: Array<{ key: string; name: string; ok?: boolean; error?: string; pages?: number; new?: number; proposals?: number }>;
};

/** `POST founder-radar/research_queue {batch}` → one resumable batch (`done` and `remaining` are counts). */
export type QueueResult = {
  ok?: boolean;
  processed?: Array<{ name: string; ok: boolean; pages?: number; proposals?: number; error?: string }>;
  done: number;
  remaining: number;
  failed?: Record<string, string>;
  skipped_no_domain?: string[];
  in_progress?: boolean;
  resume?: boolean;
};
