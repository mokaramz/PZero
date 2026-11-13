import { cx } from "@/lib/format";
import { FLOW_W, FLOW_Y, flowLabel, flowPath, flowStages, flowXs } from "../model/flow";
import type { Candidate } from "../model/types";
import styles from "../Home.module.css";

/**
 * SIGNAL → DECISION (../model/flow): not a chart, a journey. The path draws once and the stages appear in sequence
 * (≈ 0.6 s), then everything is still; reduced motion shows the final state at once.
 */
export function DecisionFlow({ candidates, review, manager, decided }: { candidates: Candidate[]; review: number; manager: number; decided: number }) {
  const stages = flowStages(candidates, review, manager, decided);
  const xs = flowXs(stages.length);
  const y = FLOW_Y;
  return (
    <figure className={styles.flow} data-testid="desk-flow" data-signature="data">
      <svg viewBox={`0 0 ${FLOW_W} 44`} role="img" aria-label={flowLabel(stages)} className={styles.flowSvg}>
        <path className={cx(styles.flowPath, "pz-trace")} d={flowPath(xs, y)} pathLength={1} strokeDasharray="1" strokeDashoffset="1" />
        {stages.map((st, i) => (
          <g key={st.key} className={styles.flowStage} data-stage={st.key} style={{ animationDelay: `${80 + i * 110}ms` }}>
            <circle cx={xs[i]} cy={y} r={st.key === "decision" ? 8 : 6.5} className={styles.flowNode} />
            {st.key !== "decision" && <circle cx={xs[i]} cy={y} r={2.2} className={styles.flowDot} />}
          </g>
        ))}
      </svg>
      <ol className={styles.flowStages} aria-hidden>
        {stages.map((st, i) => (
          <li key={st.key} data-stage={st.key} className={styles.flowStage} style={{ animationDelay: `${80 + i * 110}ms` }}>
            <b>{st.n}</b>
            <span>{st.label}</span>
            <em>{st.hint}</em>
          </li>
        ))}
      </ol>
      <figcaption>Today's operating flow · signals to decisions</figcaption>
    </figure>
  );
}
