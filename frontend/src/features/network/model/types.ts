/** Network payloads (review 013): the old `/api/people` and `/api/graph` shapes under `/api/network/*`. */

export type Person = {
  id: string;
  name: string;
  location?: string;
  company?: string;
  university?: string;
  role?: string;
  expertise?: string;
  why_interesting?: string;
  discovery?: string;
  introduced_by?: string;
  introduced_by_name?: string;
  chain?: string[];
  recommended?: string[];
  recommended_names?: string[];
  startups?: string[] | string;
  founder_potential?: string;
  linkedin?: string;
  x?: string;
  email?: string;
  github?: string;
  relationship_strength?: string;
  last_interaction?: string;
  last_checked?: string;
  next_action?: string;
  next_action_date?: string;
  notes?: string;
  created?: string;
  watch?: boolean;
  due?: boolean;
  days_since_touch?: number | null;
  radar_state?: string;
  boardy?: { status?: string };
  state_history?: Array<{ to?: string; on?: string }>;
  opportunities?: unknown[];
  intro_route?: string;
  contact_channel?: string;
  events?: unknown[];
};

/** GET network/people: the listing (due first, then stalest) and the two label tables of the form. */
export type PeoplePayload = {
  people: Person[];
  strengths: Record<string, string>;
  potential: Record<string, string>;
};

export type GraphNode = {
  id: string;
  name: string;
  role?: string;
  company?: string;
  founder_potential?: string;
  strength?: string;
  startups?: string[];
  watch?: boolean;
  children: GraphNode[];
};

export type GraphPayload = { forest: GraphNode[] };

/** A watched person as GET network/watchlist lists it (the listing row, filtered on `watch`). */
export type WatchPerson = Pick<Person, "id" | "name" | "role" | "company" | "why_interesting" | "linkedin" | "x" | "last_checked">;

/** The slice of GET conviction/pipeline that links a person's companies to their Conviction workspace. */
export type PipelineSlice = { signals?: Array<{ slug: string; company: string; sc?: { provisional?: number } }> };

/** POST network/person_save: the operator-edited fields (an add has no `id`). */
export type PersonSaveBody = Record<string, unknown> & { id?: string };
export type TalentedBody = { id: string; persons: Array<{ name: string; note: string }> };

/** Every operator-edited field the form posts (the old v1 set), plus `watch`; an edit adds `id`. */
export const PERSON_FIELDS = [
  "name",
  "location",
  "company",
  "role",
  "university",
  "expertise",
  "why_interesting",
  "discovery",
  "founder_potential",
  "relationship_strength",
  "last_interaction",
  "linkedin",
  "x",
  "startups",
  "email",
  "next_action",
  "next_action_date",
  "notes",
  "github",
] as const;
