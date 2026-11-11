/**
 * Events (v1 view `events`, review 015 — read-only): discover where founders and investors gather.
 * Deep link: /events?event=<id> opens an event (or a Scout 00 suggestion by its key); closing it replaces the history
 * entry, as before. The old `&edit=1` / `&debrief=1` opened a form; those forms arrive with the event writes port, so
 * the parameters are only removed from the URL and the event is shown. Every write keeps its old place, disabled with
 * its reason (`model/deferred.ts`).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

import { DeferredButton, DeferredLink, useDeferred } from "@/components/Deferred";
import { Async, Badge, Button, Drawer, EmptyState } from "@/components/ui";
import { usePref } from "@/lib/hooks";
import { cx } from "@/lib/format";
import { usePeople } from "@/features/network/api";
import { useEventHealth, useEvents, useWsig } from "./api";
import { dayLabel } from "./components/bits";
import { Calendar, DayStrip } from "./components/Calendar";
import { EventCard, QuietRow, SuggestionCard } from "./components/EventCard";
import { EventDetail, SuggestionDetail } from "./components/EventDetail";
import { EventHealth } from "./components/EventHealth";
import { WeekendPlan } from "./components/WeekendPlan";
import { WhereShouldIGo } from "./components/WhereShouldIGo";
import { NOT_PORTED } from "./model/deferred";
import type { EventsPayload } from "./model/types";
import { DEFAULT_FILTERS, VIEWS, addDays, counts, dayGroups, inView, itemsOf, visible, type Item, type ViewKey, type WsFilters } from "./model/workspace";
import styles from "./Events.module.css";

type Mode = "tl" | "tb" | "ld";
/** The only drawer form of 015 is the (read-only) sourcing weekend; Add / Edit / Convert / Debrief wait for 016. */
type Form = { kind: "weekend" } | null;

export default function EventsPage() {
  const q = useEvents();
  return (
    <Async q={q} label="Loading events…">
      {(ev) => <EventsWorkspace ev={ev} />}
    </Async>
  );
}

function EventsWorkspace({ ev }: { ev: EventsPayload }) {
  const [params, setParams] = useSearchParams();
  const selId = params.get("event");
  const today = ev.today || new Date().toISOString().slice(0, 10);
  const [mode, setMode] = usePref<Mode>("events.mode", "tl");
  const [view, setView] = useState<ViewKey>("upcoming");
  const [f, setF] = useState<WsFilters>(DEFAULT_FILTERS);
  const set = (p: Partial<WsFilters>) => setF((x) => ({ ...x, ...p }));
  const [month, setMonth] = useState(today.slice(0, 7));
  const [moreOpen, setMoreOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [all, setAll] = useState(false);
  const [healthOpen, setHealthOpen] = useState(false);
  const [wsigDays, setWsigDays] = useState("14");
  const menuRef = useRef<HTMLDivElement>(null);
  const [form, setForm] = useState<Form>(null);
  // Deep links from the Map panel (/events?event=<id>&edit=1 or &debrief=1) opened a form; in 015 they show the event.
  useEffect(() => {
    if (params.has("edit") || params.has("debrief")) {
      const next = new URLSearchParams(params);
      next.delete("edit");
      next.delete("debrief");
      setParams(next, { replace: true });
    }
  }, [params, setParams]);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [menuOpen]);

  const wsig = useWsig(wsigDays);
  const health = useEventHealth();
  const people = usePeople();

  const open = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("event", id);
    else next.delete("event");
    setParams(next, { replace: !id });
  };

  const events = ev.events;
  const reports = useMemo(() => ev.scout_reports ?? [], [ev.scout_reports]);
  const items = useMemo(() => itemsOf(events, reports), [events, reports]);
  const shown = useMemo(() => visible(items, view, f), [items, view, f]);
  const forCal = useMemo(() => visible(items, view, f, "date"), [items, view, f]);
  const opts = (k: "area" | "theme" | "type") => counts(visible(items, view, f, k), k);
  const viewCount = (v: ViewKey) => items.filter((it) => !(it.kind === "event" && (it.e.past || it.e.status === "attended")) && inView(it, v, f)).length;
  const cutoff = all || f.date || f.days || view !== "upcoming" ? "9999-12-31" : addDays(today, 13);
  const { groups, rest } = useMemo(() => dayGroups(shown, cutoff), [shown, cutoff]);
  const upcoming = events.filter((e) => !e.past);
  const planned = upcoming.filter((e) => e.status === "planned").length;
  const suggestions = reports.filter((r) => !r.tracked_event_id).length;
  const hp = health.data;
  const sc = ev.source_count ?? {};

  const selectedEvent = selId ? events.find((e) => e.id === selId) ?? null : null;
  const selectedReport = selId && !selectedEvent ? reports.find((r) => r.key === selId) ?? null : null;
  const formTitle = "Sourcing weekend";

  const pills: Array<[string, () => void]> = [];
  if (f.date) pills.push([new Date(`${f.date}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }), () => set({ date: "" })]);
  if (f.days) pills.push([`Next ${f.days} days`, () => set({ days: "" })]);
  if (f.area) pills.push([f.area, () => set({ area: "" })]);
  if (f.theme) pills.push([f.theme, () => set({ theme: "" })]);
  if (f.type) pills.push([ev.types[f.type] || f.type, () => set({ type: "" })]);
  if (f.founders) pills.push([f.founders === "high" ? "Founders: high" : "Founders: medium or high", () => set({ founders: "" })]);
  if (f.investors) pills.push(["Investor-relevant", () => set({ investors: "" })]);
  if (f.confidence) pills.push(["Structured sources only", () => set({ confidence: "" })]);
  if (f.general) pills.push(["Including general / rejected", () => set({ general: false })]);
  const moreCount = [f.founders, f.investors, f.confidence, f.general].filter(Boolean).length;
  const calProps = {
    items: forCal,
    today,
    date: f.date,
    month,
    past: f.past,
    onDate: (d: string) => {
      set({ date: d });
      if (d) setMonth(d.slice(0, 7));
    },
    onMonth: setMonth,
    onPast: (p: boolean) => set({ past: p, date: "" }),
  };

  const card = (it: Item) =>
    it.kind === "suggestion" ? (
      <SuggestionCard key={it.id} r={it.r} selected={selId === it.id} onOpen={open} />
    ) : (
      <EventCard key={it.id} e={it.e} types={ev.types} selected={selId === it.id} onOpen={open} />
    );

  const menuItem = (label: string, run: () => void) => (
    <button
      type="button"
      role="menuitem"
      onClick={() => {
        setMenuOpen(false);
        run();
      }}
    >
      {label}
    </button>
  );

  return (
    <div className={styles.ev}>
      <header className={styles.hero}>
        <div className={styles.heroTop}>
          <div>
            <h1 className={styles.heroTitle}>Events</h1>
            <p className={styles.heroSub}>Discover where founders and investors gather.</p>
            <p className={styles.heroFacts} data-testid="event-counts">
              <b>{upcoming.length}</b> upcoming · <b>{planned}</b> planned · <b>{suggestions}</b> Scout 00 suggestion{suggestions === 1 ? "" : "s"} not on Events yet
              {hp?.scan_time ? ` · last scan ${new Date(hp.scan_time.replace(" ", "T")).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : ""}
            </p>
          </div>
          <span className="grow" />
          <div className={styles.heroActs}>
            <DeferredLink className={styles.heroBtn} reason={NOT_PORTED.add}>
              + Event
            </DeferredLink>
            <div className={styles.menu} ref={menuRef}>
              <button type="button" className={styles.heroBtn} aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
                More ▾
              </button>
              {menuOpen && (
                <div className={styles.menuList} role="menu" aria-label="More event actions">
                  <DeferredMenuItem reason={NOT_PORTED.scan}>Scan sources</DeferredMenuItem>
                  {menuItem("Weekend plan", () => setForm({ kind: "weekend" }))}
                  <hr />
                  {menuItem(`Leads${ev.leads.length ? ` (${ev.leads.length})` : ""}`, () => setMode("ld"))}
                  {menuItem("Table view", () => setMode("tb"))}
                  {menuItem("Source health & scanner log", () => setHealthOpen(true))}
                </div>
              )}
            </div>
          </div>
        </div>
        {mode === "tl" && (
          <div className={styles.tabs} role="tablist" aria-label="Events view">
            {VIEWS.map(([k, l]) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={view === k}
                className={cx(styles.tab, view === k && styles.tabOn)}
                onClick={() => {
                  setView(k);
                  set({ date: "" });
                }}
              >
                {l}
                <span className={styles.tabN}>{viewCount(k)}</span>
              </button>
            ))}
          </div>
        )}
      </header>

      {mode !== "tl" && (
        <div className={styles.modeBar}>
          <button type="button" className={styles.linkBtn} onClick={() => setMode("tl")}>
            ← Back to events
          </button>
          <span className={styles.modeTitle}>{mode === "ld" ? "Event leads" : "All events — table"}</span>
        </div>
      )}

      {mode === "ld" && (
        <div className={styles.plain} data-testid="leads">
          <h3 className={styles.groupTitle}>Event leads — convert the real ones, dismiss the rest</h3>
          {ev.leads.length ? (
            ev.leads.slice(0, 40).map((l) => (
              <div key={l.id} className={styles.leadRow}>
                <div className={styles.leadDate}>
                  <b>{l.date ? l.date.slice(5) : "—"}</b>
                  <div className="muted small">{l.city || ""}</div>
                </div>
                <div className="grow">
                  <div className={styles.leadTitle}>{l.title}</div>
                  <div className="muted small">
                    <Badge tone={l.confidence === "VERIFIED" ? "green" : l.confidence === "LIKELY" ? "amber" : "red"}>{l.confidence || "NEEDS REVIEW"}</Badge> {l.source} · detected {l.detected_on} ·{" "}
                    <a href={l.url} target="_blank" rel="noreferrer">
                      source ↗
                    </a>
                  </div>
                  {l.note && <div className="small">{l.note}</div>}
                </div>
                <div className={styles.leadActs}>
                  <DeferredButton size="sm" variant="success" reason={NOT_PORTED.lead}>
                    Convert
                  </DeferredButton>
                  <DeferredButton size="sm" variant="danger" reason={NOT_PORTED.lead}>
                    Dismiss
                  </DeferredButton>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>No open leads. Scan to check the watched pages.</EmptyState>
          )}
        </div>
      )}

      {mode === "tb" && (
        <div className={cx(styles.plain, styles.tableWrap)}>
          <table className={styles.evTable} data-testid="events-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Event</th>
                <th>Place</th>
                <th>Score</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.id} className={cx(e.past && e.status !== "attended" && styles.faded)}>
                  <td className="small">
                    <b>{(e.start || "").slice(0, 10)}</b>
                  </td>
                  <td>
                    <button type="button" className={styles.evName} onClick={() => open(e.id)}>
                      {e.name}
                    </button>
                    <div className="muted small">
                      {ev.types[e.type ?? ""] || ""}
                      {e.organizer && e.organizer !== "UNKNOWN" ? ` · ${e.organizer}` : ""}
                    </div>
                  </td>
                  <td className="small">{e.place?.label || e.city || ""}</td>
                  <td>
                    <Badge tone={(e.sc.total ?? 0) >= 75 ? "green" : "blue"}>{e.sc.total ?? "—"}</Badge>
                  </td>
                  <td>
                    <StatusSelect name={e.name} status={e.status || "new"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!events.length && <EmptyState>No events yet. Scan sources, convert leads, or add the next event you already know about.</EmptyState>}
        </div>
      )}

      {mode === "tl" && (
        <>
          <div className={styles.fbar} role="group" aria-label="Filter events">
            <select className={cx(styles.fsel, f.days && styles.fselOn)} aria-label="Date" value={f.days} onChange={(e) => set({ days: e.target.value as WsFilters["days"] })}>
              <option value="">Any date</option>
              <option value="7">Next 7 days</option>
              <option value="30">Next 30 days</option>
              <option value="90">Next 90 days</option>
            </select>
            <select className={cx(styles.fsel, f.area && styles.fselOn)} aria-label="City or region" value={f.area} onChange={(e) => set({ area: e.target.value })}>
              <option value="">All cities &amp; regions</option>
              {f.area && !opts("area").some(([a]) => a === f.area) && <option value={f.area}>{f.area} (0)</option>}
              {opts("area").map(([a, n]) => (
                <option key={a} value={a}>
                  {a} ({n})
                </option>
              ))}
            </select>
            <select className={cx(styles.fsel, f.theme && styles.fselOn)} aria-label="Theme" value={f.theme} onChange={(e) => set({ theme: e.target.value })}>
              <option value="">All themes</option>
              {opts("theme").map(([t, n]) => (
                <option key={t} value={t}>
                  {t} ({n})
                </option>
              ))}
            </select>
            <select className={cx(styles.fsel, f.type && styles.fselOn)} aria-label="Event type" value={f.type} onChange={(e) => set({ type: e.target.value })}>
              <option value="">All types</option>
              {opts("type").map(([t, n]) => (
                <option key={t} value={t}>
                  {ev.types[t] || t} ({n})
                </option>
              ))}
            </select>
            <button type="button" className={cx(styles.moreBtn, moreCount > 0 && styles.fselOn)} aria-expanded={moreOpen} onClick={() => setMoreOpen(!moreOpen)}>
              More filters{moreCount ? ` · ${moreCount}` : ""}
            </button>
          </div>
          {moreOpen && (
            <div className={styles.moreBox} role="group" aria-label="More filters">
              <select className={cx(styles.fsel, f.founders && styles.fselOn)} aria-label="Founder relevance" value={f.founders} onChange={(e) => set({ founders: e.target.value as WsFilters["founders"] })}>
                <option value="">Founder relevance: any</option>
                <option value="medium">Founders: medium or high</option>
                <option value="high">Founders: high</option>
              </select>
              <select className={cx(styles.fsel, f.investors && styles.fselOn)} aria-label="Investor relevance" value={f.investors} onChange={(e) => set({ investors: e.target.value as WsFilters["investors"] })}>
                <option value="">Investor relevance: any</option>
                <option value="yes">Investor-relevant (demo day, VC, networking evidence)</option>
              </select>
              <select className={cx(styles.fsel, f.confidence && styles.fselOn)} aria-label="Source confidence" value={f.confidence} onChange={(e) => set({ confidence: e.target.value as WsFilters["confidence"] })}>
                <option value="">Source: any</option>
                <option value="structured">Structured source data only</option>
              </select>
              <label className={styles.check}>
                <input type="checkbox" checked={f.general} onChange={(e) => set({ general: e.target.checked })} /> Include general / rejected events
              </label>
            </div>
          )}
          {pills.length > 0 && (
            <div className={styles.activePills} aria-label="Active filters">
              {pills.map(([l, clear]) => (
                <span key={l} className={styles.pillOn}>
                  {l}
                  <button type="button" aria-label={`Remove ${l}`} onClick={clear}>
                    ×
                  </button>
                </span>
              ))}
              <button type="button" className={styles.linkBtn} onClick={() => setF({ ...DEFAULT_FILTERS, past: f.past })}>
                Clear all
              </button>
            </div>
          )}

          <div className={styles.mobileCal}>
            <DayStrip {...calProps} />
          </div>

          <div className={styles.cols}>
            <section className={styles.timeline} aria-label="Events" data-testid="timeline">
              {view === "priority" && (
                <div className={styles.wsigWrap}>
                  <WhereShouldIGo days={wsigDays} onDays={setWsigDays} ranked={wsig.data?.ranked} loading={wsig.isLoading} events={events} onOpen={open} />
                </div>
              )}
              {groups.length === 0 ? (
                <NoMatch
                  view={view}
                  f={f}
                  items={items}
                  onClear={() => setF({ ...DEFAULT_FILTERS, past: f.past })}
                  onAll={() => {
                    setView("upcoming");
                    set({ date: "" });
                  }}
                />
              ) : (
                groups.map((g) => {
                  const [main, wd] = dayLabel(g.day, today);
                  return (
                    <div key={g.day || "undated"} className={cx(styles.day, g.day === today && styles.dayToday)} data-day={g.day}>
                      <h3 className={styles.dayHead}>
                        <b>{main}</b>
                        <span>{wd}</span>
                      </h3>
                      {g.rich.map(card)}
                      {g.quiet.length > 0 && (
                        <div className={styles.quiet} aria-label="Not yet reviewed">
                          <div className={styles.quietCap}>
                            {g.rich.length ? "Also on this day — " : ""}
                            {g.quiet.length} {g.quiet.length === 1 ? "listing" : "listings"} not yet reviewed · the source gives a title only
                          </div>
                          {g.quiet.map((it) => it.kind === "event" && <QuietRow key={it.id} e={it.e} selected={selId === it.id} onOpen={open} />)}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
              {rest > 0 && (
                <button type="button" className={styles.showMore} onClick={() => setAll(true)}>
                  Show {rest} later event{rest === 1 ? "" : "s"}
                </button>
              )}
            </section>
            <aside className={styles.side} aria-label="Calendar">
              <Calendar {...calProps} />
              <p className={styles.sideNote}>
                Times in Europe/Berlin · travel times from Karlsruhe.
                {hp?.totals?.attempted != null && (
                  <>
                    <br />
                    {hp.totals.attempted} sources · {hp.totals.productive ?? 0} returning events · {hp.totals.failed ?? 0} failing —{" "}
                    <button type="button" className={styles.linkBtn} onClick={() => setHealthOpen(true)}>
                      source health
                    </button>
                  </>
                )}
              </p>
            </aside>
          </div>
        </>
      )}

      <Drawer open={!!selectedEvent && !form} onClose={() => open(null)} title={selectedEvent?.name} width={600}>
        {selectedEvent && (
          <EventDetail
            e={selectedEvent}
            ev={ev}
            people={people.data?.people ?? []}
            wsig={wsig.data?.ranked ?? []}
            homeCity="Karlsruhe"
            onWeekend={() => setForm({ kind: "weekend" })}
          />
        )}
      </Drawer>
      <Drawer open={!!selectedReport && !form} onClose={() => open(null)} title={selectedReport?.name} width={600}>
        {selectedReport && <SuggestionDetail r={selectedReport} />}
      </Drawer>
      {selId && !selectedEvent && !selectedReport && !form && (
        <Drawer open onClose={() => open(null)} title="Event not found">
          <EmptyState>This event is not in the current event list (it may have been merged or removed).</EmptyState>
        </Drawer>
      )}

      <Drawer open={healthOpen} onClose={() => setHealthOpen(false)} title="Source health & scanner log" width={1040}>
        <EventHealth h={hp} loading={health.isLoading} />
        <div className={styles.scanLog}>
          <div className={styles.scanBox}>
            <div className={styles.hd}>Scanner</div>
            <div className="muted small">
              Structured: Devpost API · Luma ×{sc.luma ?? 0} · JSON-LD pages ×{sc.jsonld ?? 0} · ICS {ev.ics_count ?? sc.ics ?? 0} configured
              <br />
              Watchers: {(ev.pages ?? []).length} pages · Manual list below
            </div>
            <DeferredButton size="sm" reason={NOT_PORTED.scan}>
              Scan sources
            </DeferredButton>
          </div>
          <div className={styles.scanBox}>
            <div className={styles.hd}>Manual sources — weekly 10-min routine</div>
            {(ev.manual_sources ?? []).map((m) => (
              <div key={m.name} className={styles.manual}>
                <b>{m.name}</b>{" "}
                <a href={m.url} target="_blank" rel="noreferrer" className="small">
                  open ↗
                </a>
                <div className="muted small">{m.how}</div>
              </div>
            ))}
          </div>
        </div>
      </Drawer>

      <Drawer open={!!form} onClose={() => setForm(null)} title={formTitle} width={760}>
        {form?.kind === "weekend" && <WeekendPlan weekendWindow={ev.weekend_window} />}
      </Drawer>
    </div>
  );
}

/** Says why this view is empty and offers the existing ways out — no diagnostics dashboard. */
function NoMatch({ view, f, items, onClear, onAll }: { view: ViewKey; f: WsFilters; items: Item[]; onClear: () => void; onAll: () => void }) {
  const viewName = VIEWS.find((v) => v[0] === view)?.[1] ?? "";
  const why = [
    view !== "upcoming" && `in ${viewName}`,
    f.date && `on ${new Date(`${f.date}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}`,
    f.area && `in ${f.area}`,
    f.theme && `about ${f.theme}`,
    f.days && `in the next ${f.days} days`,
    f.past && "attended",
  ]
    .filter(Boolean)
    .join(" ");
  const next = f.date ? visible(items, view, { ...f, date: "" }).find((it) => it.date > f.date) : undefined;
  const filtered = !!(f.date || f.days || f.area || f.theme || f.type || f.founders || f.investors || f.confidence || f.general);
  return (
    <div className={styles.empty} data-testid="events-empty">
      <h3 className={styles.emptyTitle}>No events {why || "yet"}</h3>
      <p className={styles.emptyText}>
        {view === "planned" && !filtered
          ? "You have not planned an event yet — open one and choose GO."
          : next
            ? `Next in this selection: ${next.name} on ${new Date(`${next.date}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}.`
            : filtered
              ? "Nothing matches the current filters."
              : "The scanner has not stored a matching future event."}
      </p>
      <div className={styles.emptyActs}>
        {filtered && <Button onClick={onClear}>Clear filters</Button>}
        {view !== "upcoming" && <Button onClick={onAll}>Show all upcoming</Button>}
        <DeferredButton variant="ghost" reason={NOT_PORTED.scan}>
          Scan sources
        </DeferredButton>
        <DeferredButton variant="ghost" reason={NOT_PORTED.add}>
          + Add an event you know
        </DeferredButton>
      </div>
    </div>
  );
}

/** A "More" menu item whose action is not ported yet: still a named menu item, inert, with its reason. */
function DeferredMenuItem({ reason, children }: { reason: string; children: ReactNode }) {
  const d = useDeferred(reason);
  return (
    <>
      <button type="button" role="menuitem" {...d.props}>
        {children}
      </button>
      {d.note}
    </>
  );
}

/** The table's status select (event_save, review 016): it shows the stored status, disabled with the reason. */
function StatusSelect({ name, status }: { name: string; status: string }) {
  const d = useDeferred(NOT_PORTED.status);
  return (
    <>
      <select
        aria-label={`Status of ${name}`}
        value={status}
        disabled
        title={d.props.title}
        aria-describedby={d.props["aria-describedby"]}
        data-deferred=""
        onChange={() => undefined}
      >
        {["new", "planned", "attended", "skipped"].map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      {d.note}
    </>
  );
}
