/** The Map payloads (review 025): the old `/api/map`, `/api/geo_intel`, `/api/geo_ecosystem`, `/api/geo_search` and
 *  `/api/sourcing_day` bodies, unchanged, under new paths (see ../api). The one addition is `MapData.new_signals`
 *  (decision c), which the old page read from `/api/home`. */

export type MapStartup = {
  slug: string;
  company: string;
  lat: number;
  lng: number;
  stage: string;
  stage_label: string;
  score: number;
  verified: boolean;
  archetype: string;
  one_liner: string;
  location: string;
  funding: string;
  timing: string;
  sent_to_omar: string;
  conflict: string;
  why: string;
  founders: string;
};

export type MapEvent = {
  id: string;
  name: string;
  lat: number;
  lng: number;
  city: string;
  start: string;
  type: string;
  type_label: string;
  when?: { weekend?: boolean };
  score: number;
  band: string;
  why: string;
  url: string;
  deadline: string;
  organizer: string;
  audience: string | number;
  status: string;
  past: boolean;
};

/** A person pin carries no `city` in the old answer (decision e), so "People to meet there" never shows; the field is
 *  read when present, as before. */
export type MapPerson = {
  id: string;
  name: string;
  lat: number;
  lng: number;
  role: string;
  company: string;
  why: string;
  strength: string;
  potential: string;
  next_action: string;
  watch: boolean;
  city?: string;
};

export type MapOrg = {
  name: string;
  kind: string;
  city: string;
  lat: number;
  lng: number;
  why: string;
  url: string;
};

/** `GET map/pins`. */
export type MapData = {
  startups: MapStartup[];
  events: MapEvent[];
  people: MapPerson[];
  orgs: MapOrg[];
  home: { city: string; lat: number; lng: number };
  no_geo: string[];
  /** Deal Flow candidates with `decision == "new"` (decision c). */
  new_signals?: number;
};

export type Selection =
  | { kind: "startup"; id: string }
  | { kind: "event"; id: string }
  | { kind: "person"; id: string }
  | { kind: "org"; id: string }
  | { kind: "eco"; id: string };

export type Filters = {
  q: string;
  lyStart: boolean;
  lyEv: boolean;
  lyPpl: boolean;
  lyOrg: boolean;
  lyHub: boolean;
  time: string;
  dist: number;
  stage: string;
  evType: string;
  minS: number;
  minE: number;
  theme: string;
  status: string;
};

export type Mode = "opportunity" | "go" | "gaps" | "explore";

/** `GET map/intel` — ground sourcing & ecosystem intelligence (activity / visibility, never investment scores). */
export type GeoState = "VERY ACTIVE" | "INTERESTING" | "NORMAL" | "LOW SIGNAL" | "UNDER-COVERED";

export type GeoCoverage = {
  assessed: boolean;
  families: Record<string, string>;
  strong: number;
  weak: string[];
  visibility: string;
};

export type GeoTravel = {
  bucket: "NEARBY" | "DAY TRIP" | "OVERNIGHT";
  km: number;
  text: string;
};

export type GeoEco = {
  city: string;
  lat: number;
  lng: number;
  country: string;
  state: GeoState;
  early: number;
  late: number;
  companies: number;
  events: number;
  high_signal_events: number;
  scout: number;
  conviction: number;
  convergence: {
    converging: boolean;
    families: string[];
    family_labels: string[];
    signals: number;
    entities: number;
  };
  coverage: GeoCoverage;
  reasons: string[];
  travel: GeoTravel;
};

export type GeoIntel = {
  ecosystems: GeoEco[];
  counts: Record<string, number>;
  where_to_go: {
    ranked: Array<{ city: string; state: GeoState; why: string[]; travel: GeoTravel }>;
    note: string;
  };
  cards: Array<{ id: string; title: string; text: string; city: string }>;
  unplaced: Record<string, number>;
  home: { city: string };
  /** The old note; it may end with a sentence naming source-network candidates that could not be read. */
  note: string;
  legend: Record<string, string>;
  built_at: string;
  build_s?: number;
};

export type GeoCompany = {
  name: string;
  kind: string;
  pz_state: string;
  first_seen: string;
  stage: string;
  why: string;
  early: boolean;
  late: boolean;
  score: string;
  machine: string;
  scout: string;
  watch: boolean;
  news: string[];
  families: string[];
  /** `/conviction?company=<name>`, `/deal-flow?candidate=<id>`, `/scout-intake`, … (see ./links) */
  link: string | null;
  next_action: string;
  founders?: string[];
};

/** `GET map/ecosystem?city=` — the "Why here?" panel: the ecosystem summary, whose `companies`, `events` and `scout` counts the
 *  detail replaces with the lists. */
export type GeoDetail = Omit<GeoEco, "companies" | "events" | "scout"> & {
  why_here: string[];
  companies: GeoCompany[];
  people: Array<{
    label: string;
    role: string;
    org: string;
    why: string;
    relationship: string;
    next_action: string;
    link: string | null;
  }>;
  events: Array<{
    label: string;
    date: string;
    time: string;
    band: string;
    why: string;
    audience: string;
    registration: string;
    price: string;
    url: string;
    type?: string;
    link: string | null;
  }>;
  news: Array<{ headline: string; date: string; source: string; themes?: string[] | null }>;
  institutions: Array<{ name: string; kind: string; why: string; url: string }>;
  source_candidates: Array<{ name: string; state: string; family: string | null; url: string }>;
  scout?: GeoCompany[];
  next_best_action: string;
  note: string;
};

/** `GET map/search?q=` — cities, companies, people, events and institutions → the ecosystem they belong to. */
export type GeoSearch = {
  results: Array<{ kind: string; label: string; city: string; state?: string; link?: string | null }>;
};

/** `POST map/sourcing_day {city, date}` — a day plan, never stored. */
export type SourcingDay = {
  city: string;
  date: string;
  weekday: string;
  objective: string;
  travel: GeoTravel;
  before_you_go: Array<{ name: string; why: string; link: string | null }>;
  people: Array<{ name: string; role: string; org: string; relationship: string; why: string }>;
  stops: Array<{ time: string; what: string; why: string; kind: string; registration?: string; url?: string }>;
  events_other_days: Array<{ label: string; date: string }>;
  bring_back: string[];
  coverage_caveat: string[];
  note: string;
  empty: boolean;
};
