import type { RefObject } from "react";
import { Link } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { DEFAULT_WS_GEOS, type Workspace } from "../model/geo";
import type { InboxPayload } from "../model/types";
import { FindBar } from "./FindBar";
import { ScanHistory } from "./ScanHistory";
import styles from "../DealFlow.module.css";

/** Machine analysis: secondary to human review — one quiet band below the decision surface (the scan, review 034a). */
export function MachineZone({
  ib,
  ws,
  findRef,
  onScanFinished,
}: {
  ib: InboxPayload;
  ws: Workspace;
  findRef: RefObject<HTMLDivElement | null>;
  onScanFinished: () => void;
}) {
  return (
    <section className={styles.machineZone} aria-label="Machine analysis" data-zone="background">
      <h2 className={styles.machineTitle}>
        <Icon name="layers" size={20} className={styles.machineIcon} /> Machine analysis
      </h2>
      <FindBar ib={ib} ws={ws} geos={ib.ws_geos ?? DEFAULT_WS_GEOS} onScanFinished={onScanFinished} anchorRef={findRef} />
      <ScanHistory />
      <p className="faint small">
        Source registry, coverage and health live on the <Link to="/sources">Sources</Link> page.
      </p>
    </section>
  );
}
