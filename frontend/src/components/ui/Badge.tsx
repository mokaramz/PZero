import type { HTMLAttributes } from "react";

import { cx } from "@/lib/format";
import styles from "./ui.module.css";

export type Tone = "neutral" | "blue" | "green" | "amber" | "red" | "purple";

export function Badge({ tone = "neutral", className, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cx(styles.badge, styles[`tone_${tone}`], className)} {...rest} />;
}
