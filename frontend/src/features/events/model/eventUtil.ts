/** Pure helpers shared by the Events views — each mirrors a v1 function (evFormat, costLine, evLevel …). The two small
 *  components of the old module (`Unk`, `When` — v1 evWhen) live in `components/When.tsx`. */
import type { Tone } from "@/components/ui";
import type { Assessment, EventRecord, Price } from "./types";

export const tierOf = (e: EventRecord) => e.eligibility?.tier || "NEEDS REVIEW";

export function tierTone(e: EventRecord): Tone {
  const t = tierOf(e);
  return t === "HIGH-SIGNAL" ? "green" : t === "NEEDS REVIEW" ? "amber" : "neutral";
}

/** Physical / Virtual / Hybrid — from the stored format, else inferred from text (labelled "(inferred)"). */
export function evFormat(e: EventRecord): string {
  const f = (e.format || "").toLowerCase();
  if (f && f !== "unknown") return f === "physical" ? "Physical" : f.charAt(0).toUpperCase() + f.slice(1);
  const t = `${e.venue || ""} ${e.notes || ""} ${e.name || ""}`.toLowerCase();
  if (/\bhybrid\b/.test(t)) return "Hybrid (inferred)";
  if (/\b(online|virtual|webinar|remote)\b/.test(t)) return "Virtual (inferred)";
  if (/\b(in person|on-site|onsite)\b/.test(t)) return "Physical (inferred)";
  return "";
}

export function costLine(e: EventRecord): string {
  const p = (e.price && typeof e.price === "object" ? e.price : {}) as Price;
  const st = e.price_state || "price unknown";
  if (st === "free") return "FREE";
  if (st === "sold out") return "SOLD OUT";
  if (st === "price range") return `${p.low ?? ""}–${p.high ?? ""} ${p.currency || ""}`;
  if (st === "paid") return `${p.amount ?? ""} ${p.currency || ""}`.trim();
  return "PRICE UNKNOWN";
}

/** Text shown in the price input — structured offers stay data unless the operator edits this field. */
export function priceText(p: EventRecord["price"]): string {
  if (!p) return "";
  if (typeof p === "string") return p;
  const cur = p.currency || "";
  if (p.low != null && p.low !== "" && p.high != null && p.high !== "") return `${p.low}–${p.high} ${cur}`.trim();
  if (p.amount != null && p.amount !== "") return `${p.amount} ${cur}`.trim();
  if (String(p.availability || "").toLowerCase().endsWith("soldout")) return "sold out";
  return "";
}

export function bandTone(band: string | undefined): Tone {
  return band === "HIGH" ? "green" : band === "MEDIUM" ? "amber" : band === "LOW" ? "red" : "neutral";
}

/** Band of an existing ladder value: HIGH ≥ 70 %, MEDIUM ≥ 40 % of the ladder maximum (v1 evLevel). */
export function ladderLevel(v: number | null | undefined, max: number): [string, Tone] {
  if (v == null) return ["NOT ENOUGH INFORMATION", "neutral"];
  if (v >= max * 0.7) return ["HIGH", "green"];
  if (v >= max * 0.4) return ["MEDIUM", "amber"];
  return ["LOW", "red"];
}

export function factorEvidence(a: Assessment | undefined, dim: string): string {
  const f = (a?.factors ?? []).find((x) => x.dimension === dim);
  if (f) return `evidence: ${f.evidence.join(", ")}`;
  return dim === "networking" ? "no explicit networking evidence — an organizer name alone is not networking value" : "no source evidence";
}

export function domainsOf(e: EventRecord): string[] {
  return String(e.domains || "")
    .split(/[,;/]/)
    .map((x) => x.trim())
    .filter(Boolean);
}

/** Stated-audience signal only (v1 legacy ladder "Audience" pill). */
export function audienceSignal(e: EventRecord): [string, Tone] {
  const t = `${e.audience_estimate || ""} ${e.notes || ""}`;
  if (/\b(investor|vc|lp)s?\b/i.test(t)) return ["INVESTOR-HEAVY (stated)", "amber"];
  if (/\bfounders?\b/i.test(t)) return ["FOUNDER-HEAVY (stated)", "green"];
  return ["NOT ENOUGH INFORMATION", "neutral"];
}

export const STATUS_LABEL: Record<string, string> = { planned: "GO", new: "MAYBE", skipped: "SKIP", attended: "ATTENDED" };

/** People whose location mentions the event city (v1 renderEventDetail `ppl`). */
export function peopleIn<T extends { location?: string }>(people: T[], city: string | undefined): T[] {
  if (!city) return [];
  const c = city.toLowerCase();
  return people.filter((p) => (p.location || "").toLowerCase().includes(c));
}

export function sortByStart(a: EventRecord, b: EventRecord): number {
  return (a.when?.start_date || "9999").localeCompare(b.when?.start_date || "9999") || (b.sc.total ?? 0) - (a.sc.total ?? 0);
}
