import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { Icon, type IconName } from "../Icon";
import styles from "./focus.module.css";

export type Highlight = { icon: IconName; label: string; value?: ReactNode; hint?: ReactNode; tone?: "progress" | "risk" };

const hasValue = (x: Highlight) => x.value !== undefined && x.value !== null && x.value !== "";

/** Decision-relevant facts in one quiet strip (founders, funding, strongest signal, geography, last verified …).
 *  Empty fields are not shown — the layout never invents a value; nothing renders when all are empty. */
export function HighlightStrip({ items, testId, className }: { items: Highlight[]; testId?: string; className?: string }) {
  const shown = items.filter(hasValue);
  if (!shown.length) return null;
  return (
    <dl className={cx(styles.highlights, className)} data-testid={testId ?? "highlights"}>
      {shown.map((x) => (
        <div key={x.label} className={styles.highlight}>
          <Icon name={x.icon} size={18} className={styles.highlightIcon} />
          <div className={styles.highlightBody}>
            <dt>{x.label}</dt>
            <dd className={x.tone ? styles[`h_${x.tone}`] : undefined}>{x.value}</dd>
            {x.hint && <span className={styles.highlightHint}>{x.hint}</span>}
          </div>
        </div>
      ))}
    </dl>
  );
}
