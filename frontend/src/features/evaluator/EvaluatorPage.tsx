/**
 * Active Evaluator (v1 view `evaluator`, review 024): live diligence support for a founder conversation. The counts and
 * the sessions strip, then the selected session's three columns — subject, deck, existing evidence and claim ledger |
 * the question flow or the ended summary | judgment inputs, gaps, contradictions, staged evidence, score movement and
 * IMQ readiness. Reads `GET evaluator/sessions` and `GET evaluator/session?id=`; writes the `evaluator/*` actions and
 * Conviction's `imq_trigger` (see ./api). Nothing here changes a Verified score or sends anything.
 *
 * Entry points: `?session=<id>` selects a session; `?start=1&slug=…&name=…&founder=…` (from Conviction) opens the
 * prefilled start dialog — starting still takes a click.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useToast } from "@/components/Toast";
import { Async, Button, PageHeader } from "@/components/ui";
import { cx } from "@/lib/format";
import { useSessions, useStart } from "./api";
import { FieldsModal, type FieldsAsk } from "./components/FieldsModal";
import { SessionStrip } from "./components/SessionStrip";
import { SessionView } from "./components/Workspace";
import { countsLine, startFromParams, startSubject, withoutStart, type StartPre } from "./model/view";
import styles from "./Evaluator.module.css";

export default function EvaluatorPage() {
  const ws = useSessions();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [ask, setAsk] = useState<FieldsAsk | null>(null);
  const sel = params.get("session");
  const start = useStart();

  const select = (id: string) =>
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.set("session", id);
        return p;
      },
      { replace: true },
    );

  const newExternal = (pre: StartPre = {}) =>
    setAsk({
      title: pre.slug ? "Start Active Evaluator" : "New external evaluation",
      intro: pre.slug ? `Linked to the Conviction company ${pre.name ?? pre.slug}. Nothing is recorded, nothing is sent.` : undefined,
      ok: "Start evaluation",
      fields: [
        { name: "name", label: "Company / project name (external founder meeting)", required: true, initial: pre.name ?? "" },
        { name: "founder", label: "Founder name (as introduced — stays founder-reported)", initial: pre.founder ?? "" },
      ],
      onSubmit: (v) =>
        start.mutate(
          { subject: startSubject(pre, { name: v.name, founder: v.founder }) },
          {
            onSuccess: (r) => {
              toast.show("Active Evaluator started — nothing is recorded, nothing is sent", "ok");
              select(r.id);
            },
          },
        ),
    });

  // The entry from Conviction opens the prefilled start dialog while rendering (once per entry URL); the effect then
  // drops the entry keys from the URL.
  const entry = startFromParams(params);
  const entryKey = entry ? params.toString() : null;
  const [seenEntry, setSeenEntry] = useState<string | null>(null);
  if (entryKey !== seenEntry) {
    setSeenEntry(entryKey);
    if (entry) newExternal(entry);
  }
  useEffect(() => {
    if (entryKey) setParams(withoutStart(new URLSearchParams(entryKey)), { replace: true });
  }, [entryKey, setParams]);

  return (
    <div className={styles.page}>
      <PageHeader
        title="Active Evaluator"
        subtitle={
          <>
            Live diligence support for a founder conversation — collects the evidence the existing judgment model needs. Every founder statement stays{" "}
            <b>FOUNDER-REPORTED — unverified</b>, every deck statement starts as <b>DECK CLAIM — UNVERIFIED</b>; nothing here changes a Verified score,
            records audio or sends anything to Manager. Input is what you type.
          </>
        }
      />
      <Async q={ws} label="Loading evaluations…">
        {(w) => (
          <>
            <div className={styles.bar}>
              <span className={styles.sub} data-testid="eval-counts">
                {countsLine(w.sessions)}
              </span>
              <span className="grow" />
              <Button variant="primary" onClick={() => newExternal()} busy={start.isPending}>
                New external evaluation
              </Button>
            </div>
            <SessionStrip sessions={w.sessions} selected={sel} onSelect={select} />
            {sel ? <SessionView id={sel} w={w} setAsk={setAsk} /> : <div className={cx(styles.ws, styles.wsEmpty)}>Select or start an evaluation.</div>}
          </>
        )}
      </Async>
      <FieldsModal ask={ask} onClose={() => setAsk(null)} />
    </div>
  );
}
