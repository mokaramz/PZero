import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button, Callout, Drawer, ErrorBox, Spinner } from "@/components/ui";
import { usePair, useProposals, useReview } from "../api";
import { useFr } from "../context";
import { pairSpec } from "../model/dialogs";
import type { Company, Proposals } from "../model/types";
import { chosenBindings, recommendedPending, recommendedToast, reviewToast, storedBindings } from "../model/view";
import { ReviewRow } from "./ReviewRow";
import styles from "../FounderRadar.module.css";

/**
 * Proposal Review (v1 openReview, `?review=`): one row per fact, alternatives collapsed, provenance + passage + URL per
 * row, a per-row founder binding with an individual pairing, and a bulk "Confirm recommended facts" that never includes
 * an identity.
 */
export function ReviewDrawer({ companyKey, onClose }: { companyKey: string | null; onClose: () => void }) {
  const { data } = useFr();
  const c: Partial<Company> = (data.companies ?? []).find((x) => x.key === companyKey) ?? {};
  return (
    <Drawer open={!!companyKey} onClose={onClose} title={`Review — ${c.name || ""}`} width={880}>
      {companyKey && <ReviewLoader key={companyKey} companyKey={companyKey} c={c} />}
    </Drawer>
  );
}

function ReviewLoader({ companyKey, c }: { companyKey: string; c: Partial<Company> }) {
  const q = useProposals(companyKey);
  if (q.isLoading) return <Spinner label="Loading proposals…" />;
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  return q.data ? <ReviewBody companyKey={companyKey} c={c} r={q.data} /> : null;
}

function ReviewBody({ companyKey: key, c, r }: { companyKey: string; c: Partial<Company>; r: Proposals }) {
  const { data: FR, actions } = useFr();
  const toast = useToast();
  const review = useReview();
  const pair = usePair();
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [bind, setBind] = useState<Record<string, string>>(() => storedBindings(r.groups ?? []));
  const G = r.groups ?? [];
  const S = r.summary ?? {};
  const rec = new Set(r.recommended ?? []);

  // A fresh read (after a review or a pairing) restarts the selection from the stored bindings, as v1 re-rendered. An
  // unchanged read keeps the same object (react-query's structural sharing), so the selection stays.
  const [seen, setSeen] = useState(r);
  if (r !== seen) {
    setSeen(r);
    setBind(storedBindings(r.groups ?? []));
    setChecked(new Set());
  }

  const confirmRecommended = async () => {
    const ids = recommendedPending(G, r.recommended ?? []);
    if (!ids.length) {
      toast.show("No recommended facts to confirm", "info");
      return;
    }
    try {
      toast.show(recommendedToast(await review.mutateAsync({ key, confirm: ids, bindings: {} })), "ok");
    } catch {
      /* toasted */
    }
  };

  const submitReview = async (mode: "confirm" | "reject") => {
    const ids = [...checked];
    if (!ids.length) {
      toast.show("Select proposals first", "info");
      return;
    }
    try {
      toast.show(reviewToast(mode, await review.mutateAsync({ key, bindings: chosenBindings(bind), [mode]: ids })), "ok");
    } catch {
      /* toasted */
    }
  };

  const pairProposal = async (pid: string, name: string) => {
    const person = bind[pid];
    if (!person) {
      toast.show("Select the founder reference to pair first", "info");
      return;
    }
    if (!(await actions.ask(pairSpec(name, person, FR.people.find((x) => x.id === person))))) return;
    try {
      await pair.mutateAsync({ key, proposal: pid, person });
      toast.show("Pairing recorded — now Confirm selected", "ok");
    } catch {
      /* toasted */
    }
  };

  const busy = review.isPending || pair.isPending;
  return (
    <div className={styles.review} data-testid="fr-review">
      <div className={styles.revSummary}>
        <div>
          <div className={styles.hd}>Company</div>
          <div>
            <b>{c.name || ""}</b>
          </div>
          <div className={styles.sub}>
            {c.domain || ""} · Priority {c.priority_label || ""}
          </div>
        </div>
        <div>
          <div className={styles.hd}>Research summary</div>
          <div className={styles.sub}>
            {S.pages_retrieved || 0} page(s) retrieved · {S.pages_blocked || 0} blocked/skipped · {S.facts_proposed || 0} fact(s) · {S.founder_candidates || 0}{" "}
            founder candidate(s) · {S.confirmed || 0} confirmed
          </div>
        </div>
        <div>
          <div className={styles.hd}>Recommended facts</div>
          <div className={styles.big}>{S.recommended || 0}</div>
          <div className={styles.sub}>{S.hidden_duplicates || 0} duplicate passage(s) hidden</div>
        </div>
        <div>
          <div className={styles.hd}>Missing Gold/Strong requirements</div>
          <div className={styles.sub}>{(S.missing_gate ?? []).join(", ") || "none — company facts complete"}</div>
        </div>
      </div>
      <Callout tone="amber">
        One row per fact. Quoted public facts and <i>machine inferences</i> are marked separately. Nothing counts until confirmed; founder identity always
        needs individual pairing + confirmation.
      </Callout>
      <div className={styles.revActions}>
        <Button variant="primary" onClick={confirmRecommended} busy={review.isPending} disabled={busy}>
          Confirm recommended facts ({S.recommended || 0})
        </Button>
        <Button onClick={() => submitReview("confirm")} disabled={busy}>
          Confirm selected
        </Button>
        <Button onClick={() => submitReview("reject")} disabled={busy}>
          Reject selected
        </Button>
        <Button onClick={() => actions.refreshResearch(key)} disabled={actions.busy}>
          Refresh research
        </Button>
        {r.refreshed_at && <span className={styles.sub}>last refresh {r.refreshed_at} (observation time — never recency)</span>}
      </div>
      {G.length ? (
        G.map((g) => (
          <ReviewRow
            key={g.key}
            g={g}
            founders={c.founders ?? []}
            recommended={rec.has(g.best.id)}
            checked={checked.has(g.best.id)}
            onCheck={(on) =>
              setChecked((s) => {
                const n = new Set(s);
                if (on) n.add(g.best.id);
                else n.delete(g.best.id);
                return n;
              })
            }
            bound={bind[g.best.id] ?? ""}
            onBind={(v) => setBind((b) => ({ ...b, [g.best.id]: v }))}
            onPair={() => pairProposal(g.best.id, g.best.person?.name || String(g.value))}
          />
        ))
      ) : (
        <div className={styles.sub}>No proposals yet — press Research company.</div>
      )}
      {(r.history ?? []).length > 0 && (
        <details className={styles.details}>
          <summary>Decision history ({r.history!.length}, append-only)</summary>
          <div className={styles.sub}>
            {r.history!.slice(-12).map((h, i) => (
              <div key={i}>
                {h.on} {h.proposal} {h.from}→<b>{h.to}</b>
                {h.person ? " · " + h.person : ""}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
