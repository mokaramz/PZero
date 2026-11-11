import { initials } from "./initials";
import styles from "./focus.module.css";

/** A neutral initials tile — Project Zero never invents a logo for a real company. */
export function Monogram({ name, size = 40 }: { name: string; size?: number }) {
  return (
    <span className={styles.monogram} style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }} aria-hidden>
      {initials(name)}
    </span>
  );
}
