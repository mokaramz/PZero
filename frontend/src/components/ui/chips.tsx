import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./ui.module.css";

export type SegmentedOption<T extends string> = { value: T; label: ReactNode; count?: number };

/** One-of-n choice as a row of chips (role=tablist). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<SegmentedOption<T>>;
  label?: string;
}) {
  return (
    <div className={styles.segmented} role="tablist" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          className={cx(styles.chip, o.value === value && styles.chipOn)}
          onClick={() => onChange(o.value)}
        >
          {o.label}
          {o.count !== undefined && <span className={styles.chipCount}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** A toggle chip; `on` is exposed as aria-pressed. */
export function Chip({ on, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { on?: boolean }) {
  return <button type="button" aria-pressed={on} className={cx(styles.chip, on && styles.chipOn, className)} {...rest} />;
}
