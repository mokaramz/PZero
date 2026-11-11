import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "../Conviction.module.css";

/** Mono score number: provisional (amber) or verified (green). */
export function Score({ value, kind, size }: { value: number; kind: "prov" | "ver"; size?: "big" }) {
  return <span className={cx(styles[kind], size && styles[size])}>{value}</span>;
}

/** A quiet sub-heading inside a section (sentence case, no box). */
export function Sub2({ children }: { children: ReactNode }) {
  return <div className={styles.sub2}>{children}</div>;
}

/** A part whose data arrives with a later port: its heading stays, with the reason in place of the content. */
export function NotPortedPart({ title, reason, testId }: { title: ReactNode; reason: string; testId?: string }) {
  return (
    <div data-testid={testId} data-deferred="">
      <Sub2>{title}</Sub2>
      <p className="small faint">{reason}</p>
    </div>
  );
}
