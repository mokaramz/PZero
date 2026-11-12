import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./FocusTabs.module.css";

export type FocusTab = { id: string; label: ReactNode; count?: number; content: ReactNode; hidden?: boolean };

/** Secondary areas of a page as quiet tabs — only the chosen one is mounted (the others are one click away).
 *  An unknown or hidden `value` falls back to the first shown tab; with no tab shown, nothing renders. */
export function FocusTabs({
  tabs,
  value,
  onChange,
  label,
  testId,
  className,
}: {
  tabs: FocusTab[];
  value: string;
  onChange: (id: string) => void;
  label: string;
  testId?: string;
  className?: string;
}) {
  const shown = tabs.filter((t) => !t.hidden);
  const cur = shown.find((t) => t.id === value) ?? shown[0];
  if (!cur) return null;
  return (
    <section className={cx(styles.tabs, className)} data-testid={testId ?? "focus-tabs"}>
      <div className={styles.tabList} role="tablist" aria-label={label}>
        {shown.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={t.id === cur.id}
            className={cx(styles.tab, t.id === cur.id && styles.tabOn)}
            onClick={() => onChange(t.id)}
            data-tab={t.id}
          >
            {t.label}
            {t.count !== undefined && <span className={styles.tabCount}>{t.count}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" className={cx(styles.tabPanel, "pz-reveal")} key={cur.id}>
        {cur.content}
      </div>
    </section>
  );
}
