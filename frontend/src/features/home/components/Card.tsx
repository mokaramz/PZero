import type { ReactNode } from "react";

import { Icon, type IconName } from "@/components/Icon";
import { cx } from "@/lib/format";
import styles from "../Home.module.css";

/** One desk concept in its own container: an icon, a title, an optional line and right-hand link, then its rows. */
export function Card({
  title,
  icon,
  sub,
  label,
  testId,
  right,
  className,
  tone,
  children,
}: {
  title: string;
  icon: IconName;
  sub?: string;
  label: string;
  testId?: string;
  right?: ReactNode;
  className?: string;
  /** the card's meaning, shown as a soft header tint: focus (steel) · decision (sand) · positive (sage) · activity (slate) */
  tone?: "focus" | "decision" | "positive" | "activity";
  children: ReactNode;
}) {
  return (
    <section className={cx(styles.card, className)} aria-label={label} data-testid={testId} data-tone={tone}>
      <div className={styles.cardHead}>
        <Icon name={icon} size={18} className={styles.headIcon} />
        <h2>{title}</h2>
        {sub && <span className={styles.cardSub}>{sub}</span>}
        <span className="grow" />
        {right}
      </div>
      {children}
    </section>
  );
}
