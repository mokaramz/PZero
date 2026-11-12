import { cx } from "@/lib/format";
import { SPARK_H, SPARK_W, sparkPoints } from "./sparkPoints";
import styles from "./Sparkline.module.css";

/** A tiny trend line from REAL observations (at least 3), drawn once. Direction only — never a significance claim. */
export function Sparkline({ values, label, testId }: { values: Array<number | null | undefined>; label: string; testId?: string }) {
  const s = sparkPoints(values);
  if (!s) return null;
  const pts = s.points;
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg className={styles.spark} viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} role="img" aria-label={`${label}: ${s.values.join(", ")}`} data-testid={testId}>
      <path
        className={cx(styles.sparkLine, "pz-trace")}
        d={pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ")}
        pathLength={1}
        strokeDasharray="1"
        strokeDashoffset="1"
      />
      <circle cx={lx} cy={ly} r={2.4} className={styles.sparkEnd} />
    </svg>
  );
}
