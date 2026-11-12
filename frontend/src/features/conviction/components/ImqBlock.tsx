/** The "Investment Manager Qualified" block (v1 imqBlock): the computed `imq_eval` of the record. Recording a dated
 *  why-now trigger is live (review 024); asking Scout 00 and starting the evaluator keep their place, disabled until
 *  their ports. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { DeferredLink } from "@/components/Deferred";
import { Badge, type Tone } from "@/components/ui";
import { useStart } from "@/features/evaluator/api";
import { cx } from "@/lib/format";
import { NOT_PORTED } from "../model/deferred";
import type { Signal } from "../model/types";
import { TriggerModal } from "./TriggerModal";
import styles from "../Conviction.module.css";

const QUALIFIED = "IMQ — QUALIFIED NOW";

function BulbIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
      <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.8.6 1.2 1.3 1.3 2.1h4.4c.1-.8.5-1.5 1.3-2.1A6 6 0 0 0 12 3z" />
    </svg>
  );
}

export function ImqBlock({ e }: { e: Signal }) {
  const q = e.imq_eval;
  const [trigOpen, setTrigOpen] = useState(false);
  const evalStart = useStart();
  const navigate = useNavigate();
  if (!q) return null;
  const kind = q.state === QUALIFIED ? "on" : q.state === "CONFLICT GATED" ? "gated" : q.state === "IMQ — STALE" ? "stale" : "";
  const tone: Tone = kind === "on" ? "green" : kind === "gated" ? "red" : kind === "stale" ? "amber" : "neutral";
  const t = q.timing ?? {};
  return (
    <div className={cx(styles.imq, kind === "on" && styles.imqOn, kind === "gated" && styles.imqGated, kind === "stale" && styles.imqStale)} data-testid="imq">
      <div className={styles.imqHead}>
        <BulbIcon />
        <b>Investment Manager Qualified</b>
        <Badge tone={tone}>{q.state}</Badge>
        <span className={styles.sub}>
          · Verified {q.verified_score}
          {q.route && ` · route ${q.route}`} · never sent automatically
        </span>
      </div>
      {q.state === QUALIFIED && <div className={styles.sub}>{q.reason}</div>}
      {q.blockers.length > 0 && (
        <ul className={styles.blockers}>
          {q.blockers.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}
      <div className={styles.sub}>
        Timing:{" "}
        {t.established ? (
          <>
            <b>{t.label}</b> on {t.date} ({t.origin})
          </>
        ) : (
          <b>not established</b>
        )}{" "}
        · Identities: {(q.founder_identities ?? []).map((i) => `${i.name} — ${i.status}`).join("; ") || "no named founder"}
        {q.persisted?.qualified_at &&
          ` · qualified ${q.persisted.qualified_at} at Verified ${q.persisted.verified_score_at_qualification}${q.persisted.stale_since ? ` · stale since ${q.persisted.stale_since}` : ""}`}
      </div>
      <div className={styles.links}>
        <button type="button" className={styles.link} onClick={() => setTrigOpen(true)}>
          Record dated why-now trigger (sourced)
        </button>
        {!t.established && (
          <DeferredLink className={styles.link} reason={NOT_PORTED.bridge}>
            ask Scout 00 for a dated source ↗
          </DeferredLink>
        )}
        <button
          type="button"
          className={styles.link}
          disabled={evalStart.isPending}
          onClick={async () => {
            const r = await evalStart
              .mutateAsync({ subject: { kind: "company", slug: e.slug, name: e.company, founder: e.founders?.[0]?.name ?? "" } })
              .catch(() => null);
            if (r?.ok) navigate(`/evaluator?session=${encodeURIComponent(r.id)}`);
          }}
        >
          Start Active Evaluator
        </button>
      </div>
      {trigOpen && <TriggerModal slug={e.slug} onClose={() => setTrigOpen(false)} />}
    </div>
  );
}
