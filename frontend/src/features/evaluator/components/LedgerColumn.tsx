/** The left column: the subject (with its Conviction link), the pitch deck, the existing Project Zero evidence and the
 *  claim ledger, newest first. "verify via Scout 00" keeps its place, disabled (the Scout Bridge is not ported). */
import { useState } from "react";
import { Link } from "react-router-dom";

import { DeferredLink } from "@/components/Deferred";
import { Button } from "@/components/ui";
import { companyLink } from "@/features/conviction/api";
import { cx } from "@/lib/format";
import { useDeck } from "../api";
import { NOT_PORTED } from "../model/deferred";
import type { Claim, EvaluationsWorkspace, Session } from "../model/types";
import { claimActions, existingEvidence, familyLabel, newestFirst, researchFacts } from "../model/view";
import { EvState } from "./EvState";
import styles from "../Evaluator.module.css";

export type ClaimHandlers = { onAttach: (cl: Claim) => void; onOperator: (cl: Claim) => void; onResolve: (cl: Claim) => void };

export function LedgerColumn({ s, w, handlers }: { s: Session; w: EvaluationsWorkspace; handlers: ClaimHandlers }) {
  const ctx = s.context || {};
  const L = s.ledger || [];
  const ended = s.status === "ended";
  const facts = researchFacts(ctx);
  return (
    <div className={styles.left} data-testid="eval-left">
      <section className={styles.sect}>
        <h4 className={styles.hd}>Subject</h4>
        <b>{s.subject.name || "UNKNOWN"}</b>
        <div className={styles.sub}>
          {s.subject.founder || "founder UNKNOWN"} · {s.subject.kind}
          {ctx.slug && (
            <>
              {" "}
              · Conviction: <Link to={companyLink(ctx.slug)}>{ctx.name}</Link>
            </>
          )}
        </div>
      </section>
      <section className={styles.sect}>
        <h4 className={styles.hd}>Pitch deck (paste text — statements become {w.deck_label})</h4>
        {s.deck?.imported_at && (
          <div className={styles.sub}>
            imported {s.deck.imported_at} · {(s.deck.claims || []).length} claims
          </div>
        )}
        {!ended && <DeckForm id={s.id} />}
      </section>
      <section className={styles.sect}>
        <h4 className={styles.hd}>Existing Project Zero evidence</h4>
        <div className={styles.sub} data-testid="eval-existing">
          {existingEvidence(ctx)}
          {(ctx.adjacent || []).length > 0 && <div>Adjacent known: {(ctx.adjacent ?? []).map((a) => a.name).join(", ")}</div>}
          {facts && <div>Research facts: {facts}</div>}
        </div>
      </section>
      <section className={cx(styles.sect, styles.sectLast)}>
        <h4 className={styles.hd}>Claim ledger ({L.length})</h4>
        {L.length ? (
          newestFirst(L).map((cl) => <ClaimRow key={cl.id} cl={cl} w={w} ended={ended} handlers={handlers} />)
        ) : (
          <div className={styles.sub}>empty</div>
        )}
      </section>
    </div>
  );
}

function DeckForm({ id }: { id: string }) {
  const [deck, setDeck] = useState("");
  const deckA = useDeck();
  return (
    <>
      <textarea
        aria-label="Pitch deck text"
        rows={5}
        value={deck}
        onChange={(e) => setDeck(e.target.value)}
        placeholder="Paste the deck text or its key slides…"
      />
      <Button onClick={() => deckA.mutate({ id, text: deck }, { onSuccess: () => setDeck("") })} busy={deckA.isPending}>
        Import deck claims
      </Button>
    </>
  );
}

function ClaimRow({ cl, w, ended, handlers }: { cl: Claim; w: EvaluationsWorkspace; ended: boolean; handlers: ClaimHandlers }) {
  const acts = claimActions(cl, ended);
  return (
    <div className={styles.claim} data-claim={cl.id}>
      <EvState st={cl.state} /> <span className={styles.sub}>{familyLabel(w, cl.family)}</span>
      <div>{cl.text}</div>
      {acts === "verify" ? (
        <div className={styles.sub}>
          {cl.label || ""}
          {!ended && (
            <>
              {" · "}
              <button type="button" className={styles.lnk} onClick={() => handlers.onAttach(cl)}>
                attach public source
              </button>
              {" · "}
              <button type="button" className={styles.lnk} onClick={() => handlers.onOperator(cl)}>
                operator verified
              </button>
              {" · "}
              <DeferredLink className={styles.lnk} reason={NOT_PORTED.bridge}>
                verify via Scout 00
              </DeferredLink>
            </>
          )}
        </div>
      ) : acts === "resolve" ? (
        <div className={styles.sub}>
          <button type="button" className={styles.lnk} onClick={() => handlers.onResolve(cl)}>
            resolve with note
          </button>
        </div>
      ) : acts === "resolved" ? (
        <div className={styles.sub}>resolved: {cl.resolution?.note}</div>
      ) : null}
    </div>
  );
}
