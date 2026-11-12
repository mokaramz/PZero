/**
 * Validation & Learning (v1 view `validation`, review 027a): is Project Zero making the operator better at finding
 * exceptional companies early — or only giving more information? One read (`GET validation`, see ./api), then one
 * analytical question at a time (FocusTabs; the active question is local state, as before — no query param).
 *
 * The read side only. Every write control keeps its place and text, disabled with `NOT_PORTED.writes` until review
 * 027b: Record outcome, Record a miss, Record false positive, Retract, the benchmark Preview and "Copy & log handover".
 * The News benchmark and the native search bridge pilot show their own reasons (./model/deferred).
 */
import { useState, type ReactNode } from "react";

import { DeferredButton } from "@/components/Deferred";
import { ActionArea, Async, FocusTabs, PageHeader } from "@/components/ui";
import { useValidation } from "./api";
import { EarlyTab } from "./components/EarlyTab";
import { Measurement } from "./components/Measurement";
import { MissTab } from "./components/MissTab";
import { NativeBridge } from "./components/NativeBridge";
import { RightTab } from "./components/RightTab";
import { SourcesTab } from "./components/SourcesTab";
import { NOT_PORTED } from "./model/deferred";
import type { ValidationPayload } from "./model/types";
import { QUESTIONS, type Dim, type Question } from "./model/view";
import { useScoutPacket } from "./useScoutPacket";
import styles from "./Validation.module.css";

export default function ValidationPage() {
  const q = useValidation();
  return (
    <>
      <PageHeader
        title="Validation & Learning"
        subtitle="Is Project Zero making you better at finding exceptional companies early — or only giving you more information?"
        actions={
          <ActionArea
            primary={
              <DeferredButton reason={NOT_PORTED.writes} data-testid="record-outcome">
                Record outcome
              </DeferredButton>
            }
            more={[{ label: "Record a miss", onClick: () => {}, testId: "record-miss", disabled: true, hint: NOT_PORTED.writes }]}
          />
        }
      />
      <Async q={q} label="Computing validation…">
        {(d) => <Validation d={d} />}
      </Async>
    </>
  );
}

function Validation({ d }: { d: ValidationPayload }) {
  const [question, setQuestion] = useState<Question>("early");
  const [dim, setDim] = useState<Dim>("tier");
  const scout = useScoutPacket();
  const min = d.vocab.min_n;
  const content: Record<Question, ReactNode> = {
    early: <EarlyTab d={d} />,
    right: <RightTab d={d} dim={dim} onDim={setDim} />,
    sources: <SourcesTab d={d} />,
    miss: <MissTab d={d} scout={scout} />,
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
