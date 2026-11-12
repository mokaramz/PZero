/**
 * Public work (v1 view `work`, review 020): ideas, drafts, published pieces and the inbound they generate.
 * Reads `GET content`; the drawer writes `POST content/save` and `POST content/delete` (see ./api).
 */
import { useState } from "react";

import { Async, Button, Callout, PageHeader, Panel } from "@/components/ui";
import { useContent } from "./api";
import { ItemDrawer } from "./components/ItemDrawer";
import { WorkTable } from "./components/WorkTable";
import type { Item } from "./model/item";

export default function PublicWorkPage() {
  const q = useContent();
  const [editing, setEditing] = useState<Item | "new" | null>(null);
  return (
    <>
      <PageHeader
        title="Public work"
        subtitle="Good work → reputation → relationships → inbound. Track ideas, drafts, published pieces and the inbound they generate."
        actions={
          <Button variant="primary" onClick={() => setEditing("new")}>
            + New item
          </Button>
        }
      />
      <Callout tone="amber">
        <b>Positioning rule (from Manager):</b> never present yourself publicly as a Project A Scout. Public identity = Porsche / automotive / engineering. This
        tracker will remind you on every item.
      </Callout>
      <Panel>
        <Async q={q}>{(d) => <WorkTable items={d.items} onOpen={setEditing} />}</Async>
      </Panel>
      {editing && <ItemDrawer item={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}
