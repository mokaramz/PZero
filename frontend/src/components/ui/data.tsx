import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import type { Tone } from "./Badge";
import styles from "./ui.module.css";

export function Stat({ label, value, tone }: { label: ReactNode; value: ReactNode; tone?: Tone }) {
  return (
    <div className={styles.stat}>
      <div className={cx(styles.statValue, tone && styles[`text_${tone}`])}>{value}</div>
      <div className={styles.statLabel}>{label}</div>
    </div>
  );
}

export function KeyValue({ items }: { items: Array<[ReactNode, ReactNode]> }) {
  return (
    <dl className={styles.kv}>
      {items.map(([k, v], i) => (
        <div key={i} className={styles.kvRow}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}
