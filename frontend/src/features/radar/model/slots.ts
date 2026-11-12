/** "Slot 2" / "Slots 2–8": the exact empty slots of a Radar section with `filled` of its `slots` taken. */
export function emptySlotsLabel(filled: number, slots: number): string {
  const first = filled + 1;
  return first === slots ? `Slot ${first}` : `Slots ${first}–${slots}`;
}
