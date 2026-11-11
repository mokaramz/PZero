/** Payload types for the Events feature — derived from docs/api-contract/legacy/{events,event_health,wsig}.json and events.py. */

export type Band = "HIGH" | "MEDIUM" | "LOW" | "NOT ENOUGH INFORMATION" | string;
export type Tier = "HIGH-SIGNAL" | "NEEDS REVIEW" | "REJECTED" | string;

export type EventWhen = {
  start_date?: string;
  end_date?: string;
  start_time?: string;
  end_time?: string;
  tz?: string;
  multi_day?: boolean;
  weekend?: boolean;
  ongoing?: boolean;
  group?: "weekend" | "next7" | "later" | "undated" | "past" | string;
  days_until?: number | null;
};

export type AssessmentFactor = { dimension: string; band: Band; evidence: string[]; passage?: string; passage_field?: string };

export type Assessment = {
  founder?: Band;
  project_a?: Band;
  networking?: Band;
  confidence?: string;
  source_data?: string;
  passage?: string;
  passage_field?: string;
  relevance_status?: string;
  factors?: AssessmentFactor[];
};

export type Price = { amount?: number | string | null; low?: number | string | null; high?: number | string | null; currency?: string; availability?: string; waitlist_url?: string };

export type EventAction = { state?: "open" | "unknown" | "sold_out" | "waitlist" | string; label?: string; url?: string; recommendable?: boolean };

/** Event Score shown for an event: evidence ordering (human=false) or the operator's own ladder score (human=true). */
export type EventSc = {
  total: number | null;
  band: string;
  human?: boolean;
  why?: string;
  /** [label, points, max, ladder text] */
  evidence: Array<[string, number, number, string]>;
};

export type EventRecord = {
  id: string;
  name: string;
  type?: string;
  organizer?: string;
  start?: string;
  end?: string;
  city?: string;
  venue?: string;
  url?: string;
  registration_url?: string;
  deadline?: string;
  price?: Price | string | null;
  price_state?: string;
  audience?: string;
  audience_estimate?: string | number;
  domains?: string;
  notes?: string;
  status?: "new" | "planned" | "attended" | "skipped" | string;
  score_parts?: Record<string, number | null> | null;
  sources?: Array<{ source: string; url?: string; added?: string }>;
  format?: string;
  route?: string;
  when?: EventWhen;
  unknowns?: string[];
  assessment?: Assessment;
  eligibility?: { tier?: Tier; label?: string; reasons?: string[] };
  rank_score?: number | null;
  rank_factors?: Array<{ factor: string; points: number }>;
  travel_hours?: number | null;
  action?: EventAction;
  sc: EventSc;
  past?: boolean;
  days_until?: number | null;
  /** readable geography (backend event_place.place): label for the card, area_label for the filter */
  place?: EventPlace;
  /** themes evidenced in the event's own text — display and filtering only */
  themes?: string[];
  /** Scout 00's recommendation when it reported this event (read-only) */
  scout?: ScoutView | null;
  human_verified?: boolean;
};

export type EventPlace = { city: string; area: string; country: string; country_name: string; label: string; area_label: string };

export type ScoutView = { p_class: string; ev_class: string; why: string; action: string; cycles: string[] };

/** A Scout 00 event recommendation still open in Scout Intake (NEW / MONITOR), merged across cycles. */
export type ScoutReport = ScoutView & {
  key: string;
  name: string;
  date: string;
  days_until: number | null;
  city: string;
  place: EventPlace;
  url: string;
  report_ids: string[];
  statuses: string[];
  themes: string[];
  tracked_event_id: string;
  travel_hours?: number | null;
};

export type EventLead = {
  id: string;
  title: string;
  date?: string;
  city?: string;
  url?: string;
  source?: string;
  type?: string;
  confidence?: string;
  detected_on?: string;
  note?: string;
};

export type DimDef = { label: string; max: number; ladder: Array<[number, string]> };

export type EventsPayload = {
  events: EventRecord[];
  leads: EventLead[];
  weekend_window?: [string, string];
  today?: string;
  types: Record<string, string>;
  dims: Record<string, DimDef>;
  dim_order: string[];
  manual_sources?: Array<{ name: string; url: string; how: string }>;
  pages?: string[];
  ics_count?: number;
  scout_reports?: ScoutReport[];
  source_count?: Record<string, number>;
};

export type HealthSource = {
  name: string;
  url?: string;
  city?: string;
  kind?: string;
  status?: "ok" | "failed" | string;
  raw?: number;
  future?: number;
  ingested?: number;
  accepted?: number;
  review?: number;
  past?: number;
  dups?: number;
  last_ok?: string;
  note?: string;
  route?: string;
};

export type EventHealthPayload = {
  scan_time?: string;
  note?: string;
  totals?: Record<string, number | undefined>;
  sources?: HealthSource[];
};

export type EventFindResult = {
  added: number;
  accepted?: number;
  dropped_past: number;
  dropped_dupe: number;
  health?: EventHealthPayload;
  report: Array<{ source: string; status: string; kind?: string; note: string }>;
};

export type WsigItem = {
  id: string;
  name: string;
  city?: string;
  start?: string;
  weekend?: boolean;
  type_label?: string;
  event_score: number | null;
  band?: string;
  rank: number | null;
  reason?: string;
  extra?: string;
  url?: string;
  deadline?: string;
  contacts?: string[];
  priority?: string;
};

export type WeekendStep = {
  when?: string;
  what: string;
  why?: string;
  score?: number | null;
  url?: string;
  time?: string;
  end_time?: string;
  venue?: string;
  city?: string;
  format?: string;
  price_state?: string;
  price?: Price;
  registration_url?: string;
  action?: EventAction;
  organizer?: string;
  confidence?: string;
  unknowns?: string[];
  objective?: string;
  research_first?: string[];
};

export type WeekendMission = {
  city: string;
  travel_hours: number | null;
  strength?: string;
  unknowns?: string[];
  plan: WeekendStep[];
  expected: string;
};

/** Minimal slice of /api/people used here (people to meet at an event's city). */
export type PeopleSlice = { people: Array<{ id: string; name: string; role?: string; location?: string }> };
