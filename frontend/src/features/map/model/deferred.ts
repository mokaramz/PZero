/**
 * What the Map shows for views that are not here (review 025, decisions b and d):
 * - Scout Intake was merged into Deal Flow: a `/scout-intake` link opens the Deal Flow candidate when the item names
 *   one, otherwise it shows as plain text with this reason;
 * - news and source-network candidates are read from the imported snapshot until their own ports (decision b).
 */
export const NOT_PORTED = {
  scoutIntake: "Scout Intake is merged into Deal Flow — this Scout 00 card has no Deal Flow candidate to open",
} as const;

export const SNAPSHOT_NOTE = "News and source candidates come from the imported snapshot until their own views are ported.";
