import { cx } from "@/lib/format";
import styles from "./focus.module.css";

const W = 300;

/** A real relationship chain drawn once (e.g. Smooth Operator → introducer → founder). Nothing without a real path. */
export function PathTrace({ nodes, testId }: { nodes: string[]; testId?: string }) {
  const ns = nodes.map((n) => n.trim()).filter(Boolean);
  if (ns.length < 2) return null;
  const step = (W - 24) / (ns.length - 1);
  return (
    <figure className={styles.path} data-testid={testId ?? "path-trace"} data-signature="data">
      <svg viewBox={`0 0 ${W} 44`} role="img" aria-label={`Introduction path: ${ns.join(" → ")}`}>
        <path className={cx(styles.traceLine, "pz-trace")} d={`M12 16 H${W - 12}`} pathLength={1} strokeDasharray="1" strokeDashoffset="1" />
        {ns.map((n, i) => (
          <g key={n + i}>
            <circle cx={12 + i * step} cy={16} r={i === ns.length - 1 ? 5 : 3.5} className={i === ns.length - 1 ? styles.traceTarget : styles.traceSource} />
            <text x={12 + i * step} y={38} textAnchor={i === 0 ? "start" : i === ns.length - 1 ? "end" : "middle"} className={styles.traceLabel}>
              {n.length > 18 ? `${n.slice(0, 17)}…` : n}
            </text>
          </g>
        ))}
      </svg>
    </figure>
  );
}
