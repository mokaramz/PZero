import type { ReactNode } from "react";

import { Badge, Button } from "@/components/ui";
import type { ReportRow } from "@/features/deal-flow/model/types";
import { cx } from "@/lib/format";
import { funnel, latestScan, limitation, scanTone, signed, srcHealth } from "../model/health";
import type { Source, SourcesPayload } from "../model/types";
import styles from "../Sources.module.css";

function Sect({ title, children, id }: { title: string; children: ReactNode; id?: string }) {
  return (
    <section className={styles.sect} id={id}>
      <h4 className={styles.hd}>{title}</h4>
      <div className={styles.ppt}>{children}</div>
    </section>
  );
}

/**
 * The selected source: what it monitors, why it matters, health (with the on / off switch), coverage, yield, the
 * feedback priority, the quality funnel, limitations and the latest scan result. The old "ask Scout 00 for a
 * replacement" link (failing sources) is gone with the Scout Bridge; nothing stands in its place.
 */
export function SourceDetail({
  s,
  m,
  report,
  onToggle,
  toggling,
}: {
  s: Source | undefined;
  m: SourcesPayload;
  report: ReportRow[];
  onToggle: (id: string, enabled: boolean) => void;
  toggling: boolean;
}) {
  if (!s) return <div className={styles.detEmpty}>Select a source.</div>;
  const [h, hl] = srcHealth(s);
  const y = s.yield || {};
  const fb = s.feedback || {};
  const rep = latestScan(s, report);
  const rows = funnel(s);
  const maxF = Math.max(1, ...rows.map(([, v]) => v));
  const limit = limitation(s);
  return (
    <div className={styles.det} data-testid="source-detail">
      <div className="row">
        <Badge>{(s.kind || "source").toUpperCase()}</Badge>
        <Badge tone={s.reliability === "high" ? "green" : "neutral"}>{(s.reliability || "").toUpperCase()} RELIABILITY</Badge>
        {s.stage && <Badge>{String(s.stage).replace("_", " ").toUpperCase()}</Badge>}
      </div>
      <div className={styles.srcName}>{s.name}</div>
      <div className="faint small">
        {(s.geo || []).join(", ")} · {(s.sectors || []).join(", ")}
        {s.freshness ? ` · ${s.freshness}` : ""}
      </div>

      <Sect title="What it monitors">
        {s.url ? (
          <a href={s.url} target="_blank" rel="noreferrer" className={styles.url}>
            {s.url.replace(/^https?:\/\//, "").slice(0, 70)} ↗
          </a>
        ) : (
          <span className="faint">no URL</span>
        )}
        {s.parser && <div className="faint">parser: {s.parser}</div>}
      </Sect>
      <Sect title="Why it matters">{s.notes ? s.notes : <span className="faint">No description on file.</span>}</Sect>
      <Sect title="Current health">
        <span className={cx(styles.hdot, styles[`h_${h}`])} /> {hl}
        <div className="faint">
          last successful scan: {s.last_ok || "never"} · last count: {s.last_result_count == null ? "—" : s.last_result_count} · consecutive failures:{" "}
          {s.failures_in_row || 0}
          {s.enabled ? "" : " · "}
          {!s.enabled && <b>disabled</b>}
        </div>
        <Button size="sm" className={styles.mt6} onClick={() => onToggle(s.id, !s.enabled)} disabled={toggling}>
          {s.enabled ? "Disable source" : "Enable source"}
        </Button>
      </Sect>
      <Sect title="Coverage">
        <div className={styles.tags}>
          {[...(s.geo || []), ...(s.sectors || [])].map((g) => (
            <span key={g} className={styles.tag}>
              {g}
            </span>
          ))}
        </div>
        {s.geo_scope && <div className="faint">scope: {s.geo_scope}</div>}
      </Sect>
      <Sect title="Recent yield">
        <span className={styles.num}>
          kept {y.kept || 0} · research {y.research || 0} · rejected {y.rejected || 0}
          {s.last_result_count != null ? ` · last scan returned ${s.last_result_count}` : ""}
        </span>
      </Sect>
      <Sect title={m.feedback_label || "Feedback-adjusted sourcing priority"} id="srcFeedback">
        <b className={styles.num}>{signed(fb.adjustment || 0)}</b> <span className="faint">{fb.reason || "neutral"}</span>
        <div className="faint">
          Ordering only, from Keep / Research / Reject and Manager ± decisions on candidates this source surfaced. Neutral prior; adjusted after{" "}
          {m.feedback_min_reviewed || 5} reviewed companies (Keep + Manager outcome on one company count once; a changed outcome replaces the earlier one); capped at ±
          {m.feedback_cap || 3}. It never disables a source, never stops fetching, never rejects or hides a candidate. No model is trained — a bounded counter of your
          own decisions.
        </div>
      </Sect>
      <Sect title="Quality funnel">
        <div className={styles.funnel}>
          {rows.map(([label, v]) => (
            <div key={label} className={styles.frow}>
              <span className={styles.fl}>{label}</span>
              <span className={styles.fb}>
                <i style={{ width: `${Math.round((v / maxF) * 100)}%` }} />
              </span>
              <span className={styles.num}>{v}</span>
            </div>
          ))}
        </div>
        <div className="faint">Counted once per candidate; downstream steps credit the deterministic quality source.</div>
      </Sect>
      <Sect title="Limitations / known issues">{limit ?? <span className="faint">None recorded.</span>}</Sect>
      <Sect title="Latest scan result">
        {rep ? (
          <>
            <Badge tone={scanTone(rep.status)}>{(rep.status || "").toUpperCase()}</Badge> {rep.note || ""}
          </>
        ) : (
          <span className="faint">No entry in the last scan report.</span>
        )}
      </Sect>
    </div>
  );
}
