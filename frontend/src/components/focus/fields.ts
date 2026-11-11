/** Semantic card fields. One per card. */
export type Field = "neutral" | "frontier" | "industrial" | "energy" | "attention" | "risk" | "progress";

/** First match wins (order matters: frontier science before energy before industrial). */
const FIELD_RULES: Array<[Field, RegExp]> = [
  [
    "frontier",
    /quantum|photonic|semiconduct|chip|bio|life scien|materials|space|fusion|frontier|deep ?tech|scien|research|lab\b|neuro|compute/i,
  ],
  ["energy", /energy|grid|battery|manufactur|infrastructure|defen[cs]e|dual.use|mining|steel|chemical|hydrogen|nuclear/i],
  ["industrial", /climate|industrial|robot|automation|physical|agri|food|water|mobility|logistic|construction|aero|drone/i],
];

/** The thematic field of a company from its own description / theme words (presentation only — never a score). */
export function fieldFor(...texts: Array<string | null | undefined>): Field {
  const t = texts.filter(Boolean).join(" ");
  for (const [f, re] of FIELD_RULES) if (re.test(t)) return f;
  return "neutral";
}

export const FIELD_LABEL: Record<Field, string> = {
  neutral: "",
  frontier: "Frontier science",
  industrial: "Industrial / physical",
  energy: "Energy / infrastructure",
  attention: "Needs you",
  risk: "Risk",
  progress: "New intel",
};
