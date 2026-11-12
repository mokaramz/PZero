/** The Map's colour tables, as before. Map data colours follow the design tokens (no red / yellow / violet): navy =
 *  strongest activity, steel = interest, light steel = normal, grey = low signal, cocoa = blind spot / limited
 *  visibility, forest = good visibility. */

export const STAGE_COLOR: Record<string, string> = {
  pre_company: "#2E7D32",
  grant_angel: "#4A90D9",
  pre_seed: "#4A90D9",
  seed: "#1F4E79",
  series_a_plus: "#9AA3AF",
  unknown: "#9AA3AF",
};

export const LAYER_COLOR = {
  startup: "#1F4E79",
  event: "#C77D2E",
  person: "#5B6577",
  uni: "#3D6B6B",
  hub: "#8A6D3B",
};

export const GEO_COLOR: Record<string, string> = {
  "VERY ACTIVE": "#1F2B3D",
  INTERESTING: "#2B5C9E",
  NORMAL: "#8FA6C4",
  "LOW SIGNAL": "#9AA3AF",
  "UNDER-COVERED": "#86664F",
};

export const VIS_COLOR: Record<string, string> = {
  GOOD: "#3A6A50",
  LIMITED: "#86664F",
  POOR: "#7A5A48",
  "NOT ASSESSED": "#9AA3AF",
};
