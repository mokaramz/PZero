/** The public-work items, in the order the server returns them; a title opens the item. Every cell is text (a stored
 *  value may be any JSON, Codex H-149); the ↗ link is shown for an http(s) url only. */
import { Badge } from "@/components/ui";
import {
  inboundOrNotes,
  kindTone,
  linkOf,
  textOf,
  type Item,
} from "../model/item";
import styles from "../PublicWork.module.css";

export function WorkTable({
  items,
  onOpen,
}: {
  items: Item[];
  onOpen: (item: Item) => void;
}) {
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.w90}>Status</th>
            <th>Title</th>
            <th className={styles.w90}>Platform</th>
            <th className={styles.w110}>Created</th>
            <th className={styles.w150}>Inbound / notes</th>
          </tr>
        </thead>
        <tbody>
          {items.map((x) => {
            const title = textOf(x.title);
            const href = linkOf(x.url);
            return (
              <tr key={x.id} data-testid="work-row">
                <td>
                  <Badge tone={kindTone(x.kind)}>
                    {textOf(x.kind) || "idea"}
                  </Badge>
                </td>
                <td>
                  <button
                    type="button"
                    className={styles.title}
                    onClick={() => onOpen(x)}
                  >
                    {title}
                  </button>
                  {href && (
                    <>
                      {" "}
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`Open ${title}`}
                      >
                        ↗
                      </a>
                    </>
                  )}
                </td>
                <td className={styles.sub}>{textOf(x.platform)}</td>
                <td className={styles.sub}>{textOf(x.created)}</td>
                <td className={styles.sub}>{inboundOrNotes(x)}</td>
              </tr>
            );
          })}
          {items.length === 0 && (
            <tr>
              <td colSpan={5} className={styles.empty}>
                Nothing yet. One useful post about industrial AI (from your
                automotive seat) is the right first item.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
