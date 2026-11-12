import { useMemo, useState } from "react";

import { Button, Callout, ErrorBox, Modal, Spinner } from "@/components/ui";
import { useAdoptCandidate, useCoverage } from "../api";
import { filterEcosystems, STATES } from "../model/coverage";
import type { CovCandidate } from "../model/types";
import styles from "../Ecosystems.module.css";
import { CoverageDetail } from "./CoverageDetail";
import { CoverageTable } from "./CoverageTable";
import { CovTag } from "./CovTag";

/**
 * Coverage intelligence — where Project Zero can and cannot see (`GET ecosystems/coverage`). Candidates are adopted one
 * at a time, explicitly, behind a confirmation (`POST ecosystems/coverage/adopt`).
 */
export function CoveragePanel() {
  const q = useCoverage();
  const [filter, setFilter] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [adopting, setAdopting] = useState<CovCandidate | null>(null);
  const adopt = useAdoptCandidate();

  const c = q.data;
  const rows = useMemo(() => filterEcosystems(c?.ecosystems ?? [], filter), [c, filter]);
  if (q.isLoading)
    return (
      <div className={styles.box}>
        <Spinner label="Loading coverage…" />
      </div>
    );
  if (q.error || !c) return <ErrorBox error={q.error ?? "Coverage unavailable"} onRetry={() => q.refetch()} />;
  const detail = sel ? c.ecosystems.find((e) => e.id === sel) : undefined;

  const confirm = async () => {
    if (!adopting) return;
    try {
      await adopt.mutateAsync({ id: adopting.id, confirm: true });
    } catch {
      /* the failure toast is already shown */
    }
    setAdopting(null);
  };

  return (
    <section className={styles.box} data-testid="coverage">
      <h3 className={styles.hd}>Coverage intelligence — where Project Zero can and cannot see</h3>
      <p className="muted small">{c.note}</p>
      <div className={styles.covSum}>
        <span className="muted small" data-testid="coverage-summary">
          {c.registry_size} ecosystems · {c.sources_declared} configured sources declared ({c.sources_with_override} from coverage_sources.json) · Grok audit
          candidates: <b>{c.candidates?.total ?? 0}</b> declared, {c.candidates?.adopted ?? 0} adopted — a candidate never counts as coverage until you
          adopt it and a scan retrieves records
        </span>
        {STATES.map((s) => (
          <span key={s} className="small" data-testid={`coverage-count-${s}`}>
            <CovTag st={s} /> {c.counts[s] ?? 0}
          </span>
        ))}
        <input aria-label="Filter ecosystems" placeholder="Filter ecosystems…" value={filter} onChange={(e) => setFilter(e.target.value)} className={styles.covFilter} />
      </div>
      {!!c.new_ecosystems?.length && (
        <Callout tone="amber" data-testid="new-ecosystems">
          <b>{c.labels.new}</b>
          {c.new_ecosystems.map((n) => (
            <div key={n.place} className="small">
              {n.place}
              {n.country ? ` (${n.country})` : ""} — {n.signals} signals ({n.kinds.join(", ")}): {n.examples.join(", ")} · {n.action}
            </div>
          ))}
        </Callout>
      )}
      <CoverageTable rows={rows} families={c.families} sel={sel} onSel={setSel} />
      {detail && <CoverageDetail e={detail} families={c.families} onAdopt={setAdopting} />}
      <Modal
        open={!!adopting}
        onClose={() => setAdopting(null)}
        title="Adopt as watcher?"
        footer={
          <>
            <Button onClick={() => setAdopting(null)}>Cancel</Button>
            <Button variant="primary" busy={adopt.isPending} onClick={confirm}>
              Adopt as watcher
            </Button>
          </>
        }
      >
        <p>
          Adopt "{adopting?.name}" as a configured watcher? It stays UNKNOWN until a scan retrieves it and becomes HEALTHY only with productive records.
          One source, explicit — nothing else is activated.
        </p>
      </Modal>
    </section>
  );
}
