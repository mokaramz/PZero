import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { WS_LABEL, type Workspace } from "../model/geo";
import styles from "../DealFlow.module.css";

type Counts = { eu: number; na: number; unk: number };

/** The workspace tabs with their undecided counts, and the workspace's one-line purpose. */
export function WorkspaceBar({ ws, setWs, counts }: { ws: Workspace; setWs: (w: Workspace) => void; counts: Counts }) {
  const seg = (v: Workspace, label: ReactNode, n?: number) => (
    <button
      type="button"
      role="tab"
      aria-selected={ws === v}
      className={cx(styles.wsSeg, ws === v && styles.wsOn, v === "unk" && styles.wsUnk)}
      onClick={() => setWs(v)}
      data-ws={v}
    >
      {label}
      {!!n && <span className={styles.wsN}>{n}</span>}
    </button>
  );
  const l = WS_LABEL[ws];
  return (
    <div className={styles.wsBar}>
      <div className={styles.wsSegs} role="tablist" aria-label="Workspace">
        {seg("eu", <b>EUROPE</b>, counts.eu)}
        {seg("na", <b>NORTH AMERICA</b>, counts.na)}
        {seg("all", "Global")}
        {seg("unk", "Unresolved", counts.unk)}
      </div>
      <span className={styles.wsLabel} data-testid="ws-label">
        {l.strong && <b>{l.strong}</b>}
        {l.rest}
      </span>
    </div>
  );
}
