/** The "Investment Manager Qualified" block (v1 imqBlock), read-only: the computed `imq_eval` of the record. Its three
 *  actions (record a dated trigger, ask Scout 00, start the evaluator) keep their place, disabled until their ports. */
import { DeferredLink } from "@/components/Deferred";
import { Badge, type Tone } from "@/components/ui";
import { cx } from "@/lib/format";
import { NOT_PORTED } from "../model/deferred";
import type { Signal } from "../model/types";
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
          {q.blockers.map((b) => (
            <li key={b}>{b}</li>
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
        <DeferredLink className={styles.link} reason={NOT_PORTED.imqTrigger}>
          Record dated why-now trigger (sourced)
        </DeferredLink>
        {!t.established && (
          <DeferredLink className={styles.link} reason={NOT_PORTED.bridge}>
            ask Scout 00 for a dated source ↗
          </DeferredLink>
        )}
        <DeferredLink className={styles.link} reason={NOT_PORTED.evaluator}>
          Start Active Evaluator
        </DeferredLink>
      </div>
    </div>
  );
}
