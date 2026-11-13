/**
 * One answer from PZ Associate (ported from the old page): Ardea, the name and the "Documentation only" badge, the
 * Markdown text, the cited sources (in-app links when they have one), the documentation sections, the actions (open a
 * page, save as a draft — the draft is saved only after the confirmation Modal) and the trace (the read tools used and
 * the notes). New (revision 2): `notice`, shown under an answer the server did not save.
 */
import { Link } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui";
import { inAppLink, stateFor, toolsUsed } from "../model/associate";
import type { Msg } from "../model/types";
import { ArdeaAvatar } from "./Ardea";
import { Markdown } from "./Markdown";
import styles from "../Associate.module.css";

export function AssistantMessage({ m, latest, onDraft, notice }: { m: Msg; latest: boolean; onDraft: (title: string) => void; notice?: string }) {
  const used = toolsUsed(m);
  return (
    <article className={styles.asstRow} data-testid="associate-answer">
      <ArdeaAvatar size={32} state={latest ? stateFor(m) : "ready"} decorative className={styles.asstAvatar} />
      <div className={styles.asstBody}>
        <div className={styles.asstName}>
          PZ Associate
          {m.mode === "offline" && <span className={styles.offlineBadge}>Documentation only</span>}
        </div>
        <Markdown text={m.text} />
        {!!m.sources?.length && (
          <div className={styles.sources}>
            <span className={styles.metaLabel}>Sources</span>
            {m.sources.map((s) => {
              const to = inAppLink(s.link);
              return to ? (
                <Link key={`${s.kind}:${s.id}`} to={to} className={styles.sourceChip}>
                  {s.label || s.id}
                </Link>
              ) : (
                <span key={`${s.kind}:${s.id}`} className={styles.sourceChip}>
                  {s.label || s.id}
                </span>
              );
            })}
          </div>
        )}
        {!!m.docs?.length && (
          <div className={styles.docs}>
            <span className={styles.metaLabel}>Documentation</span> {m.docs.join(" · ")}
          </div>
        )}
        {!!m.actions?.length && (
          <div className={styles.actions}>
            {m.actions.map((a, i) => {
              const to = a.kind === "open" ? inAppLink(a.link) : null;
              return to ? (
                <Link key={i} to={to} className={styles.actionLink}>
                  {a.label} <Icon name="chevron" size={12} />
                </Link>
              ) : a.kind === "save_draft" ? (
                <Button key={i} size="sm" onClick={() => onDraft(a.title || "Associate draft")}>
                  {a.label}
                </Button>
              ) : null;
            })}
          </div>
        )}
        {(used.length > 0 || !!m.notes?.length) && (
          <div className={styles.trace} data-testid="associate-trace">
            {used.length > 0 && <span>Read: {used.join(", ")}</span>}
            {(m.notes ?? []).map((n) => (
              <span key={n}>{n}</span>
            ))}
          </div>
        )}
        {notice && (
          <p className={styles.banner} role="status" data-testid="associate-unsaved">
            {notice}
          </p>
        )}
      </div>
    </article>
  );
}
