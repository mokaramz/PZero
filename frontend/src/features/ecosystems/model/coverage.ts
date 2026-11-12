/** Coverage intelligence's pure rules (the old CoveragePanel kept them inline). */
import type { Tone } from "@/components/ui";
import type { AdoptResult, CovEcosystem, CovFamily, CovState } from "./types";

/** The four states, in the summary's order. */
export const STATES = ["HEALTHY", "PARTIAL", "GAP", "UNKNOWN"] as const;

const TONE: Record<string, Tone> = { HEALTHY: "green", PARTIAL: "amber", GAP: "red" };

/** HEALTHY green, PARTIAL amber, GAP red; UNKNOWN, any other state and no state are neutral. */
export const stateTone = (st: CovState | undefined): Tone => TONE[st ?? ""] ?? "neutral";

/** The local filter: city, country name and region, case-insensitive; an empty filter keeps every ecosystem. */
export function filterEcosystems(list: CovEcosystem[], filter: string): CovEcosystem[] {
  const f = filter.toLowerCase();
  return list.filter((e) => !f || `${e.city} ${e.country_name} ${e.region}`.toLowerCase().includes(f));
}

/** The table header: the family label up to its first " /" ("Founder formation / talent exits" → "Founder formation"). */
export const familyShort = (label: string) => label.split(" /")[0];

/** A family cell's counters ("3 cfg · 2 ok · 1 prod"); a missing family counts zero. */
export const familyCounts = (f: CovFamily | undefined) => `${f?.configured ?? 0} cfg · ${f?.retrieved ?? 0} ok · ${f?.productive ?? 0} prod`;

/** How many of a family's sources the detail lists before "… n more". */
export const SOURCES_SHOWN = 8;

/** One configured source in the detail: "<name> [<origin>] — retrieved <when> · productive (<declared by>)". */
export function sourceLine(s: CovFamily["sources"][number]): string {
  return (
    `${s.name} [${s.origin}] — ${s.retrieved ? `retrieved ${s.last_ok || ""}` : "never retrieved"}` +
    `${s.productive ? " · productive" : " · no records"}${s.failing ? " · failing" : ""} (${s.declared_by})`
  );
}

/** The adopt toast, as before (an `already` answer has no note, so it ends in " — "). */
export const adoptMessage = (r: AdoptResult) => `Adopted as watcher ${r.source_id} — ${r.note || ""}`;
