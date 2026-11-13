import { useId } from "react";
import { useNavigate } from "react-router-dom";

import { useDeferred } from "@/components/Deferred";
import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui";
import { NOT_PORTED } from "@/features/deal-flow/model/deferred";
import { cx } from "@/lib/format";
import { lastScanLine, machineLine } from "../model/desk";
import type { Candidate, HomePayload, Inbox } from "../model/types";
import styles from "../Home.module.css";

export const FIND_LINK = "/deal-flow?find=1";

/**
 * MACHINE WORK IN PROGRESS — last and folded: what the system is handling, and the five next actions in the old order.
 * Four of them navigate (nothing is posted; Find only focuses the Find control) or open the weekly drawer. The Agent
 * Review Queue is deferred until the analysis port (decision d, revision 2): the control keeps its place and label, is
 * disabled through the shared `useDeferred` (an inert click and Enter), and its reason is the visible note right below
 * the controls, which its `aria-describedby` names. No review link is built.
 */
export function Machine({
  ib,
  progress,
  news,
  C,
  done,
  warn,
  onWeekly,
}: {
  ib?: Inbox;
  progress: HomePayload["progress"];
  news: Candidate[];
  C: Candidate[];
  done: number;
  warn: number;
  onWeekly: () => void;
}) {
  const navigate = useNavigate();
  const review = useDeferred(NOT_PORTED.reviewQueue);
  const noteId = useId();
  const scan = lastScanLine(ib);
  return (
    <details className={styles.machine} data-testid="desk-machine">
      <summary>
        <Icon name="layers" size={17} className={styles.headIcon} />
        <span className={styles.machineTitle}>Machine work in progress</span>
        <span className={styles.machineLine}>{machineLine(ib, progress, done, warn)}</span>
        <Icon name="chevron" size={14} className={styles.machineChevron} />
      </summary>
      <div className={cx(styles.machineBody, "pz-reveal")}>
        <div className={styles.pulse} data-testid="desk-pulse">
          <span>
            <b>{progress.found ?? news.length}</b> new candidates
          </span>
          <span>
            <b>{news.filter((c) => c.discovery_tier === "pre_company").length}</b> pre-company signals
          </span>
          <span>
            <b>{done}</b> research completed
          </span>
          <span>
            <b>{C.filter((c) => c.decision === "kept").length}</b> kept
          </span>
          <span>
            <b>{progress.sent_omar ?? 0}</b> sent to Manager
          </span>
          <span>
            <b>{warn}</b> source health warnings
          </span>
        </div>
        {scan && <p className={styles.small}>{scan}</p>}
        <div className={styles.machineActions} role="group" aria-label="Next actions">
          <Button size="sm" onClick={() => navigate(FIND_LINK)}>
            Find New Candidates
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate("/deal-flow")}>
            Open Deal Flow
          </Button>
          <Button size="sm" variant="ghost" {...review.props} aria-describedby={noteId} data-testid="desk-review-queue">
            Open Agent Review Queue
          </Button>
          <Button size="sm" variant="ghost" onClick={() => navigate("/conviction")}>
            Open Conviction
          </Button>
          <Button size="sm" variant="ghost" onClick={onWeekly}>
            Compose weekly update
          </Button>
        </div>
        <p id={noteId} className={styles.small} data-testid="desk-review-note">
          {NOT_PORTED.reviewQueue}
        </p>
      </div>
    </details>
  );
}
