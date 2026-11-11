/**
 * STAGE TRACE — the quiet header graphic of Conviction (approved mockups): scattered signals converge through a few
 * nodes into an ANALYSIS point (layers), then a single line runs to the destination (a forest target). Illustrative of
 * the workflow, never a fake metric: it shows no numbers; the accessible label carries the page's real counts. Drawn
 * once (≈ 0.6 s), then still; reduced motion shows the final state at once. Illustrative (data-illustrative), so it
 * never counts as the page's one data signature graphic (Conviction's convergence trace keeps that role).
 */
import { cx } from "@/lib/format";
import styles from "./StageTrace.module.css";

const DOTS: Array<[number, number, string]> = [
  [8, 22, "sand"], [18, 46, "steel"], [30, 10, "steel"], [36, 34, "sand"], [44, 58, "sage"], [56, 20, "sand"], [64, 44, "steel"],
];
const NODES: Array<[number, number, string]> = [
  [104, 26, "sage"], [118, 40, "sage"], [134, 32, "ring"], [128, 52, "ring"],
];

export function StageTrace({ label, stages, testId }: { label: string; stages?: [string, string, string]; testId?: string }) {
  const ay = 36;
  const ax = 214;
  const mx = 268;
  const tx = 318;
  return (
    <figure className={styles.trace} data-testid={testId ?? "stage-trace"} data-illustrative="true">
      <svg viewBox={`0 0 340 ${stages ? 80 : 66}`} role="img" aria-label={label}>
        {NODES.map(([x, y], i) => (
          <path
            key={`p${i}`}
            className={cx(styles.line, "pz-trace")}
            d={`M${x} ${y} C ${x + 40} ${y}, ${ax - 46} ${ay}, ${ax - 17} ${ay}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
            style={{ animationDelay: `${40 + i * 60}ms` }}
          />
        ))}
        {DOTS.slice(2, 6).map(([x, y], i) => (
          <path
            key={`f${i}`}
            className={cx(styles.line, styles.faint, "pz-trace")}
            d={`M${x} ${y} Q ${(x + NODES[i][0]) / 2} ${y}, ${NODES[i][0]} ${NODES[i][1]}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
          />
        ))}
        <path className={cx(styles.line, styles.strong, "pz-trace")} d={`M${ax + 17} ${ay} H${tx - 13}`} pathLength={1} strokeDasharray="1" strokeDashoffset="1" style={{ animationDelay: "300ms" }} />
        {DOTS.map(([x, y, t], i) => (
          <circle key={`d${i}`} cx={x} cy={y} r={3} className={styles.dot} data-tone={t} />
        ))}
        {NODES.map(([x, y, t], i) => (
          <circle key={`n${i}`} cx={x} cy={y} r={4.5} className={styles.node} data-tone={t} style={{ animationDelay: `${60 + i * 40}ms` }} />
        ))}
        <g className={styles.stage} style={{ animationDelay: "240ms" }}>
          <circle cx={ax} cy={ay} r={17} className={styles.analysis} />
          <path className={styles.glyph} d={`M${ax} ${ay - 7} l-8 4 8 4 8 -4 z M${ax - 8} ${ay + 1.5} l8 4 8 -4 M${ax - 8} ${ay + 5.5} l8 4 8 -4`} />
        </g>
        <circle cx={mx} cy={ay} r={4} className={cx(styles.mid, styles.stage)} style={{ animationDelay: "360ms" }} />
        <g className={styles.stage} style={{ animationDelay: "440ms" }}>
          <circle cx={tx} cy={ay} r={12} className={styles.target} />
          <circle cx={tx} cy={ay} r={6} className={styles.core} />
        </g>
        {stages && (
          <>
            <text x={118} y={76} textAnchor="middle" className={styles.text}>
              {stages[0]}
            </text>
            <text x={ax} y={76} textAnchor="middle" className={styles.text}>
              {stages[1]}
            </text>
            <text x={tx + 14} y={76} textAnchor="end" className={styles.text}>
              {stages[2]}
            </text>
          </>
        )}
      </svg>
    </figure>
  );
}
