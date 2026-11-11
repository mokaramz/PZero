import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Badge, Modal } from "@/components/ui";
import { isMissingEndpoint } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { ALL_ITEMS } from "../nav";
import { HIT_TONE, searchHits, type Events, type Hit, type People, type Pipeline } from "./searchHits";
import styles from "./CommandPalette.module.css";

/** Search sources are read only while the palette is open; one that is not ported yet (404) is not retried. */
function useSource<T>(path: string, open: boolean) {
  return useApi<T>(path, undefined, { enabled: open, retry: (failures, error) => !isMissingEndpoint(error) && failures < 1 });
}

/** Global search (Ctrl/Cmd+K): pages, pipeline companies, people and events. Deep-links via URL params. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const navigate = useNavigate();
  const pipeline = useSource<Pipeline>("pipeline", open);
  const people = useSource<People>("people", open);
  const events = useSource<Events>("events", open);

  const hits = useMemo(
    () => searchHits(q, { pages: ALL_ITEMS, pipeline: pipeline.data, people: people.data, events: events.data }),
    [q, pipeline.data, people.data, events.data],
  );
  const notPorted = [
    ["Companies", pipeline.error],
    ["people", people.error],
    ["events", events.error],
  ]
    .filter(([, error]) => isMissingEndpoint(error))
    .map(([name]) => name as string);

  const go = (h: Hit | undefined) => {
    if (!h) return;
    onClose();
    setQ("");
    navigate(h.to);
  };

  return (
    <Modal open={open} onClose={onClose} title="Search" width={620}>
      <input
        autoFocus
        className={styles.input}
        placeholder="Companies, people, events, pages…"
        value={q}
        aria-label="Search"
        onChange={(e) => {
          setQ(e.target.value);
          setActive(0);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setActive((a) => Math.min(a + 1, hits.length - 1));
          if (e.key === "ArrowUp") setActive((a) => Math.max(a - 1, 0));
          if (e.key === "Enter") go(hits[active]);
        }}
      />
      <ul className={styles.results} role="listbox">
        {hits.map((h, i) => (
          <li
            key={h.kind + h.to}
            role="option"
            aria-selected={i === active}
            className={i === active ? styles.active : undefined}
            onMouseEnter={() => setActive(i)}
            onClick={() => go(h)}
          >
            <Badge tone={HIT_TONE[h.kind]}>{h.kind}</Badge>
            <b>{h.name}</b>
            <span className="muted small">{h.meta}</span>
          </li>
        ))}
        {!hits.length && <li className="muted">No matches.</li>}
      </ul>
      {notPorted.length > 0 && (
        <p className="faint small" data-testid="search-not-ported">
          Search over {notPorted.join(", ")} — not ported yet
        </p>
      )}
    </Modal>
  );
}
