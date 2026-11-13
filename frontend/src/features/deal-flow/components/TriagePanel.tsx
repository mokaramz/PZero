import { useState } from "react";

import { Badge, Button } from "@/components/ui";
import { EDGE_LABEL, PROPOSAL_LABEL, ROUTE_LABEL, proposalTone, type TriageSummary, type Verdict } from "../model/triage";
import type { TriageMode } from "../model/triageDecide";
import styles from "../DealFlow.module.css";

const VERDICTS: Verdict[] = ["KEEP", "RESEARCH", "WATCH", "REJECT"];

export type TriageDecide = (verdict: Verdict, mode: TriageMode) => void;

/** Accept / override (review 035a): the machine proposal becomes Mohamed's decision. Accepting a KEEP opens the Keep
 *  form ("— score it"); an override takes the verdict picked in the select. */
function TriageDecision({ t, busy, onDecide }: { t: TriageSummary; busy: boolean; onDecide: TriageDecide }) {
  const [over, setOver] = useState<Verdict | "">("");
  return (
    <div className={styles.dec}>
      <span className={styles.decLab}>Machine proposal</span>
      <Button variant={t.proposal === "REJECT" ? "danger" : "success"} onClick={() => onDecide(t.proposal, "accept")} disabled={busy} data-testid="triage-accept">
        Accept {t.proposal}
        {t.proposal === "KEEP" ? " — score it" : ""}
      </Button>
      <select value={over} onChange={(e) => setOver(e.target.value as Verdict | "")} aria-label="Override verdict">
        <option value="">Override…</option>
        {VERDICTS.filter((v) => v !== t.proposal).map((v) => (
          <option key={v} value={v}>
            {v}
          </option>
        ))}
      </select>
      <Button size="sm" onClick={() => over && onDecide(over, "override")} disabled={busy || !over} data-testid="triage-override">
        Override
      </Button>
    </div>
  );
}

/** Machine triage section of the candidate detail: the proposal, why, and Mohamed's accept / override (until decided). */
export function TriagePanel({
  t,
  themes,
  decided,
  busy,
  onDecide,
}: {
  t: TriageSummary;
  themes: Record<string, string>;
  decided: boolean;
  busy: boolean;
  onDecide: TriageDecide;
}) {
  const pf = t.portfolio;
  const flagged = t.display_proposal === "KNOWN_PORTFOLIO" || t.display_proposal === "ASK_OMAR_CONFLICT";
  return (
    <section className={styles.dsec} data-testid="triage-panel">
      <h4 className={styles.hd}>Machine triage — proposal only</h4>
      <div className="row">
        <Badge tone={proposalTone(t.display_proposal)} data-testid="triage-proposal">
          {PROPOSAL_LABEL[t.display_proposal]}
        </Badge>
        {flagged && <Badge tone="neutral">machine said {t.proposal}</Badge>}
        {t.confidence && <Badge>{t.confidence} confidence</Badge>}
        <Badge tone={t.edge === "PRE_FUNDING_EDGE" ? "green" : "neutral"}>{EDGE_LABEL[t.edge]}</Badge>
        {t.stale && <Badge tone="amber">candidate changed since proposal</Badge>}
        {t.status === "needs_human" && <Badge tone="amber">schema failure — your call</Badge>}
      </div>

      {t.queue && (
        <div className="small" data-testid="triage-route" data-state={t.queue.state}>
          <Badge tone={t.queue.state === "NEEDS_MOHAMED" ? "amber" : "neutral"}>{ROUTE_LABEL[t.queue.state]}</Badge> <b>Why it is here:</b> {t.queue.reason}
          {t.queue.resurfaced && <span> · resurfaced from {ROUTE_LABEL[t.queue.resurfaced.from as keyof typeof ROUTE_LABEL] ?? t.queue.resurfaced.from}</span>}
          <div className="faint">
            Routing priority {t.queue.priority} ({t.queue.priority_why.join(" · ")}) — attention order only; you can keep, research, watch or drop it regardless.
          </div>
        </div>
      )}

      {pf.status !== "NONE" && (
        <div className={`small ${pf.route_to_omar ? styles.amberText : ""}`} data-testid="triage-portfolio">
          <b>{pf.status.replace(/_/g, " ")}</b>
          {pf.route_to_omar && " — route to Manager; the machine never clears a conflict"}
          {pf.evidence.map((e) => (
            <div key={e}>· {e}</div>
          ))}
          {pf.record && (
            <div>
              · already in {pf.record.where}: {pf.record.name}
              {pf.record.conflict ? ` (conflict: ${pf.record.conflict})` : ""}
            </div>
          )}
        </div>
      )}

      {t.entity.broken && (
        <div className="small">
          Stored name is not a company ({t.entity.broken}).{" "}
          {t.entity.entities.length ? (
            <>
              Named in the text: <b>{t.entity.entities.map((e) => e.name).join(", ")}</b>
              <span className="faint"> — “{t.entity.entities[0].evidence.slice(0, 140)}”</span>
            </>
          ) : (
            <span className="faint">no company is named in the stored text — open the source.</span>
          )}
        </div>
      )}

      <div className={styles.why}>
        {t.reasons.map((r) => (
          <div key={r}>· {r}</div>
        ))}
        {t.proposal === "REJECT" && t.reject_basis && (
          <div>
            <b>Reject basis:</b> {t.reject_basis.replace(/_/g, " ").toLowerCase()}
            {t.reject_evidence && <span className="faint"> — “{t.reject_evidence}”</span>}
          </div>
        )}
        {!!t.missing.length && <div className="faint">Would change the label: {t.missing.join(" · ")}</div>}
      </div>
      <div className={`${styles.mono} faint small`}>
        {t.stage === "stage0" ? "Stage 0 (junk rule)" : `Flash: ${t.flash.proposal}${t.flash.reject_basis ? ` (${t.flash.reject_basis})` : ""}`}
        {t.veto && ` · Qwen veto: ${t.veto.ok ? `${t.veto.proposal}${t.veto.reject_basis ? ` (${t.veto.reject_basis})` : ""}` : "unavailable"}`}
        {t.path && ` · ${t.path}`}
        {t.capital_stage && ` · stage hint ${t.capital_stage.replace(/_/g, " ").toLowerCase()}`}
        {!!t.themes.length && ` · ${t.themes.map((x) => themes[x] || x).join(", ")}`}
        {` · ${t.routing.queue === "operating" ? "operating queue" : t.routing.queue.replace("_", " ")} (${t.routing.reason})`}
      </div>

      {t.mohamed ? (
        <div className="small" data-testid="triage-verdict">
          Your verdict: <b>{t.mohamed.verdict}</b> ({t.mohamed.mode}, {t.mohamed.agreed ? "agreed with machine" : "overrode machine"}) · {t.mohamed.at}
        </div>
      ) : null}
      {!decided && <TriageDecision key={t.candidate_id} t={t} busy={busy} onDecide={onDecide} />}
    </section>
  );
}
