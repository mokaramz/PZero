import type { ReactNode } from "react";

import styles from "../News.module.css";

/** A titled block of a story card (the old kicker + body). */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={styles.section}>
      <div className={styles.kicker}>{title}</div>
      <div>{children}</div>
    </div>
  );
}
