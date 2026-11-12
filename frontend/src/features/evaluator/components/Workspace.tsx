/** One open evaluation: the three-column workspace, and the dialogs its claims and the why-now trigger open. */
import { Callout, Spinner } from "@/components/ui";
import { useConfirm } from "@/components/useConfirm";
import { useEvaluatorTrigger, useEvidence, useResolve, useSession } from "../api";
import type { Claim, EvaluationDetail, EvaluationsWorkspace } from "../model/types";
import { IMQ_KINDS } from "../model/view";
import type { FieldsAsk } from "./FieldsModal";
import { JudgmentPanel } from "./JudgmentPanel";
import { LedgerColumn } from "./LedgerColumn";
import { QuestionFlow } from "./QuestionFlow";
import styles from "../Evaluator.module.css";

type SetAsk = (a: FieldsAsk) => void;

/** The selected session, read by id: a spinner while it loads, the server's message for an unknown one. */
export function SessionView({ id, w, setAsk }: { id: string; w: EvaluationsWorkspace; setAsk: SetAsk }) {
  const q = useSession(id);
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <Callout tone="red">{q.error instanceof Error ? q.error.message : "unknown session"}</Callout>;
  return <Workspace d={q.data} w={w} setAsk={setAsk} />;
}

function Workspace({ d, w, setAsk }: { d: EvaluationDetail; w: EvaluationsWorkspace; setAsk: SetAsk }) {
  const [confirm, confirmEl] = useConfirm();
  const s = d.session;
  const ctx = s.context || {};
  const evidenceA = useEvidence();
  const resolveA = useResolve();
  const imq = useEvaluatorTrigger();

  const attachSource = (cl: Claim) =>
    setAsk({
      title: "Attach public source",
      intro: "Public source URL for THIS claim only (not LinkedIn, not a search result).",
      ok: "Attach source",
      fields: [
        { name: "url", label: "Public source URL", type: "url", required: true },
        { name: "label", label: "Source label" },
        { name: "note", label: "What the source states", type: "textarea" },
      ],
      onSubmit: (v) => evidenceA.mutate({ id: s.id, claim_id: cl.id, url: v.url, label: v.label, note: v.note, kind: "public" }),
    });
  const operatorVerify = (cl: Claim) =>
    setAsk({
      title: "Operator verified",
      intro: "Mark THIS claim as OPERATOR VERIFIED (you checked it yourself)? Other claims and the Verified score stay unchanged.",
      ok: "Mark operator verified",
      fields: [{ name: "note", label: "How did you verify it?", type: "textarea" }],
      onSubmit: (v) => evidenceA.mutate({ id: s.id, claim_id: cl.id, kind: "operator", confirm: true, note: v.note }),
    });
  const resolve = (cl: Claim) =>
    setAsk({
      title: "Resolve contradiction",
      ok: "Resolve",
      fields: [{ name: "note", label: "Resolution note (what settled the contradiction)", type: "textarea" }],
      onSubmit: (v) => resolveA.mutate({ id: s.id, claim_id: cl.id, note: v.note }),
    });
  const recordTrigger = () =>
    setAsk({
      title: "Record dated why-now trigger (sourced)",
      intro: "Same public-evidence rules as Conviction: a dated fact and the public source that documents it. Nothing is sent.",
      ok: "Review trigger",
      fields: [
        { name: "kind", label: "Trigger kind", type: "select", options: IMQ_KINDS },
        { name: "date", label: "Date of the trigger (when it happened, not today)", type: "date", required: true },
        { name: "url", label: "Public source URL that documents it (not LinkedIn, not a search result)", type: "url", required: true },
        { name: "fact", label: "The dated fact as the source states it", type: "textarea" },
      ],
      onSubmit: async (v) => {
        const ok = await confirm(`Record why-now trigger:\n${v.kind} · ${v.date}\n"${v.fact}"\n${v.url}`, {
          title: "Record why-now trigger",
          ok: "Record trigger",
        });
        if (ok && ctx.slug) imq.mutate({ slug: ctx.slug, kind: v.kind, date: v.date, url: v.url, fact: v.fact, confirm: true });
      },
    });

  return (
    <div className={styles.ws} data-testid="eval-workspace">
      <LedgerColumn s={s} w={w} handlers={{ onAttach: attachSource, onOperator: operatorVerify, onResolve: resolve }} />
      <QuestionFlow d={d} w={w} confirm={confirm} />
      <JudgmentPanel s={s} P={d.panel} onTrigger={recordTrigger} />
      {confirmEl}
    </div>
  );
}
