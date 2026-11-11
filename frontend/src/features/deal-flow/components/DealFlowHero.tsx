import { useMemo } from "react";

import { cx } from "@/lib/format";
import type { NaFilter, Workspace } from "../model/geo";
import { buildList } from "../model/list";
import type { InboxPayload } from "../model/types";
import styles from "../DealFlow.module.css";

const XS = [96, 216, 336];
const Y = 30;

/** "Monday, 11 Nov · 09:30" */
function stamp(now: Date): string {
  const day = now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" }).replace(" ", ", ");
  return `${day} · ${now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

/**
 * Deal Flow header (approved mockup): the date, the title, the purpose — and ONE restrained flow trace drawn from the
 * workspace's real states: found (every candidate in this workspace, baseline excluded) → researching → kept. No
 * invented funnel stage; the trace draws once (≈ 0.6 s) and stays still; reduced motion shows it at once.
 */
export function DealFlowHero({ ib, ws, naf }: { ib: InboxPayload; ws: Workspace; naf: NaFilter }) {
  const c = useMemo(() => buildList(ib.candidates, { ws, naf, theme: "", im: false, filter: "new", lastRun: ib.last_run }).counts, [ib, ws, naf]);
  const found = (c.new || 0) + (c.research || 0) + (c.watch || 0) + (c.kept || 0) + (c.rejected || 0);
  const stages = [
    { key: "found", n: found, label: "found" },
    { key: "research", n: c.research || 0, label: "researching" },
    { key: "kept", n: c.kept || 0, label: "kept" },
  ];
  return (
    <header className={styles.hero}>
      <div className={styles.heroText}>
        <div className={styles.heroDate}>{stamp(new Date())}</div>
        <h1 className={styles.heroTitle}>Deal Flow</h1>
        <p className={styles.heroSub}>Opportunities worth your attention</p>
      </div>
      <figure className={styles.trace} data-testid="df-trace" data-signature="data">
        <svg viewBox="0 0 380 64" role="img" aria-label={`Candidate flow in this workspace: ${stages.map((st) => `${st.n} ${st.label}`).join(" → ")}`}>
          <path
            className={cx(styles.traceIn, "pz-trace")}
            d={`M4 ${Y + 10} C 40 ${Y + 10}, 64 ${Y}, ${XS[0]} ${Y}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
          />
          <path
            className={cx(styles.traceLine, "pz-trace")}
            d={`M${XS[0]} ${Y} C ${XS[0] + 50} ${Y - 14}, ${XS[1] - 50} ${Y - 14}, ${XS[1]} ${Y} S ${XS[2] - 40} ${Y + 12}, ${XS[2]} ${Y}`}
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset="1"
            style={{ animationDelay: "120ms" }}
          />
          <g className={styles.traceStage} data-stage="found" style={{ animationDelay: "60ms" }}>
            <circle cx={XS[0]} cy={Y} r={6} className={styles.traceRing} />
          </g>
          <g className={styles.traceStage} data-stage="research" style={{ animationDelay: "240ms" }}>
            <circle cx={XS[1]} cy={Y} r={14} className={styles.traceFocus} />
            <path className={styles.traceGlyph} d={`M${XS[1]} ${Y - 6} l-7 3.5 7 3.5 7 -3.5 z M${XS[1] - 7} ${Y + 1.5} l7 3.5 7 -3.5`} />
          </g>
          <g className={styles.traceStage} data-stage="kept" style={{ animationDelay: "420ms" }}>
            <circle cx={XS[2]} cy={Y} r={11} className={styles.traceTarget} />
            <circle cx={XS[2]} cy={Y} r={5.5} className={styles.traceCore} />
          </g>
          {stages.map((st, i) => (
            <text key={st.key} x={XS[i]} y={60} textAnchor="middle" className={styles.traceText} data-stage={st.key}>
              {st.n} {st.label}
            </text>
          ))}
        </svg>
      </figure>
    </header>
  );
}
