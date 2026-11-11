import { Badge } from "@/components/ui";
import { cx } from "@/lib/format";
import { initials, linkedNames, OMAR_ID, pplCity, STRENGTH_TONE, STRENGTH_WIDTH } from "../model/peopleUtil";
import type { PeoplePayload, Person } from "../model/types";
import styles from "../Network.module.css";

/** One list row: name + DUE / WATCH, role · company · city, the strength scale and last contact, linked companies. */
export function PersonRow({ p, data, selected, onSelect }: { p: Person; data: PeoplePayload; selected: boolean; onSelect: () => void }) {
  const lk = linkedNames(p);
  const strength = p.relationship_strength ?? "";
  return (
    <li>
      <button type="button" className={cx(styles.row, selected && styles.rowSel)} onClick={onSelect} aria-current={selected || undefined} data-testid="person-row">
        <span className={cx(styles.avatar, p.id === OMAR_ID && styles.avatarNavy)}>{initials(p.name)}</span>
        <span className={styles.rowBody}>
          <span className={styles.rowL1}>
            <b>{p.name}</b>
            {p.due && <Badge tone="red">DUE</Badge>}
            {p.watch && <Badge>WATCH</Badge>}
          </span>
          <span className="muted small">
            {p.role || ""}
            {p.company ? ` · ${p.company}` : ""}
            {p.location ? ` · ${pplCity(p)}` : ""}
            {p.radar_state && (
              <>
                {" "}
                · <Badge tone="blue">{p.radar_state}</Badge>
              </>
            )}
            {p.contact_channel ? ` · ${p.contact_channel}` : ""}
          </span>
          <span className={styles.rowL3}>
            <span className={cx(styles.dot, styles[`dot_${STRENGTH_TONE[strength] ?? "faint"}`])} />
            <span className="muted small">{data.strengths[strength] || "—"}</span>
            <span className={styles.sbar}>
              <i style={{ width: STRENGTH_WIDTH[strength] ?? "15%" }} />
            </span>
            <span className="muted small">{p.last_interaction ? `last ${p.last_interaction}` : "no contact logged"}</span>
          </span>
          {(lk.length > 0 || p.why_interesting) && (
            <span className={cx("small", styles.rowL4)}>
              {lk.length > 0 && <b className={styles.navy}>{lk.slice(0, 3).join(" · ")}</b>}
              {p.why_interesting && <span className="muted">{`${lk.length ? " — " : ""}${p.why_interesting.slice(0, 70)}`}</span>}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}
