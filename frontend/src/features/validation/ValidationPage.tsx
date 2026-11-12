/**
 * Validation & Learning (v1 view `validation`, reviews 027a, 027b): is Project Zero making the operator better at
 * finding exceptional companies early — or only giving more information? One read (`GET validation`, see ./api), then
 * one analytical question at a time (FocusTabs; the active question is local state, as before — no query param).
 *
 * The writes, each append-only (./api): Record outcome and Record a miss (the header), Record false positive and
 * "Copy & log handover" (Where do we miss?), Retract (the outcome ledger) and the benchmark preview / import (Which
 * sources work?). The forms need the vocabulary, so they live with the data. The News benchmark and the native search
 * bridge pilot show their own reasons (./model/deferred).
 */
import { useState, type ReactNode } from "react";

import { ActionArea, Async, Button, FocusTabs, PageHeader } from "@/components/ui";
import { useValidation } from "./api";
import { EarlyTab } from "./components/EarlyTab";
import { Measurement } from "./components/Measurement";
import { MissTab } from "./components/MissTab";
import { NativeBridge } from "./components/NativeBridge";
import { AuditForm, OutcomeForm } from "./components/RecordForms";
import { RightTab } from "./components/RightTab";
import { SourcesTab } from "./components/SourcesTab";
import type { ValidationPayload } from "./model/types";
import { QUESTIONS, type Dim, type Question } from "./model/view";
import type { AuditType } from "./model/writes";
import { useScoutPacket } from "./useScoutPacket";
import styles from "./Validation.module.css";

export default function ValidationPage() {
  const q = useValidation();
  const [outcomeOpen, setOutcomeOpen] = useState(false);
  const [audit, setAudit] = useState<AuditType | null>(null);
  return (
    <>
      <PageHeader
        title="Validation & Learning"
        subtitle="Is Project Zero making you better at finding exceptional companies early — or only giving you more information?"
        actions={
          <ActionArea
            primary={
              <Button onClick={() => setOutcomeOpen(true)} data-testid="record-outcome">
                Record outcome
              </Button>
            }
            more={[{ label: "Record a miss", onClick: () => setAudit("miss"), testId: "record-miss" }]}
          />
        }
      />
      <Async q={q} label="Computing validation…">
        {(d) => (
          <>
            <Validation d={d} onFalsePositive={() => setAudit("false_positive")} />
            <OutcomeForm open={outcomeOpen} onClose={() => setOutcomeOpen(false)} vocab={d.vocab} />
            <AuditForm key={audit ?? "none"} type={audit} onClose={() => setAudit(null)} vocab={d.vocab} />
          </>
        )}
      </Async>
    </>
  );
}

function Validation({ d, onFalsePositive }: { d: ValidationPayload; onFalsePositive: () => void }) {
  const [question, setQuestion] = useState<Question>("early");
  const [dim, setDim] = useState<Dim>("tier");
  const scout = useScoutPacket();
  const min = d.vocab.min_n;
  const content: Record<Question, ReactNode> = {
    early: <EarlyTab d={d} />,
    right: <RightTab d={d} dim={dim} onDim={setDim} />,
    sources: <SourcesTab d={d} />,
    miss: <MissTab d={d} scout={scout} onFalsePositive={onFalsePositive} />,
    cost: (
      <div className={styles.page}>
        <NativeBridge bridge={d.native_bridge} />
      </div>
    ),
  };
  return (
    <div className={styles.page}>
      <p className={styles.note}>
        Read-only evidence about Project Zero itself. Outcomes count only from <b>real-world events, your decisions, Manager and the deterministic gates</b>{" "}
        — machine proposals never validate themselves. Rates appear once a group has {min}+ cases; before that you see counts and “collecting”.{" "}
        <b>UNKNOWN</b> means “no outcome yet”, not failure.
      </p>

      <Measurement d={d} />

      <FocusTabs
        label="Question"
        testId="val-questions"
        value={question}
        onChange={(id) => setQuestion(id as Question)}
        tabs={QUESTIONS.map((t) => ({ id: t.id, label: t.label, content: content[t.id] }))}
      />

      <p className="small faint" data-testid="val-footer">
        Validation spends no model money (${d.cost.validation_usd.toFixed(2)}); all paid inference this month: ${d.cost.ai_usd_this_month.toFixed(2)}.
        Balanced on purpose: recall, earliness, quality, novelty and your attention are shown side by side — there is no single score to optimise. Daily
        snapshots kept: {d.snapshots.length}.
      </p>
    </div>
  );
}
