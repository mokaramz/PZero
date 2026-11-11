/**
 * FOCUS ARCHITECTURE primitives (docs/design-system.md → Focus architecture). Alive, not busy:
 *   Layer 1  Focus   — what needs attention now: one dominant anchor, one primary action per region
 *   Layer 2  Context — the selected item, on demand, in a right-hand ContextInspector
 *   Layer 3  Audit   — history, provenance, machine detail: collapsed (Disclosure inside a DisclosureGroup)
 * Nothing is removed by these components — everything they hide is one deliberate click away.
 */
export { ContextInspector, type ContextInspectorProps } from "./ContextInspector";
export { DisclosureGroup } from "./DisclosureGroup";
export { GroupedFilters, type GroupedFiltersProps } from "./GroupedFilters";
export { useGroupedOpen, type DisclosureGroupState } from "./groupContext";
