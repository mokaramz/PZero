import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Badge, Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { NETWORK_KEYS, PERSON_SAVE, type PersonSaveResult } from "../api";
import { STRENGTH_TONE, STRENGTH_WIDTH, stripSuggested, today } from "../model/peopleUtil";
import type { PeoplePayload, Person, PersonSaveBody } from "../model/types";
import styles from "../Network.module.css";

/** The warm path to a person: through the introducer, direct once you know them, otherwise cold. */
function warmPath(p: Person): string {
  if (p.introduced_by_name) return `via ${p.introduced_by_name}`;
  return p.relationship_strength && p.relationship_strength !== "met_once" ? "direct" : "cold — find an intro";
}

/** Right rail: strength, warm path, last contact, follow-up editor, log contact (v1 pplRail). */
export function PersonRail({ p, data, onEdit }: { p: Person; data: PeoplePayload; onEdit: () => void }) {
  const navigate = useNavigate();
  const [na, setNa] = useState(stripSuggested(p.next_action));
  const [nd, setNd] = useState(p.next_action_date || "");
  const [note, setNote] = useState("");
  const saveNext = useAction<PersonSaveBody, PersonSaveResult>(PERSON_SAVE, { invalidates: NETWORK_KEYS, label: "Saving the follow-up", success: "Follow-up saved" });
  const logTouch = useAction<PersonSaveBody, PersonSaveResult>(PERSON_SAVE, { invalidates: NETWORK_KEYS, label: "Logging the contact", success: "Contact logged" });

  const strength = p.relationship_strength ?? "";
  const st = data.strengths[strength] || "—";

  const log = async () => {
    const d = today();
    const body: Record<string, string> = { id: p.id, last_interaction: d };
    if (note.trim()) body.notes = `${p.notes ? `${p.notes}\n` : ""}${d} — ${note.trim()}`;
    const r = await logTouch.mutateAsync(body).catch(() => null);
    if (r) setNote("");
  };

  return (
    <aside className={styles.rail} aria-label="Relationship" data-testid="person-rail">
      <div className={styles.hd}>Relationship</div>
      <div className={styles.rlBlk}>
        <div className="muted small">Strength</div>
        <div className={styles.rlv}>
          <span className={cx(styles.dot, styles[`dot_${STRENGTH_TONE[strength] ?? "faint"}`])} />
          {st}
        </div>
        <div className={styles.sbar}>
          <i style={{ width: STRENGTH_WIDTH[strength] ?? "15%" }} />
        </div>
      </div>
      <div className={styles.rlBlk}>
        <div className="muted small">Warm path</div>
        <div className={styles.rlv}>{warmPath(p)}</div>
      </div>
      <div className={styles.rlBlk}>
        <div className="muted small">Last contact</div>
        <div className={styles.rlv}>
          {p.last_interaction ? (
            <>
              {p.last_interaction}
              {p.days_since_touch != null && <span className="muted small"> ({p.days_since_touch}d ago)</span>}
            </>
          ) : (
            <span className="muted">never logged</span>
          )}
        </div>
      </div>
      <div className={styles.rlBlk}>
        <div className="muted small">Follow-up</div>
        <div className={styles.rlv}>
          {p.next_action ? (
            <>
              {p.due && <Badge tone="red">DUE</Badge>} {stripSuggested(p.next_action).slice(0, 80)}
            </>
          ) : (
            <span className="muted">none set</span>
          )}
          {p.next_action_date && <div className="muted small">{p.next_action_date}</div>}
        </div>
        <input aria-label="Next action" placeholder="Set next action…" value={na} onChange={(e) => setNa(e.target.value)} />
        <input aria-label="Next action date" type="date" value={nd} onChange={(e) => setNd(e.target.value)} />
        <Button className={styles.full} busy={saveNext.isPending} onClick={() => saveNext.mutate({ id: p.id, next_action: na.trim(), next_action_date: nd })}>
          Save follow-up
        </Button>
      </div>
      <div className={styles.rlBlk}>
        <div className="muted small">Add interaction / note</div>
        <input aria-label="Interaction note" placeholder="What happened? (appended to notes)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button variant="primary" className={styles.full} busy={logTouch.isPending} onClick={() => void log()}>
          Log contact today
        </Button>
        <Button className={styles.full} onClick={() => navigate(`/founder-calls?${new URLSearchParams({ log: "1", person_id: p.id, name: p.name, company: p.company || "" })}`)}>
          Log founder call
        </Button>
        <Button className={styles.full} onClick={onEdit}>
          Edit full profile
        </Button>
        {p.linkedin && (
          <a className={styles.btnLink} href={p.linkedin} target="_blank" rel="noreferrer">
            LinkedIn ↗
          </a>
        )}
      </div>
    </aside>
  );
}
