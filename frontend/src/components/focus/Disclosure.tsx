import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { useGroupedOpen } from "../attention/groupContext";
import { Icon, type IconName } from "../Icon";
import styles from "./focus.module.css";

export type DisclosureProps = {
  title: ReactNode;
  /** 2 = decision evidence, 3 = full audit (muted title, layers icon) */
  level?: 2 | 3;
  /** one-line summary on the right of the row */
  hint?: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  testId?: string;
  icon?: IconName;
  /** stable id inside a DisclosureGroup (single-open region) */
  groupKey?: string;
};

/** Level 2 (decision evidence) / level 3 (full audit) — collapsed by default, native <details> for keyboard + SR.
 *  The body is mounted only while open. */
export function Disclosure({ title, level = 2, hint, children, defaultOpen, className, testId, icon, groupKey }: DisclosureProps) {
  const [open, setOpen] = useGroupedOpen(!!defaultOpen, groupKey);
  return (
    <details
      className={cx(styles.disclosure, level === 3 && styles.audit, className)}
      open={open}
      onToggle={(e) => {
        const v = (e.currentTarget as HTMLDetailsElement).open;
        if (v !== open) setOpen(v);
      }}
      data-testid={testId}
    >
      <summary className={styles.summary}>
        <Icon name={icon ?? (level === 3 ? "layers" : "doc")} size={15} className={styles.summaryIcon} />
        <span className={styles.summaryTitle}>{title}</span>
        {hint && <span className={styles.summaryHint}>{hint}</span>}
        <Icon name="chevron" size={14} className={styles.summaryChevron} />
      </summary>
      {open && <div className={cx(styles.disclosureBody, "pz-reveal")}>{children}</div>}
    </details>
  );
}
