import type { ReactNode } from "react";

import { Badge, Button, Callout } from "@/components/ui";
import type { Call, CallsWorkspace } from "../model/types";
import { DueTag, FC_LABEL, FcLabel, Unk } from "./bits";
import styles from "../FounderCalls.module.css";

function Box({ title, children, className }: { title: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={className ? `${styles.box} ${className}` : styles.box}>
      <h3 className={styles.boxHead}>{title}</h3>
      <div className={styles.boxBody}>{children}</div>
    </section>
  );
}

/** One call: the facts, the answers per template section, the claims, risks, next action and the private judgment.
 *  Edit, Export memo and Prepare Manager briefing sit in its bar. */
export function CallDetail({
  fc,
  call: c,
  onEdit,
  onMemo,
  onBriefing,
  onFollowup,
}: {
  fc: CallsWorkspace;
  call: Call;
  onEdit: () => void;
  onMemo: () => void;
  onBriefing: () => void;
  onFollowup: (done: boolean) => void;
}) {
  const t = fc.templates[c.call_type] ?? { sections: [] };
  const na = c.next_action || { text: "", owner: "", due: "" };
  const a = c.assessment || {};
  const ans = c.answers || {};
  return (
    <div className={styles.pane} data-testid="call-detail">
      <div className={styles.paneBar}>
        <b className={styles.paneTitle}>{c.founder_name}</b>
        <span className={styles.sub}>{c.company_name}</span>
        <Badge>{c.call_type_label}</Badge>
        <Badge tone="blue">
          {c.date}
          {c.time ? ` ${c.time}` : ""} · {c.channel}
        </Badge>
        <DueTag state={c.due_state} />
        <span className="grow" />
        <div className={styles.paneActs}>
          <Button onClick={onEdit}>Edit</Button>
          <Button onClick={onMemo}>Export memo (.md)</Button>
          <Button onClick={onBriefing}>Prepare Manager briefing</Button>
        </div>
      </div>
      <Callout tone="amber">
        Private research note. Everything the founder said is <FcLabel /> — it does not verify identity or founder status and changes no Gold/Strong
        bucket, ranking or evidence gate. Verify publicly via the sourced-evidence workflow before anything leaves this notebook.
      </Callout>

      <Box
        title={
          <>
            Summary <span className={styles.boxHeadSub}>— {c.summary_label}</span>
          </>
        }
      >
        {c.summary}
      </Box>

      <Box title="Call facts">
        <div>
          <b>Participants:</b> {(c.participants || []).join(", ") || "UNKNOWN"}
        </div>
        <div>
          <b>Discovery origin:</b> {c.discovery_origin || "UNKNOWN"} · <b>Introduction path:</b> {c.intro_path || "UNKNOWN"}
        </div>
        <div>
          <b>Objective:</b> {c.objective || "UNKNOWN"}
        </div>
        <div className={styles.sub}>
          created {c.created} · updated {c.updated} · call id {c.id} · founder id {c.founder_id} · company id {c.company_id}
        </div>
      </Box>

      <Box title="Questions and answers">
        {t.sections.length ? (
          t.sections.map((s, i) => {
            const r = ans[s.id] || { a: "", unknown: true, followups: {} };
            const fu = Object.entries(r.followups || {}).filter(([, v]) => v);
            return (
              <div key={s.id} className={styles.qa}>
                <div className={styles.q}>
                  {i + 1}. {s.q} <FcLabel />
                </div>
                <div className={styles.a}>{r.unknown || !r.a ? <Unk text="UNKNOWN — not answered" /> : r.a}</div>
                {fu.length > 0 && (
                  <ul className={styles.fuList}>
                    {fu.map(([j, v]) => (
                      <li key={j}>
                        <span className={styles.sub}>{s.followups[Number(j)] ?? ""}</span> — {v}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })
        ) : (
          <span className={styles.sub}>no template sections</span>
        )}
      </Box>

      <Box title="Exact founder claims">
        {(c.claims || []).length ? (
          <ul className={styles.claims}>
            {c.claims.map((x, i) => (
              <li key={i}>
                “{x.text}” <FcLabel text={x.label || FC_LABEL} />
              </li>
            ))}
          </ul>
        ) : (
          <span className={styles.sub}>none recorded</span>
        )}
      </Box>

      <Box title="Smooth Operator's private observations">
        <div className={styles.preWrap}>{c.observations || <span className={styles.sub}>none</span>}</div>
      </Box>

      <Box title="Risks and unanswered questions">
        <div>
          <b>Risks:</b> {(c.risks || []).length ? c.risks.join(" · ") : <span className={styles.sub}>none recorded</span>}
        </div>
        <div>
          <b>Unanswered:</b> {(c.open_questions || []).length ? c.open_questions.join(" · ") : <span className={styles.sub}>none recorded</span>}
        </div>
      </Box>

      <Box title="Next action">
        {na.text ? (
          <div className={styles.naRow}>
            <DueTag state={c.due_state} /> {na.text}{" "}
            <span className={styles.sub}>
              — {na.owner || "Smooth Operator"}
              {na.due ? ` · due ${na.due}` : ""}
              {na.done ? ` · done ${na.done_on || ""}` : ""}
            </span>{" "}
            {na.done ? (
              <Button size="sm" onClick={() => onFollowup(false)}>
                Reopen
              </Button>
            ) : (
              <Button size="sm" onClick={() => onFollowup(true)}>
                Mark done
              </Button>
            )}
          </div>
        ) : (
          <span className={styles.sub}>none set</span>
        )}
      </Box>

      <Box title="Post-call judgment (private)">
        {fc.assessment_fields.map(([key, label]) => (
          <div key={key}>
            <b>{label}:</b> {a[key] ? a[key] : <Unk />}
          </div>
        ))}
        <div>
          <b>Recommendation:</b> {a.recommendation ? <Badge tone="amber">{a.recommendation}</Badge> : <Unk />} · <b>Confidence:</b>{" "}
          {a.confidence ? a.confidence : <Unk />}
        </div>
        <div>
          <b>Next action:</b> {a.next_action || na.text || <Unk />}
        </div>
      </Box>
    </div>
  );
}
