import { cx } from "@/lib/format";
import { flowLabel } from "../model/view";
import styles from "../Today.module.css";

/**
 * TODAY'S FLOW — Today's own graphic (approved mockup): scattered signals converge through a few nodes into REVIEW (a
 * filter) and on to the DECISION point. The counts are the page's real state — machine-handled signals · your
 * missions · decisions due (Manager + events); no invented "done" metric. Lines draw once, nodes appear in sequence
 * (≈ 0.6 s), then everything is still; reduced motion shows the final state at once.
 */
export function DayFlow({ missions, decisions, handled }: { missions: number; decisions: number; handled?: number }) {
  const label = flowLabel(missions, decisions, handled);
  // scattered signals (left), converging nodes (middle), review filter, decision point — fixed composition
  const dots: Array<[number, number, string]> = [
    [10, 40, "sand"],
    [22, 18, "sage"],
    [30, 58, "steel"],
    [42, 30, "sand"],
    [50, 72, "sage"],
    [58, 12, "steel"],
    [64, 48, "sand"],
  ];
  const nodes: Array<[number, number, string]> = [
    [96, 22, "ring"],
    [104, 60, "ring"],
    [134, 38, "sage"],
    [140, 70, "ring"],
  ];
  const fx = 214;
  const fy = 44;
  const tx = 314;
  return (
    <figure className={styles.flow} data-testid="today-flow" data-signature="data">
      <svg viewBox="0 0 352 96" role="img" aria-label={label} className={styles.flowSvg}>
        {/* paths: signals → nodes → review → decision */}
        {nodes.map(([x, y], i) => (
          <path
            key={`n${i}`}
            className={cx(styles.flowLine, "pz-trace")}
            d={`M${x} ${y} C ${x + 40} ${y}, ${fx - 50} ${fy}, ${fx - 17} ${fy}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
            style={{ animationDelay: `${60 + i * 60}ms` }}
          />
        ))}
        {dots.slice(1, 4).map(([x, y], i) => (
          <path
            key={`d${i}`}
            className={cx(styles.flowLine, styles.flowLineFaint, "pz-trace")}
            d={`M${x} ${y} Q ${(x + nodes[i % nodes.length][0]) / 2} ${(y + nodes[i % nodes.length][1]) / 2 + 6}, ${nodes[i % nodes.length][0]} ${nodes[i % nodes.length][1]}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
          />
        ))}
        <path
          className={cx(styles.flowLine, styles.flowLineStrong, "pz-trace")}
          d={`M${fx + 17} ${fy} H${tx - 15}`}
          pathLength={1}
          strokeDasharray="1"
          strokeDashoffset="1"
          style={{ animationDelay: "320ms" }}
        />
        <path className={cx(styles.flowArrow, "pz-fade-late")} d={`M${tx - 40} ${fy - 4} l5 4 -5 4`} />
        {dots.map(([x, y, t], i) => (
          <circle key={`dot${i}`} cx={x} cy={y} r={3.2} className={styles.flowDot} data-tone={t} style={{ animationDelay: `${i * 30}ms` }} />
        ))}
        {nodes.map(([x, y, t], i) => (
          <circle key={`node${i}`} cx={x} cy={y} r={5.5} className={styles.flowNode} data-tone={t} style={{ animationDelay: `${80 + i * 50}ms` }} />
        ))}
        {/* review: a filter */}
        <g className={styles.flowStage} style={{ animationDelay: "260ms" }} data-step="review">
          <circle cx={fx} cy={fy} r={17} className={styles.flowReview} />
          <path className={styles.flowFunnel} d={`M${fx - 7} ${fy - 6} h14 l-5.5 6.5 v5.5 l-3 1.8 v-7.3 z`} />
        </g>
        {/* decision: the destination */}
        <g className={styles.flowStage} style={{ animationDelay: "420ms" }} data-step="decision">
          <circle cx={tx} cy={fy} r={13} className={styles.flowTarget} />
          <circle cx={tx} cy={fy} r={6.5} className={styles.flowTargetCore} />
        </g>
        {/* real counts under the three stages */}
        {handled !== undefined && (
          <text x={38} y={92} textAnchor="middle" className={styles.flowCount} data-step="signals">
            {handled} handled
          </text>
        )}
        <text x={fx} y={84} textAnchor="middle" className={styles.flowCount} data-step="missions">
          {missions} {missions === 1 ? "mission" : "missions"}
        </text>
        <text x={tx + 16} y={84} textAnchor="end" className={styles.flowCount} data-step="decisions">
          {decisions} {decisions === 1 ? "decision" : "decisions"} due
        </text>
      </svg>
    </figure>
  );
}
