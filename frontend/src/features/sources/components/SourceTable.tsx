import { cx } from "@/lib/format";
import { fbPrio, HEALTH_SHORT, srcHealth } from "../model/health";
import type { Source } from "../model/types";
import styles from "../Sources.module.css";

/** The registry table: one row per source in the workspace; a click selects it, the last cell switches it on / off. */
export function SourceTable({
  list,
  minReviewed,
  sel,
  onSel,
  onToggle,
}: {
  list: Source[];
  minReviewed?: number;
  sel: string | null;
  onSel: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.tbl} data-testid="source-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Type</th>
            <th>Geo</th>
            <th>Sectors</th>
            <th>Rel.</th>
            <th>Health</th>
            <th>Last OK</th>
            <th title="candidates found">Found</th>
            <th title="attention queue hits">Attn</th>
            <th title="researched">Res.</th>
            <th>Kept</th>
            <th title="sent to team">Sent</th>
            <th title="Manager positive / negative">Manager ±</th>
            <th title="Feedback-adjusted sourcing priority — ordering only, cap ±3, neutral until 5 reviewed companies">Fb. prio</th>
            <th>On</th>
          </tr>
        </thead>
        <tbody>
          {list.map((s) => (
            <SourceRow key={s.id} s={s} minReviewed={minReviewed} selected={sel === s.id} onSel={onSel} onToggle={onToggle} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SourceRow({
  s,
  minReviewed,
  selected,
  onSel,
  onToggle,
}: {
  s: Source;
  minReviewed?: number;
  selected: boolean;
  onSel: (id: string) => void;
  onToggle: (id: string, enabled: boolean) => void;
}) {
  const [h, hl] = srcHealth(s);
  const q = s.quality || {};
  const fb = s.feedback || {};
  const prio = fbPrio(fb, minReviewed || 5);
  const sec = s.sectors || [];
  return (
    <tr className={cx(selected && styles.sel, !s.enabled && styles.off)} onClick={() => onSel(s.id)} data-id={s.id}>
      <td>
        <button type="button" className={styles.nameBtn} onClick={() => onSel(s.id)}>
          {s.name}
        </button>
      </td>
      <td className={styles.sub}>{s.kind || ""}</td>
      <td className={styles.sub}>{(s.geo || []).slice(0, 2).join("/")}</td>
      <td className={styles.sub} title={sec.join(", ")}>
        {sec.slice(0, 2).join(", ")}
        {sec.length > 2 ? ` +${sec.length - 2}` : ""}
      </td>
      <td className={styles.sub}>{(s.reliability || "").slice(0, 3)}</td>
      <td title={hl} className={styles.nowrap}>
        <span className={cx(styles.hdot, styles[`h_${h}`])} />
        <span className={styles.sub}>{HEALTH_SHORT[h]}</span>
      </td>
      <td className={cx(styles.sub, styles.nowrap)}>{(s.last_ok || "never").slice(5)}</td>
      <td className={styles.num}>{q.candidates_found ?? 0}</td>
      <td className={styles.num}>{q.attention_queue ?? 0}</td>
      <td className={styles.num}>{q.researched ?? 0}</td>
      <td className={styles.num}>{q.kept ?? 0}</td>
      <td className={styles.num}>{q.sent_to_omar ?? 0}</td>
      <td className={cx(styles.num, styles.nowrap)}>
        {q.omar_positive ?? 0} / {q.omar_negative ?? 0}
      </td>
      <td className={cx(styles.num, styles.nowrap)} title={fb.reason || ""}>
        {prio.value}
        {prio.progress && <span className="faint"> · {prio.progress}</span>}
      </td>
      <td onClick={(e) => e.stopPropagation()}>
        <input type="checkbox" checked={s.enabled} onChange={(e) => onToggle(s.id, e.target.checked)} aria-label={`Enable ${s.name}`} />
      </td>
    </tr>
  );
}
