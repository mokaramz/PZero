/**
 * "Drafts" (ported from the old page): the saved drafts, newest first as the server sends them, read only while the
 * drawer is open. Copy puts a draft on the clipboard; Remove sends `POST associate/draft_delete`. Nothing is sent.
 */
import { Button, Drawer, ErrorBox, Spinner } from "@/components/ui";
import { useAction, useCopy } from "@/lib/hooks";
import { ASSOCIATE, useDrafts } from "../api";
import { when } from "../model/associate";
import styles from "../Associate.module.css";

export function DraftsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useDrafts(open);
  const del = useAction<{ id: string }>(ASSOCIATE.draftDelete, { label: "Removing draft", success: "Draft removed", invalidates: [ASSOCIATE.drafts] });
  const copy = useCopy();
  return (
    <Drawer open={open} onClose={onClose} width={640} title="Drafts">
      <p className={styles.modalNote}>Prepared text you chose to keep. Nothing here has been sent — copy it into your own email or message when you decide.</p>
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} onRetry={() => q.refetch()} />}
      {q.data && q.data.drafts.length === 0 && <p className={styles.asideEmpty}>No drafts yet.</p>}
      <ul className={styles.draftList}>
        {q.data?.drafts.map((d) => (
          <li key={d.id} className={styles.draft}>
            <div className={styles.draftHead}>
              <strong>{d.title}</strong>
              <span className={styles.convWhen}>{when(d.created)}</span>
            </div>
            <pre className={styles.draftBody}>{d.body}</pre>
            <div className={styles.actions}>
              <Button size="sm" onClick={() => copy(d.body, "Draft copied")}>
                Copy
              </Button>
              <Button size="sm" variant="ghost" onClick={() => del.mutate({ id: d.id })}>
                Remove
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}
