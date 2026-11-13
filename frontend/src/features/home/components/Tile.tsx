import { Link } from "react-router-dom";

import { Icon, type IconName } from "@/components/Icon";
import styles from "../Home.module.css";

/** One orientation tile: a count that opens the page where it lives. */
export function Tile({ icon, n, label, to, tone }: { icon: IconName; n: number; label: string; to: string; tone: "blue" | "cocoa" | "slate" | "forest" }) {
  return (
    <Link className={styles.tile} data-tone={tone} to={to} role="listitem">
      <span className={styles.tileIcon}>
        <Icon name={icon} size={18} />
      </span>
      <span className={styles.tileN}>{n}</span>
      <span className={styles.tileLabel}>{label}</span>
    </Link>
  );
}
