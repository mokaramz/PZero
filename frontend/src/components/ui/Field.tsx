import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./ui.module.css";

/** A labelled form control: the label wraps the control, an optional hint sits under it. */
export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx(styles.field, className)}>
      <span className={styles.fieldLabel}>{label}</span>
      {children}
      {hint && <span className={styles.fieldHint}>{hint}</span>}
    </label>
  );
}
