import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import styles from "./focus.module.css";

export type KickerTone = "attention" | "progress" | "risk" | "info";

/** A small uppercase label above a block. */
export function Kicker({ children, tone, className }: { children: ReactNode; tone?: KickerTone; className?: string }) {
  return <span className={cx(styles.kicker, tone && styles[`k_${tone}`], className)}>{children}</span>;
}
