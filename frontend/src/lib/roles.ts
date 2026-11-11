/**
 * Project Zero's human and system roles (docs/design-system.md → "Roles"). The UI speaks in ROLES, not personal names:
 *   SMOOTH OPERATOR — the final human decision owner / primary operator
 *   MANAGER         — the investment-manager escalation: portfolio conflicts, handoff approval, important exceptions
 *   MACHINE         — automated Project Zero work
 *   SCOUT 00        — the external Chief Scout
 *   NATIVE SCOUT    — the internal structured scout
 *
 * Real personal names stay wherever identity is FACTUAL DATA (founders, investors, contacts, the relationship graph,
 * call participants, notes, feedback text, Scout packet contents, evidence, audit history) — never pass those through
 * `asRole`.
 */
export const ROLE = {
  operator: "Smooth Operator",
  manager: "Manager",
  machine: "Machine",
  scout00: "Scout 00",
  native: "Native Scout",
} as const;

const RULES: Array<[RegExp, string]> = [
  [/\bOmar[’']s\b/g, `${ROLE.manager}'s`],
  [/\bOmar\b/g, ROLE.manager],
  [/\bMohamed[’']s\b/g, `${ROLE.operator}'s`],
  [/\bMohamed\b/g, ROLE.operator],
  [/\bOMAR\b/g, ROLE.manager.toUpperCase()],
  [/\bWAITING FOR HUMAN\b/g, `WAITING FOR ${ROLE.operator.toUpperCase()}`],
  [/\b([Ww])aiting for human\b/g, `$1aiting for ${ROLE.operator}`],
  [/\bMOHAMED\b/g, ROLE.operator.toUpperCase()],
];

/** Role wording for SYSTEM-GENERATED labels only (next actions, states, mission titles, triage routes, notices). The
 *  backend still says "Omar" / "Mohamed" in a few computed labels; this maps them at display time without touching the
 *  backend (methodology, prompts, parity). Never call it on factual text. */
export function asRole(text: string | null | undefined): string {
  let s = String(text ?? "");
  for (const [rx, to] of RULES) s = s.replace(rx, to);
  return s;
}
