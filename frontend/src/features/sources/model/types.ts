/** `GET sources` (review 021): the old `/api/sources` payload plus the fields the old page read from `/api/inbox`
 *  (`ws_geos`, `report`, `manual_sources`, `pages`, `feeds`), so the page makes one call. */
import type { ReportRow, WsGeos } from "@/features/deal-flow/model/types";

export type SourceQuality = {
  candidates_found?: number;
  attention_queue?: number;
  researched?: number;
  kept?: number;
  radar?: number;
  sent_to_omar?: number;
  omar_positive?: number;
  omar_negative?: number;
};

export type SourceFeedback = {
  adjustment?: number;
  reviewed?: number;
  active?: boolean;
  stats?: Record<string, unknown>;
  label?: string;
  reason?: string;
};

export type Source = {
  id: string;
  name: string;
  url?: string;
  kind?: string;
  parser?: string;
  geo?: string[];
  sectors?: string[];
  stage?: string;
  reliability?: string;
  freshness?: string;
  enabled: boolean;
  /** local "YYYY-MM-DD HH:MM", as before */
  last_scan?: string | null;
  last_ok?: string | null;
  last_result_count?: number | null;
  failures_in_row?: number;
  yield?: { kept?: number; research?: number; rejected?: number };
  geo_scope?: string;
  notes?: string;
  quality?: SourceQuality;
  feedback?: SourceFeedback;
};

export type ManualSource = { name: string; url: string; how: string };
export type WatchedPage = { name: string; url: string; location?: string; country?: string; archetypes: Array<number | string> };
export type Feed = { name: string; url: string };

/** geo → sector → weighted coverage */
export type Grid = Record<string, Record<string, number>>;

export type SourcesPayload = {
  sources: Source[];
  geos: string[];
  geo_label: Record<string, string>;
  sectors: string[];
  sector_label: Record<string, string>;
  potential: Grid;
  verified: Grid;
  cells?: unknown;
  feedback_label?: string;
  feedback_min_reviewed?: number;
  feedback_cap?: number;
  ws_geos?: WsGeos;
  report?: ReportRow[];
  manual_sources?: ManualSource[];
  pages?: WatchedPage[];
  feeds?: Feed[];
};

export type Health = "ok" | "warn" | "failed" | "off";
