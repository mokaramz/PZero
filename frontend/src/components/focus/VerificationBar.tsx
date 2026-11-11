import styles from "./focus.module.css";

/** Verification progress (n of total real facts). Eases to a NEW real value when it changes; static on first view. */
export function VerificationBar({ n, of, label }: { n: number; of: number; label: string }) {
  const pct = of ? Math.max(0, Math.min(1, n / of)) : 0;
  return (
    <span className={styles.vbar} role="meter" aria-valuemin={0} aria-valuemax={of} aria-valuenow={n} aria-label={label}>
      <span className={styles.vbarFill} style={{ transform: `scaleX(${pct})` }} />
    </span>
  );
}
