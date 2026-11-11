/**
 * Operator Focus primitives: the few things that matter first, everything else one deliberate click below.
 *   Level 1  DecisionCard — what is it, why it may matter, what can kill it, what is unknown, your move
 *   Level 2  <Disclosure level={2}> — decision evidence (founder, funding, traction, Analyst, Red Team, IC Chair)
 *   Level 3  <Disclosure level={3}> — full audit (raw claims, provenance, routing history, model outputs)
 * Inside a <DisclosureGroup> (components/attention) only one disclosure is open at a time.
 * Nothing is removed by these components: capped lists always offer the rest behind "N more".
 * Color is never the only signal — every field / dot carries a text label.
 */
export { Capped, type CappedProps } from "./Capped";
export { ConvergenceTrace } from "./ConvergenceTrace";
export { DecisionCard, type DecisionCardProps } from "./DecisionCard";
export { Disclosure, type DisclosureProps } from "./Disclosure";
export { FIELD_LABEL, fieldFor, type Field } from "./fields";
export { HighlightStrip, type Highlight } from "./HighlightStrip";
export { Kicker, type KickerTone } from "./Kicker";
export { initials } from "./initials";
export { Monogram } from "./Monogram";
export { MoveButton, type Move } from "./MoveButton";
export { PathTrace } from "./PathTrace";
export { StatusChip, type StatusTone } from "./StatusChip";
export { VerificationBar } from "./VerificationBar";
