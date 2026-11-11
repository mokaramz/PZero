import { useCallback, useMemo, useState, type ReactNode } from "react";

import { cx } from "@/lib/format";
import { ToastContext, type ToastKind } from "./context";
import styles from "./Toast.module.css";

type ToastItem = { id: number; text: string; kind: ToastKind };

const VISIBLE_MAX = 4; // the newest four; an older one makes room
const SHOW_MS: Record<ToastKind, number> = { ok: 6000, info: 6000, error: 9000 };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const show = useCallback((text: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-(VISIBLE_MAX - 1)), { id, text, kind }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), SHOW_MS[kind]);
  }, []);
  const value = useMemo(() => ({ show }), [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.toasts} role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx(styles.toast, styles[`toast_${t.kind}`])}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
