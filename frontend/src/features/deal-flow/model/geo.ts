/**
 * Workspace routing on the client (protected; old `logic.ts`, from v1 `dashboard.py`).
 * Country / location TEXT first, then the country code, then the source's geo scope and tags. It intentionally differs
 * from the server's `workspace_of` (tags first) — changing either moves what Mohamed sees (review 009, deviation b).
 */
import type { ReportRow, WsGeos } from "./types";

export type Workspace = "eu" | "na" | "all" | "unk";
export type NaFilter = "both" | "us" | "ca";
export type Region = "eu" | "us" | "ca" | "unknown";

/** Fallback until the server's ws_geos answers (v1 RC1.2 constants). */
export const DEFAULT_WS_GEOS: WsGeos = { eu: ["DACH", "CH", "NORD", "BNL", "FR", "UK", "SEU", "EU"], na: ["US", "CA"], un: [] };

export const WS_LABEL: Record<Workspace, { strong: string; rest: string }> = {
  eu: { strong: "Core Project A sourcing", rest: " — Europe is the main market and the default workspace." },
  na: {
    strong: "Exceptional opportunity hunting",
    rest: " — Project A can do outstanding US/Canadian deals (Manager confirmed), so the bar here is higher: outliers only.",
  },
  all: { strong: "", rest: "All geographies mixed — explicit view; Europe remains the default workflow." },
  unk: {
    strong: "Unresolved geography",
    rest: " — the source is global/multi-geo and the item carries no location evidence; judge individually, nothing here defaults to Europe.",
  },
};

const EUROPE_TEXT =
  /\b(germany|deutschland|austria|österreich|switzerland|schweiz|liechtenstein|france|united kingdom|uk|england|scotland|wales|ireland|netherlands|belgium|luxembourg|denmark|sweden|norway|finland|iceland|spain|portugal|italy|greece|poland|czech|slovakia|hungary|romania|bulgaria|croatia|slovenia|serbia|estonia|latvia|lithuania|malta|cyprus|europe|eu)\b/i;
const US_TEXT =
  /\b(usa|u\.s\.a?\.?|united states|america)\b|,\s*(al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\b/i;
const CANADA_TEXT = /\b(canada|ontario|quebec|québec|british columbia|alberta|waterloo|toronto|montreal|vancouver)\b/i;
const EUROPE_CODE = /^(de|at|ch|fr|gb|ie|nl|be|lu|dk|se|no|fi|is|es|pt|it|gr|pl|cz|sk|hu|ro|bg|hr|si|ee|lv|lt|mt|cy)$/i;

export type Located = { country?: string; location?: string; geo_scope?: string; geo?: string[] };

export function region(c: Located): Region {
  const country = (c.country || "").trim();
  const text = `${c.country || ""} ${c.location || ""}`;
  if (US_TEXT.test(text) || /^(us)$/i.test(country)) return "us";
  if (CANADA_TEXT.test(text) || /^ca$/i.test(country)) return "ca";
  if (EUROPE_TEXT.test(text) || EUROPE_CODE.test(country)) return "eu";
  const scope = c.geo_scope || "country";
  const tags = c.geo || [];
  if (scope === "country") {
    if (tags.includes("US")) return "us";
    if (tags.includes("CA")) return "ca";
    return "eu";
  }
  if (scope === "region-eu") return "eu";
  return "unknown";
}

export function geoOk(c: Located, ws: Workspace, naf: NaFilter): boolean {
  const r = region(c);
  if (ws === "all") return true;
  if (ws === "unk") return r === "unknown";
  if (ws === "eu") return r === "eu";
  if (r !== "us" && r !== "ca") return false;
  if (naf === "us") return r === "us";
  if (naf === "ca") return r === "ca";
  return true;
}

/** Scan-report row belongs to the workspace (system rows and ALL-geo rows are shown everywhere). */
export function repInWS(row: ReportRow, ws: Workspace, geos: WsGeos): boolean {
  if (ws === "all") return true;
  const tags = row.geo || [];
  if (tags.includes("ALL") || row.tier === "system") return true;
  const set = ws === "na" ? geos.na : geos.eu;
  return tags.length ? tags.some((v) => set.includes(v)) : ws === "eu";
}

/** Undecided counts per workspace for the segment badges (not theme-filtered, as in v1). */
export function wsCounts(all: Array<Located & { decision: string }>): { eu: number; na: number; unk: number } {
  let eu = 0;
  let na = 0;
  let unk = 0;
  for (const c of all) {
    if (c.decision !== "new") continue;
    const r = region(c);
    if (r === "eu") eu++;
    else if (r === "us" || r === "ca") na++;
    else unk++;
  }
  return { eu, na, unk };
}

export const batchWs = (ws: Workspace): "eu" | "na" | "all" => (ws === "na" ? "na" : ws === "all" ? "all" : "eu");
