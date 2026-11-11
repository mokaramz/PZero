import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./focus.module.css";

export type StatusTone = "neutral" | "progress" | "attention" | "risk" | "machine" | "focus";

/** One meaningful state as a small quiet chip — the word carries the meaning, colour only supports it. */
export function StatusChip({ children, tone = "neutral", title, testId }: { children: ReactNode; tone?: StatusTone; title?: string; testId?: string }) {
  return (
    <span className={cx(styles.status, styles[`s_${tone}`])} title={title} data-testid={testId}>
      {children}
    </span>
  );
}
