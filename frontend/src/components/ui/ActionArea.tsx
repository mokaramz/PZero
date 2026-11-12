import { useEffect, useRef, type ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./ActionArea.module.css";

/** One low-frequency action. `disabled` keeps it in the menu but inert; `hint` is its tooltip (the reason, when disabled). */
export type MoreItem = { label: ReactNode; onClick: () => void; testId?: string; disabled?: boolean; hint?: string };

/** Low-frequency actions behind one quiet "More ▾" — all still one click away, none competing with the primary.
 *  A native <details>: a click outside or Escape closes it, and choosing an item closes it before the item runs. */
export function MoreMenu({
  items,
  label = "More",
  testId,
  children,
  inline,
}: {
  items: MoreItem[];
  label?: string;
  testId?: string;
  children?: ReactNode;
  /** open in the flow (inside a scrolling rail) instead of as a floating menu */
  inline?: boolean;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = () => ref.current?.removeAttribute("open");
  useEffect(() => {
    const away = (ev: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(ev.target as Node)) close();
    };
    const esc = (ev: KeyboardEvent) => ev.key === "Escape" && close();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, []);
  if (!items.length && !children) return null;
  return (
    <details className={cx(styles.more, inline && styles.moreInline)} ref={ref} data-testid={testId ?? "more-actions"}>
      <summary className={styles.moreBtn}>{label}</summary>
      <div className={styles.morePanel} role="group" aria-label={label}>
        {items.map((it, i) => (
          <button
            key={i}
            type="button"
            className={styles.moreItem}
            disabled={it.disabled}
            title={it.hint}
            data-testid={it.testId}
            onClick={() => {
              close();
              it.onClick();
            }}
          >
            {it.label}
          </button>
        ))}
        {children}
      </div>
    </details>
  );
}

/** A region's contextual action area: ONE primary (filled navy, or none) + "More ▾" for everything else. */
export function ActionArea({ primary, more, className }: { primary?: ReactNode; more?: MoreItem[]; className?: string }) {
  return (
    <div className={cx(styles.actionArea, className)} data-action-area>
      {more && <MoreMenu items={more} />}
      {primary}
    </div>
  );
}
