/**
 * The conversation drawer (the page's aside, ported from the old page): the saved conversations, newest first as the
 * server sends them; a click opens one, the × removes it (`POST associate/conversation_delete`).
 */
import { Icon } from "@/components/Icon";
import { Spinner } from "@/components/ui";
import { cx } from "@/lib/format";
import { when } from "../model/associate";
import type { ConvRow } from "../model/types";
import { ArdeaMark } from "./Ardea";
import styles from "../Associate.module.css";

export function ConversationList({
  rows,
  loading,
  current,
  onOpen,
  onDelete,
}: {
  rows: ConvRow[];
  loading: boolean;
  current: string | null;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className={styles.aside} aria-label="Conversations">
      <div className={styles.asideHead}>Conversations</div>
      {loading ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <p className={styles.asideEmpty}>
          <ArdeaMark size={12} className={styles.emptyMark} />
          Nothing yet. Your conversations are saved in the Project Zero database.
        </p>
      ) : (
        <ul className={styles.convList}>
          {rows.map((c) => (
            <li key={c.id} className={cx(styles.convRow, c.id === current && styles.convOn)}>
              <button type="button" className={styles.convOpen} onClick={() => onOpen(c.id)} aria-current={c.id === current || undefined}>
                <span className={styles.convTitle}>{c.title || "Conversation"}</span>
                <span className={styles.convWhen}>{when(c.updated)}</span>
              </button>
              <button type="button" className={styles.convDel} aria-label={`Remove conversation: ${c.title}`} title="Remove conversation" onClick={() => onDelete(c.id)}>
                <Icon name="close" size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
