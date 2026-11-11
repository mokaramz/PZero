/**
 * Why an Events entry point is visible but does nothing yet (review 015, "Not in 015"). Each one keeps its old place
 * in the layout and is disabled with this one-line reason: every write waits for the event writes port (review 016),
 * the network scan of the event sources for its own port (review 017).
 */
export const NOT_PORTED = {
  status: "Choosing GO / MAYBE / SKIP and changing an event's status arrive with the event writes port",
  add: "Adding an event arrives with the event writes port",
  edit: "Editing an event and its notes arrives with the event writes port",
  verify: "Marking an event as verified arrives with the event writes port",
  lead: "Converting and dismissing event leads arrive with the event writes port",
  debrief: "The event debrief arrives with the event writes port",
  scout: "Adding, monitoring and ignoring Scout 00 suggestions arrive with the event writes port",
  scan: "Scanning the event sources arrives with the event source scan port",
} as const;
