import { Button, Chip } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import {
  PROPOSAL_LABEL,
  ROUTE_LABEL,
  ROUTE_ORDER,
  type RouteFilter,
  type RouteState,
  type TriageKind,
  type TriagePayload,
  type TriageScope,
} from "../model/triage";
import { DeferredButton } from "./DeferredButton";
import styles from "../DealFlow.module.css";

const SCOPES: ReadonlyArray<readonly [TriageScope, string]> = [
  ["operating", "Operating queue (Europe-first)"],
  ["global_only", "Global only"],
  ["non_startup", "Non-startup records"],
  ["all", "Everything"],
];
const KINDS = ["ALL", "ASK_OMAR_CONFLICT", "KNOWN_PORTFOLIO", "KEEP", "RESEARCH", "WATCH", "REJECT"] as const;

type Props = {
  tRoute: RouteFilter;
  setTRoute: (r: RouteFilter) => void;
  tScope: TriageScope;
  setTScope: (s: TriageScope) => void;
  tKind: TriageKind;
  setTKind: (k: TriageKind) => void;
  rCounts: Partial<Record<RouteState, number>>;
  tCounts: Partial<Record<TriageKind, number>>;
  payload?: TriagePayload;
  /** "Accept obvious REJECTs…" (review 035a): previews, confirms, then applies */
  onBatchReject: () => void;
  batchBusy: boolean;
};

/** The Machine triage view's controls: routing views, queue scope and proposal kind, and the batch accept of the obvious
 *  REJECTs (review 035a). The Analyst and Red Team batches wait for the analysis port and stay in place, disabled. */
export function TriageBars({ tRoute, setTRoute, tScope, setTScope, tKind, setTKind, rCounts, tCounts, payload, onBatchReject, batchBusy }: Props) {
  return (
    <>
      <div className={styles.filters} data-testid="triage-routes">
        <span className="faint small">Routing (attention order — never a decision):</span>
        <Chip on={tRoute === "ANY"} onClick={() => setTRoute("ANY")} data-route="ANY">
          By proposal
        </Chip>
        {ROUTE_ORDER.map((r) =>
          rCounts[r] ? (
            <Chip key={r} on={tRoute === r} onClick={() => setTRoute(r)} data-route={r}>
              {ROUTE_LABEL[r]} {rCounts[r]}
            </Chip>
          ) : null,
        )}
      </div>
      {tRoute === "ANY" && (
        <div className={styles.filters} data-testid="triage-bar">
          {SCOPES.map(([v, l]) => (
            <Chip key={v} on={tScope === v} onClick={() => setTScope(v)} data-scope={v}>
              {l}
            </Chip>
          ))}
          <span className="grow" />
          {KINDS.map((k) =>
            k === "ALL" || tCounts[k] ? (
              <Chip key={k} on={tKind === k} onClick={() => setTKind(k)} data-kind={k}>
                {k === "ALL" ? "All" : PROPOSAL_LABEL[k]} {tCounts[k] ?? 0}
              </Chip>
            ) : null,
          )}
          <DeferredButton size="sm" reason={NOT_PORTED.analysis} data-testid="triage-analyst">
            Analyze top KEEPs…
          </DeferredButton>
          <DeferredButton size="sm" reason={NOT_PORTED.redTeam} data-testid="triage-redteam">
            Red-team analysed…
          </DeferredButton>
          <Button size="sm" variant="danger" onClick={onBatchReject} busy={batchBusy} disabled={!payload} data-testid="triage-batch">
            Accept obvious REJECTs…
          </Button>
        </div>
      )}
      {payload?.calibration && (
        <div className="faint small" data-testid="triage-note">
          {payload.note} Accepted architecture {payload.architecture?.prompt_version}
          {payload.calibration.decisions
            ? ` · your decisions so far: ${payload.calibration.decisions}, agreement ${Math.round((payload.calibration.agreement ?? 0) * 100)}%, machine REJECTs you overturned: ${payload.calibration.machine_rejects_overturned_to_keep_or_research}`
            : " · no decisions logged yet"}
        </div>
      )}
    </>
  );
}
