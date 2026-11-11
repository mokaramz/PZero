/**
 * Network (v1 view `people`, review 013): relationships — who you know, how warm it is, and what to do next.
 * Deep links: /network?person=<id> selects a person (history replace, as before); &edit=1 opens their edit drawer once
 * and is then removed from the URL. Wide screens (≥ 1240px) show list | profile | rail; narrower ones open the person in
 * a drawer.
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { GroupedFilters } from "@/components/attention";
import { Async, Button, Chip, Drawer, EmptyState, PageHeader, Toolbar } from "@/components/ui";
import { cx } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { useMedia } from "@/lib/useMedia";
import { usePeople, usePipelineSlice } from "./api";
import { IdentityReview } from "./components/IdentityReview";
import { PersonForm } from "./components/PersonForm";
import { PersonProfile } from "./components/PersonProfile";
import { PersonRail } from "./components/PersonRail";
import { PersonRow } from "./components/PersonRow";
import { TalentGraph } from "./components/TalentGraph";
import { SEGMENTS, segmentTest, topCities, type Segment } from "./model/peopleUtil";
import type { PeoplePayload } from "./model/types";
import styles from "./Network.module.css";

const WIDE = "(min-width: 1240px)";
const NOT_IN_RECORDS = "This person is not in your network records.";

export default function NetworkPage() {
  const q = usePeople();
  return (
    <>
      <PageHeader title="Network" subtitle="Relationships — who you know, how warm it is, and what to do next." />
      <IdentityReview />
      <Async q={q} label="Loading people…">
        {(d) => <NetworkWorkspace data={d} />}
      </Async>
    </>
  );
}

type FormState = { id: string | null } | null;
/** the everyday segments stay visible; the rest (and the cities) sit under "More filters" */
const ATTENTION_SEGS = ["all", "due", "fp", "watch"];

function NetworkWorkspace({ data }: { data: PeoplePayload }) {
  const [params, setParams] = useSearchParams();
  const wide = useMedia(WIDE);
  const [search, setSearch] = useState("");
  const qs = useDebounced(search, 150).toLowerCase();
  const [seg, setSeg] = useState("all");
  const [graph, setGraph] = useState(false);
  const P = useMemo(() => data.people ?? [], [data.people]);
  // ?edit=1 opens the edit drawer of a person on record (an unknown id never turns into an "Add person" form)
  const [form, setForm] = useState<FormState>(() => {
    const id = params.get("person");
    return params.get("edit") && id && P.some((p) => p.id === id) ? { id } : null;
  });
  useEffect(() => {
    if (params.has("edit")) {
      const next = new URLSearchParams(params);
      next.delete("edit");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  const pipeline = usePipelineSlice();

  const list = useMemo(() => {
    const test = segmentTest(seg);
    return P.filter((p) => (!qs || JSON.stringify(p).toLowerCase().includes(qs)) && test(p));
  }, [P, qs, seg]);
  const cities = useMemo(() => topCities(P), [P]);

  const paramId = params.get("person");
  const selId = paramId ?? (wide ? (list[0]?.id ?? null) : null);
  const sel = selId ? (P.find((p) => p.id === selId) ?? null) : null;

  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("person", id);
    else next.delete("person");
    setParams(next, { replace: true });
  };
  const openForm = (id: string | null) => setForm({ id });
  const formPerson = form?.id ? (P.find((p) => p.id === form.id) ?? null) : null;

  const due = P.filter((p) => p.due).length;
  const chains = P.filter((p) => p.introduced_by).length;
  const segChip = (s: Segment) => (
    <Chip key={s.id} on={seg === s.id} onClick={() => setSeg(s.id)}>
      {s.label} <span className={cx(styles.segN, s.red && styles.red)}>{P.filter(s.test).length}</span>
    </Chip>
  );

  return (
    <>
      <Toolbar>
        <span className="muted small" data-testid="people-counts">
          {P.length} relationships · {due} due · {chains} from chains
        </span>
        <span className="grow" />
        <input className={styles.search} aria-label="Search people" placeholder="Search people…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <Button aria-pressed={graph} onClick={() => setGraph((g) => !g)}>
          {graph ? "List" : "Graph"}
        </Button>
        <Button onClick={() => openForm(null)}>+ Person</Button>
      </Toolbar>

      <div className={cx(styles.ws, !wide && styles.wsNarrow)}>
        <div className={styles.left}>
          <div className={styles.segs} role="group" aria-label="Segments">
            <GroupedFilters
              flush
              testId="people-filters"
              attention={SEGMENTS.filter((s) => ATTENTION_SEGS.includes(s.id)).map(segChip)}
              activeMore={ATTENTION_SEGS.includes(seg) ? undefined : seg.startsWith("c:") ? seg.slice(2) : SEGMENTS.find((s) => s.id === seg)?.label}
              more={
                <>
                  {SEGMENTS.filter((s) => !ATTENTION_SEGS.includes(s.id)).map(segChip)}
                  {cities.map(([c, n]) => (
                    <Chip key={c} on={seg === `c:${c}`} onClick={() => setSeg(`c:${c}`)}>
                      {c} <span className={styles.segN}>{n}</span>
                    </Chip>
                  ))}
                </>
              }
            />
          </div>
          {graph ? (
            <TalentGraph onOpen={(id) => openForm(id)} />
          ) : (
            <ul className={styles.list} aria-label="People" data-has-selection={sel ? "" : undefined}>
              {list.map((p) => (
                <PersonRow key={p.id} p={p} data={data} selected={sel?.id === p.id} onSelect={() => select(p.id)} />
              ))}
              {!list.length && <li className={styles.noMatch}>No matches.</li>}
            </ul>
          )}
        </div>

        {wide && (
          <>
            <div className={styles.center}>{sel ? <PersonProfile p={sel} pipeline={pipeline.data} /> : <EmptyState>Select a person.</EmptyState>}</div>
            {sel && <PersonRail key={sel.id} p={sel} data={data} onEdit={() => openForm(sel.id)} />}
          </>
        )}
      </div>

      {!wide && (
        <Drawer open={!!paramId && !form} onClose={() => select(null)} title={sel?.name ?? "Person"} width={860}>
          {sel ? (
            <div className={styles.drawerGrid}>
              <PersonProfile p={sel} pipeline={pipeline.data} />
              <PersonRail key={sel.id} p={sel} data={data} onEdit={() => openForm(sel.id)} />
            </div>
          ) : (
            <EmptyState>{NOT_IN_RECORDS}</EmptyState>
          )}
        </Drawer>
      )}
      {wide && paramId && !sel && <EmptyState>{NOT_IN_RECORDS}</EmptyState>}

      <Drawer open={!!form} onClose={() => setForm(null)} title={formPerson ? formPerson.name : "Add person"} width={760}>
        {form && (
          <PersonForm
            key={form.id ?? "new"}
            p={formPerson}
            data={data}
            onDone={(id) => {
              setForm(null);
              if (id) select(id);
            }}
          />
        )}
      </Drawer>
    </>
  );
}
