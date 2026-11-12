/**
 * Ecosystems (v1 view `eco`, review 022): coverage intelligence — where Project Zero can and cannot see, with explicit,
 * one-at-a-time candidate adoption — then the curated + detected city registry and one city's page (default the home
 * city; `?city=` deep links, as before). Reads `GET ecosystems/coverage`, `GET ecosystems/registry` and
 * `GET ecosystems/eco?city=`; writes `POST ecosystems/coverage/adopt` (see ./api).
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Async, Callout, PageHeader } from "@/components/ui";
import { useCityRegistry } from "./api";
import { CityRegistry } from "./components/CityRegistry";
import { CityView } from "./components/CityView";
import { CoveragePanel } from "./components/CoveragePanel";
import { HOME_CITY } from "./model/registry";
import styles from "./Ecosystems.module.css";

export default function EcosystemsPage() {
  const [params, setParams] = useSearchParams();
  const city = params.get("city") || HOME_CITY;
  const [q, setQ] = useState("");
  const reg = useCityRegistry();

  const pick = (name: string) => {
    const next = new URLSearchParams(params);
    next.set("city", name);
    setParams(next, { replace: true });
  };

  return (
    <>
      <PageHeader
        title="Ecosystems"
        subtitle="One page per city: startups in pipeline, upcoming events, your people, universities & hubs. Presence beats research — these pages tell you what a trip there would touch."
      />
      <Callout tone="amber">
        This page is a <b>curated city registry plus detected coverage</b> — it does not limit where Project Zero sources from. The startup registry, event
        sources and your people data reach any geography their sources return.
      </Callout>
      <CoveragePanel />
      <input className={styles.search} aria-label="Search cities" placeholder="Search cities…" value={q} onChange={(e) => setQ(e.target.value)} />
      <Async q={reg} label="Loading cities…">
        {(r) => <CityRegistry r={r} q={q} city={city} onPick={pick} />}
      </Async>
      <CityView city={city} reg={reg.data} />
    </>
  );
}
