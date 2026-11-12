import { Async, Button, Drawer } from "@/components/ui";
import { useCopy } from "@/lib/hooks";
import { useOutreachEmail } from "../api";

/** v1 drawerFor(slug,'email') — the timing-aware outreach draft with a Copy button ("Email draft" in Actions). */
export function EmailDrawer({ slug, onClose }: { slug: string | null; onClose: () => void }) {
  const q = useOutreachEmail(slug);
  const copy = useCopy();
  return (
    <Drawer
      open={!!slug}
      onClose={onClose}
      title="Outreach email"
      actions={
        <Button variant="primary" onClick={() => copy(q.data?.text ?? "")} disabled={!q.data}>
          Copy
        </Button>
      }
    >
      <Async q={q}>{(d) => <pre>{d.text}</pre>}</Async>
    </Drawer>
  );
}
