import { Badge, Button } from "@/components/ui";
import { plainText } from "@/lib/activity";
import type { CompanyFounder, ProposalGroup } from "../model/types";
import { Ext } from "./bits";
import styles from "../FounderRadar.module.css";

type Props = {
  g: ProposalGroup;
  founders: CompanyFounder[];
  recommended: boolean;
  checked: boolean;
  onCheck: (on: boolean) => void;
  bound: string;
  onBind: (v: string) => void;
  onPair: () => void;
};

/** One fact of the review: its status, confidence and kind, the passage, the source and why it matters; a founder row
 *  also has its binding selector and "Confirm pairing…". A decided row (confirmed / rejected) can no longer be selected,
 *  bound or paired — a replay is never re-applied. */
export function ReviewRow({ g, founders, recommended, checked, onCheck, bound, onBind, onPair }: Props) {
  const p = g.best;
  const ident = g.field === "founder";
  const infer = (p.evidence_kind || "") === "machine_inference";
  const pending = p.status === "pending";
  return (
    <div className={styles.revRow} data-testid="fr-review-row" data-field={g.field} data-value={String(g.value)} data-recommended={recommended || undefined}>
      <label className={styles.revLabel}>
        <input type="checkbox" checked={checked} disabled={!pending} onChange={(e) => onCheck(e.target.checked)} aria-label={`select ${g.field} = ${String(g.value)}`} />{" "}
        <span>
          <b>{g.field}</b> = {String(g.value)}
          {p.activity_date ? " · activity date " + p.activity_date : ""}
        </span>{" "}
        <Badge tone={p.status === "confirmed" ? "green" : p.status === "rejected" ? "red" : "blue"}>{p.status}</Badge>{" "}
        <Badge tone={p.confidence === "high" ? "green" : p.confidence === "medium" ? "amber" : "neutral"}>{p.confidence}</Badge>
        {recommended && <Badge tone="green">recommended</Badge>}
        {g.disputed && <Badge tone="amber">disputed by another source</Badge>}
        {p.template_text && <Badge tone="amber">template text</Badge>}
        {infer ? <Badge>machine inference</Badge> : p.evidence_kind === "quoted_fact" ? <Badge>quoted public fact</Badge> : <Badge tone="amber">evidence kind unknown</Badge>}
      </label>
      <div className={styles.passage}>{infer ? <i>{p.passage}</i> : `“${p.passage}”`}</div>
      <div className={styles.provenance}>
        Source: <Ext href={p.url}>{p.source_label} ↗</Ext> · {p.source_type} · rank {p.source_rank || "-"} · <b>Why it matters:</b> {p.why || ""}
        {p.last_error && (
          <>
            {" · "}
            <Badge tone="amber">{plainText(p.last_error)}</Badge>
          </>
        )}
      </div>
      {ident && (
        <div className={styles.provenance}>
          <label>
            Bind to founder reference →{" "}
            <select value={bound} disabled={!pending} onChange={(e) => onBind(e.target.value)} data-testid="fr-bind" data-prop={p.id}>
              <option value="">choose…</option>
              {founders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                  {f.handle_only ? " (login only — pair first)" : ""}
                </option>
              ))}
            </select>
          </label>{" "}
          <Button size="sm" onClick={onPair} disabled={!pending}>
            Confirm pairing…
          </Button>{" "}
          <Badge tone="amber">individual confirmation only</Badge>
        </div>
      )}
      <details className={styles.details}>
        <summary>{g.hidden ? `${g.hidden} supporting source(s) / duplicate passage(s) hidden` : "raw passage & details"}</summary>
        {(g.alternatives ?? []).length ? (
          g.alternatives.map((a) => (
            <div key={a.id} className={styles.sub}>
              “{a.passage}” — <Ext href={a.url}>{a.source_label} ↗</Ext> · rank {a.source_rank || "-"} · {a.confidence} · {a.status}
            </div>
          ))
        ) : (
          <div className={styles.sub}>no alternative sources</div>
        )}
        <div className={styles.sub}>
          proposal id {p.id} · retrieved {p.retrieved}
        </div>
      </details>
    </div>
  );
}
