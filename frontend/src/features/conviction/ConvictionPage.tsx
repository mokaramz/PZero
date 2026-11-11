/**
 * Conviction (v1 view `pipe`, review 011): the companies you chose to keep following — status and next action first.
 * Deep link: /conviction?company=<slug> (searches every entry, dropped ones too), optional &seg=inv|watch|gated. Both
 * are kept in the URL and changed with history replace, as before.
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { DeferredButton } from "@/components/Deferred";
import { StageTrace } from "@/components/StageTrace";
import { Async, Button, EmptyState, PageHeader, Segmented, Toolbar } from "@/components/ui";
import { cx } from "@/lib/format";
import { useMeta, usePipeline } from "./api";
import { CompanyDetail } from "./components/CompanyDetail";
import { CompanyList } from "./components/CompanyList";
import { EditCompanyDrawer } from "./components/EditCompanyDrawer";
import { NOT_PORTED } from "./model/deferred";
import { pipeGroups, type Seg } from "./model/logic";
import type { Signal } from "./model/types";
import styles from "./Conviction.module.css";

const SEGS: Seg[] = ["all", "inv", "watch", "gated"];

export default function ConvictionPage() {
  const pipe = usePipeline();
  const meta = useMeta();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const segParam = params.get("seg") as Seg | null;
  const seg: Seg = segParam && SEGS.includes(segParam) ? segParam : "all";
  const [edit, setEdit] = useState<{ entry: Signal | null } | null>(null);

  const signals = useMemo(() => pipe.data?.signals ?? [], [pipe.data]);
  const groups = useMemo(() => pipeGroups(signals, q), [signals, q]);
  const ordered = [...groups.inv, ...groups.watch, ...groups.gated];
  const selSlug = params.get("company") ?? ordered[0]?.slug ?? null;
  const selected = signals.find((x) => x.slug === selSlug) ?? null;

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };

  const active = signals.filter((e) => e.status !== "dropped");
  const counts = `${active.length} companies · ${groups.gated.length} gated`;
  const fully = `${signals.filter((e) => e.sc?.fully_verified).length} fully verified`;

  return (
    <div className={styles.page}>
      <PageHeader
        title="Conviction"
        subtitle="The companies you chose to follow — what you think, and what to do next."
        actions={
          <StageTrace
            testId="conviction-trace"
            stages={["Signal", "Analysis", "Conviction"]}
            label={`From signal through analysis to conviction${pipe.data ? `: ${active.length} companies in Conviction, ${fully}` : ""}`}
          />
        }
      />
      <Toolbar>
        <div className={styles.tGroup} role="group" aria-label="View">
          <input className={styles.filter} placeholder="Filter companies…" aria-label="Filter companies" value={q} onChange={(e) => setQ(e.target.value)} />
          <Segmented<Seg>
            label="Conviction segment"
            value={seg}
            onChange={(v) => update({ seg: v === "all" ? null : v })}
            options={[
              { value: "all", label: "All" },
              { value: "inv", label: "Investigate" },
              { value: "watch", label: "Watch" },
              { value: "gated", label: "Gated" },
            ]}
          />
          <span className={styles.counts} data-testid="pipe-counts" title={pipe.data ? fully : undefined}>
            {pipe.data ? counts : ""}
          </span>
        </div>
        <span className="grow" />
        <div className={styles.tGroup} role="group" aria-label="Operations">
          <Button variant="ghost" size="sm" onClick={() => setEdit({ entry: null })}>
            + Add company
          </Button>
          <DeferredButton variant="ghost" size="sm" reason={NOT_PORTED.weekly}>
            Weekly update
          </DeferredButton>
        </div>
        <div className={cx(styles.tGroup, styles.tQuiet)} role="group" aria-label="System">
          <DeferredButton variant="ghost" size="sm" reason={NOT_PORTED.radar}>
            Generate Radar
          </DeferredButton>
        </div>
      </Toolbar>

      <Async q={pipe} label="Loading pipeline…">
        {() => (
          <div className={styles.split}>
            <CompanyList groups={groups} seg={seg} selected={selected?.slug ?? null} onSelect={(slug) => update({ company: slug })} />
            {selected ? (
              <CompanyDetail key={selected.slug} e={selected} all={signals} meta={meta.data} actions={{ onEdit: () => setEdit({ entry: selected }) }} />
            ) : (
              <EmptyState>Select a company.</EmptyState>
            )}
          </div>
        )}
      </Async>

      <EditCompanyDrawer open={!!edit} entry={edit?.entry} onClose={() => setEdit(null)} onSaved={(slug) => update({ company: slug })} />
    </div>
  );
}
