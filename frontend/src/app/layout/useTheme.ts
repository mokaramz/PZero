import { useCallback, useState } from "react";

export const THEME_KEY = "pz.theme";
const SWITCH_MS = 260; // the colours ease only while the switch runs (theme-dark.css → data-theme-switching)

/** Light (default) / dark, remembered per browser; index.html applies it before the first paint. */
export function useTheme(): [boolean, () => void] {
  const [dark, setDark] = useState(() => document.documentElement.getAttribute("data-theme") === "dark");
  const toggle = useCallback(() => {
    const next = !dark;
    const root = document.documentElement;
    root.setAttribute("data-theme-switching", "");
    if (next) root.setAttribute("data-theme", "dark");
    else root.removeAttribute("data-theme");
    window.setTimeout(() => root.removeAttribute("data-theme-switching"), SWITCH_MS);
    try {
      localStorage.setItem(THEME_KEY, next ? "dark" : "light");
    } catch {
      /* private window: the switch still works for this session */
    }
    setDark(next);
  }, [dark]);
  return [dark, toggle];
}
