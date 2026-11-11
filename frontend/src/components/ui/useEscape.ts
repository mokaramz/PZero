import { useEffect, useRef } from "react";

/**
 * Overlays stack: a Modal opened from inside a Drawer sits on top of it, and Escape closes only the TOPMOST
 * overlay. Each open overlay pushes a token; one window listener dispatches to the last one.
 */
const overlayStack: Array<{ close: () => void }> = [];
let escapeBound = false;

function onEscape(e: KeyboardEvent) {
  if (e.key !== "Escape" || !overlayStack.length) return;
  e.stopPropagation();
  overlayStack[overlayStack.length - 1].close();
}

export function useEscape(open: boolean, onClose: () => void) {
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    if (!open) return;
    if (!escapeBound) {
      window.addEventListener("keydown", onEscape);
      escapeBound = true;
    }
    const token = { close: () => closeRef.current() };
    overlayStack.push(token);
    return () => {
      const i = overlayStack.indexOf(token);
      if (i >= 0) overlayStack.splice(i, 1);
    };
  }, [open]);
}
