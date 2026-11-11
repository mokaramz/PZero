/**
 * Why an Events entry point is visible but does nothing yet. The writes arrived in review 016; only the network scan
 * of the event sources (`event_find`) waits for its own port (review 017). It keeps its old places — the "More" menu,
 * the source-health drawer and the empty state — disabled with this one-line reason.
 */
export const NOT_PORTED = {
  scan: "Scanning the event sources arrives with the event source scan port",
} as const;
