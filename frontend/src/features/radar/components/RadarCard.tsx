import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { ConvergenceTrace } from "@/components/focus";
import { companyLink } from "@/features/conviction/api";
import { convergenceSources } from "@/features/conviction/model/logic";
import type { Meta, Signal } from "@/features/conviction/model/types";
import { cx } from "@/lib/format";
import styles from "../Radar.module.css";

/** The selected card (its convergence trace is open) and the companies that arrived while the page was open. */
export type CardPick = { sel: string | null; onSelect: (slug: string) => void; fresh: Set<string> };

/** What a card shows first; the rest of the record is one click below. */
const FIRST = ["WHY PROJECT A", "WHY NOW", "NEXT ACTION"];

type Row = [label: string, value: ReactNode];

/** The record of one Radar company, in the old order. NEXT ACTION is the operator state when a human outcome, the
 *  conflict gate or a prepared case set it — a mere score band never replaces the recorded next action. */
function rows(e: Signal, meta?: Meta): Row[] {
  const verify = Array.isArray(e.verify_list) ? e.verify_list : e.verify_list ? [e.verify_list] : [];
  return [
    ["WHY FOUND", `${e.discovery_source ?? ""} · ${(meta?.tiers[e.discovery_tier ?? ""] ?? "").split(" — ")[0]}`],
    ["WHY PROJECT A", e.why_project_a ?? ""],
    ["WHY NOW", e.why_now_text ?? ""],
    ["FOUNDER SIGNAL", e.founder_signal ?? ""],
    [
      "EARLINESS · TIMING",
      <>
        {meta?.earliness[e.earliness ?? ""] ?? "?"} · <b>{e.sc.timing_label}</b> — {e.sc.timing_action}
      </>,
    ],
    ["PORTFOLIO", `${e.twin || "no twin"} — ${meta?.conflict[e.conflict ?? ""] ?? ""}`],
    ["WHAT I NEED TO VERIFY", verify.join("; ")],
    ["NEXT ACTION", e.op && e.op.source !== "score band" ? `${e.op.status} — ${e.op.action}` : (e.next_action ?? "")],
  ];
}

function RowLine({ row: [k, v] }: { row: Row }) {
  return (
    <div className={styles.k}>
      <b>{k}:</b> {v}
    </div>
  );
}

/** One Radar company: name (→ Conviction), score with its verified / PROVISIONAL label, the "N sources" convergence
 *  toggle, the FIRST rows, and the rest behind one <details>. */
export function RadarCard({ e, gated, meta, pick }: { e: Signal; gated?: boolean; meta?: Meta; pick: CardPick }) {
  const fv = e.sc.fully_verified;
  const inputs = convergenceSources(e);
  const on = pick.sel === e.slug;
  const all = rows(e, meta);
  return (
    <article
      className={cx(styles.card, gated && styles.gate, on && styles.cardOn, pick.fresh.has(e.slug) && "pz-arrive")}
      data-testid="radar-card"
      data-selected={on || undefined}
    >
      <header className={styles.cardHead}>
        <Link to={companyLink(e.slug)} className={styles.company}>
          {e.company}
        </Link>
        <span className={styles.sub}>{e.location ?? ""}</span>
        <span className="grow" />
        <span className={fv ? styles.ver : styles.prov}>{fv ? e.sc.verified : e.sc.provisional}</span>
        <span className={styles.sub}>{fv ? "verified" : `PROVISIONAL · unverified: ${e.sc.missing.join(", ")}`}</span>
        {inputs.length >= 2 && (
          <button type="button" className={styles.trace} aria-pressed={on} onClick={() => pick.onSelect(e.slug)}>
            {inputs.length} sources
          </button>
        )}
      </header>
      {on && (
        <div className={styles.traceRow}>
          <ConvergenceTrace sources={inputs} target={e.company} testId="radar-convergence" />
        </div>
      )}
      {all
        .filter(([k]) => FIRST.includes(k))
        .map((r) => (
          <RowLine key={r[0]} row={r} />
        ))}
      <details className={styles.more}>
        <summary>Founder, timing, portfolio &amp; what to verify</summary>
        {all
          .filter(([k]) => !FIRST.includes(k))
          .map((r) => (
            <RowLine key={r[0]} row={r} />
          ))}
      </details>
    </article>
  );
}
