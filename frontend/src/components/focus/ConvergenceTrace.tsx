import { cx } from "@/lib/format";
import styles from "./focus.module.css";

const ROW = 15;
const W = 260;

/**
 * CONVERGENCE TRACE — independent real inputs (sources, Scout 00 cycles, Native) drawn once into one company: the
 * signature Project Zero motion ("independent signals becoming one decision"). Renders NOTHING with fewer than two
 * real inputs — never fabricated. Lines draw once (~520 ms, staggered), then the graphic is still.
 */
export function ConvergenceTrace({ sources, target, testId }: { sources: string[]; target: string; testId?: string }) {
  const src = [...new Set(sources.map((s) => s.trim()).filter(Boolean))].slice(0, 4);
  if (src.length < 2) return null;
  const H = Math.max(src.length * ROW + 6, 40);
  const tx = W - 14;
  const ty = H / 2;
  return (
    <figure className={styles.trace} data-testid={testId ?? "convergence-trace"} data-signature="data">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${target}: ${src.length} independent inputs — ${src.join(", ")}`}>
        {src.map((s, i) => {
          const y = 3 + ROW / 2 + i * ROW;
          return (
            <g key={s}>
              <text x={0} y={y + 3.5} className={styles.traceLabel}>
                {s.length > 22 ? `${s.slice(0, 21)}…` : s}
              </text>
              <path
                className={cx(styles.traceLine, "pz-trace")}
                d={`M128 ${y} C 178 ${y}, 196 ${ty}, ${tx - 6} ${ty}`}
                pathLength={1}
                strokeDasharray="1"
                strokeDashoffset="1"
                style={{ animationDelay: `${60 + i * 70}ms` }}
              />
              <circle cx={126} cy={y} r={2.2} className={styles.traceSource} />
            </g>
          );
        })}
        <circle cx={tx} cy={ty} r={5} className={cx(styles.traceTarget, "pz-fade-late")} />
      </svg>
      <figcaption>{src.length} independent inputs converge</figcaption>
    </figure>
  );
}
