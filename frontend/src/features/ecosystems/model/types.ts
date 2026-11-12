/** The Ecosystems payloads (review 022) — the old `/api/city_registry`, `/api/eco` and `/api/coverage` bodies, unchanged,
 *  under new paths (see ../api). */

export type RegistryCity = {
  name: string;
  curated: boolean;
  country?: string;
  travel_hours?: number | null;
  coverage: { startups: number; events: number; people: number; institutions: number; last_refresh?: string };
  status: { startups: string; events: string; people: string; institutions: string };
};

export type CityRegistry = { cities: RegistryCity[]; curated_count: number; detected_count: number; note: string };

export type Org = { name: string; kind: string; city: string; lat?: number; lng?: number; why: string; url: string };

export type CityPage = {
  city: string;
  travel_hours: number | null;
  note?: string;
  startups: Array<{ slug: string; company: string; one_liner?: string; stage?: string; sent?: string | boolean; score: number; verified?: boolean }>;
  events_upcoming: Array<{ id: string; name: string; start?: string; type_label?: string; score: number | null }>;
  events_past?: unknown[];
  people: Array<{ id: string; name: string; role?: string; company?: string; next_action?: string }>;
  orgs: Org[];
};

/** HEALTHY / PARTIAL / GAP / UNKNOWN — any other state the server sends is shown as-is, neutral. */
export type CovState = string;

export type CovCandidate = { id: string; name: string; url: string; access_mode?: string; access_limitations?: string; source_type?: string; status?: string };

export type CovSource = { id: string; name: string; origin: string; retrieved: boolean; productive: boolean; last_ok?: string; failing?: boolean; declared_by: string };

export type CovFamily = {
  state: CovState;
  why: string;
  configured: number;
  retrieved: number;
  productive: number;
  sources: CovSource[];
  candidates?: CovCandidate[];
};

export type CovEcosystem = {
  id: string;
  city: string;
  country: string;
  country_name?: string;
  region?: string;
  overall: CovState;
  label: string;
  families: Record<string, CovFamily>;
  families_covered: string[];
  families_missing: string[];
  last_successful_retrieval?: string;
  audit?: { status?: CovState; ecosystem?: string; blind_spot?: string; source?: string };
};

/** `[family id, family label]`, in the server's order. */
export type FamilyDef = [string, string];

export type NewEcosystem = { place: string; country?: string; signals: number; kinds: string[]; examples: string[]; action: string };

export type Coverage = {
  generated?: string;
  families: FamilyDef[];
  ecosystems: CovEcosystem[];
  counts: Record<string, number>;
  sources_declared: number;
  sources_with_override: number;
  registry_size: number;
  candidates?: { total?: number; adopted?: number };
  new_ecosystems?: NewEcosystem[];
  note: string;
  labels: Record<string, string>;
};

/** `POST ecosystems/coverage/adopt` — a success (`already` when the candidate was adopted before); a refusal is
 *  `{ok:false, error}` and reaches the UI as a failure. */
export type AdoptResult = { ok?: boolean; already?: boolean; source_id?: string; note?: string; error?: string };
