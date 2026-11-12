import { useState } from "react";

import { Button, Callout, Drawer } from "@/components/ui";
import { useCopy } from "@/lib/hooks";
import { filterRows, type PickRow } from "../model/calls";
import { FcLabel } from "./bits";
import styles from "../FounderCalls.module.css";

export type MdView = { title: string; markdown: string; file: string };
export type Pick = { title: string; rows: PickRow[]; onPick: (id: string) => void };

/** Hands the Markdown to the browser as a file to save (nothing is written on the server). */
function saveFile(name: string, text: string) {
  const href = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(href), 2000);
}

/** Call memo / Manager briefing: rendered on request, never stored, never sent. Copy or download is the operator's click. */
export function MarkdownDrawer({ view, onClose }: { view: MdView | null; onClose: () => void }) {
  const copy = useCopy();
  return (
    <Drawer
      open={!!view}
      onClose={onClose}
      title={view?.title}
      width={760}
      actions={
        view && (
          <>
            <Button onClick={() => void copy(view.markdown, "Copied")}>Copy</Button>
            <Button variant="primary" onClick={() => saveFile(view.file, view.markdown)}>
              Download .md
            </Button>
          </>
        )
      }
    >
      <Callout tone="amber">
        <FcLabel /> Private research note — not a sourced fact, not sent anywhere.
      </Callout>
      <pre className={styles.md} data-testid="call-md">
        {view?.markdown}
      </pre>
    </Drawer>
  );
}

/** Link a founder / company to an existing record — stored in the private call notes only. */
export function PickDrawer({ pick, onClose }: { pick: Pick | null; onClose: () => void }) {
  const [q, setQ] = useState("");
  const rows = filterRows(pick?.rows ?? [], q);
  const close = () => {
    setQ("");
    onClose();
  };
  return (
    <Drawer open={!!pick} onClose={close} title={pick?.title} width={560}>
      <Callout tone="blue">
        Linking stores the link in your private call notes only — the existing record is not modified, and no call is lost or duplicated.
      </Callout>
      <input className={styles.pickQ} aria-label="Filter" placeholder="filter…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className={styles.pickList}>
        {rows.length ? (
          rows.map((r) => (
            <button
              type="button"
              key={r.id}
              className={styles.pickRow}
              onClick={() => {
                pick?.onPick(r.id);
                close();
              }}
            >
              <b>{r.label}</b>
              <span className={styles.sub}>{r.sub}</span>
            </button>
          ))
        ) : (
          <span className={styles.sub}>nothing to link to</span>
        )}
      </div>
    </Drawer>
  );
}
