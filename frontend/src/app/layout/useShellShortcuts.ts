import { useEffect } from "react";

/** A key typed into a field is the operator's text, not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  return !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
}

/**
 * The shell's keyboard shortcuts:
 *   F            toggles focus mode (not while typing, not with a modifier or key repeat, not while a dialog is open)
 *   Ctrl/Cmd+K   opens global search
 */
export function useShellShortcuts({ onFocusKey, onSearchKey }: { onFocusKey: () => void; onSearchKey: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== "f" || e.ctrlKey || e.metaKey || e.altKey || e.repeat) return;
      if (isTyping(e.target)) return;
      if (document.querySelector("[role=dialog]")) return;
      e.preventDefault();
      onFocusKey();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFocusKey]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onSearchKey();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onSearchKey]);
}
