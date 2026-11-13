import { Link } from "react-router-dom";

import { Icon, type IconName } from "@/components/Icon";
import styles from "../Today.module.css";

/** One orientation tile: a count that links to where it lives (an in-page anchor or a route). */
export function Tile({ icon, tone, n, label, to }: { icon: IconName; tone: string; n: number; label: string; to: string }) {
  const inner = (
    <>
      <span className={styles.tileIcon}>
        <Icon name={icon} size={16} />
      </span>
      <span className={styles.tileN}>{n}</span>
      <span className={styles.tileLabel}>{label}</span>
    </>
  );
  return (
    <li className={styles.tile} data-tone={tone}>
      {to.startsWith("#") ? <a href={to}>{inner}</a> : <Link to={to}>{inner}</Link>}
    </li>
  );
}
