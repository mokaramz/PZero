/**
 * Review 015 — the Events workspace on a REAL `/api/events` payload: every exported function of the NEW
 * `features/events/model/workspace.ts` (and the pure `components/bits.tsx` date / time labels) against the OLD
 * frontend's `features/events/workspace.ts` / `bits.tsx`, on the same payload, across every view and a set of filter
 * combinations. Real data stays where it is: only aggregates and difference paths (positions and filter-value
 * indexes, never names, ids, places or themes) are printed, and nothing is written into the repo.
 *
 *   curl -s <server>/api/events > <scratch>/events.json                         (or any saved payload)
 *   curl -s "<server>/api/events/wsig?days=30" > <scratch>/wsig.json            (optional)
 *   node scripts/parity-events-workspace.mjs <scratch>/events.json <old repo>/frontend [--wsig <scratch>/wsig.json]
 *
 * Both modules are bundled with rolldown into a temp folder and run with the clock fixed (Date.now and `new Date()` at
 * noon UTC of the payload's `today`). Exit 1 on any difference, 2 on bad usage.
 */
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { build } from "rolldown";

const args = process.argv.slice(2);
const wsigAt = args.indexOf("--wsig");
const wsigFile = wsigAt >= 0 ? args[wsigAt + 1] : null;
const [payloadFile, oldFrontend] = wsigAt >= 0 ? args.filter((_, i) => i !== wsigAt && i !== wsigAt + 1) : args;
if (!payloadFile || !oldFrontend || (wsigAt >= 0 && !wsigFile)) {
  console.error("usage: node scripts/parity-events-workspace.mjs <events payload.json> <old frontend dir> [--wsig <wsig payload.json>]");
  process.exit(2);
}

const payload = JSON.parse(readFileSync(payloadFile, "utf-8"));
const wsigRaw = wsigFile ? JSON.parse(readFileSync(wsigFile, "utf-8")) : null;
const ranked = wsigRaw ? (Array.isArray(wsigRaw) ? wsigRaw : (wsigRaw.ranked ?? [])) : [];
const events = payload.events ?? [];
const reports = payload.scout_reports ?? [];
const today = payload.today || "2026-11-11";

// the clock, fixed before either module runs
const NOW = Date.parse(`${today}T12:00:00Z`);
const RealDate = Date;
class FixedDate extends RealDate {
  constructor(...a) {
    super(...(a.length ? a : [NOW]));
  }
  static now() {
    return NOW;
  }
}
globalThis.Date = FixedDate;

const here = resolve(import.meta.dirname, "..");
const tmp = mkdtempSync(join(tmpdir(), "pz-events-ws-"));
const bundle = async (input, name) => {
  await build({ input, output: { file: join(tmp, name), format: "esm" }, resolve: { alias: { "@": join(here, "src") } }, logLevel: "silent" });
  return import(pathToFileURL(join(tmp, name)).href);
};

try {
  const O = await bundle(join(oldFrontend, "src/features/events/workspace.ts"), "old-ws.mjs");
  const N = await bundle(join(here, "src/features/events/model/workspace.ts"), "new-ws.mjs");
  const OB = await bundle(join(oldFrontend, "src/features/events/bits.tsx"), "old-bits.mjs");
  const NB = await bundle(join(here, "src/features/events/components/bits.tsx"), "new-bits.mjs");

  const problems = [];
  let compared = 0;
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const check = (path, a, b) => {
    compared++;
    if (!same(a, b)) problems.push(path);
  };
  const ids = (xs) => xs.map((x) => x.id);

  // the exported surface and the constants
  check("exports", Object.keys(O).sort(), Object.keys(N).sort());
  check("exports bits", Object.keys(OB).sort(), Object.keys(NB).sort());
  for (const k of ["DEFAULT_FILTERS", "VIEWS", "STRONG_ORDER"]) check(`const ${k}`, O[k], N[k]);

  // items
  const oItems = O.itemsOf(events, reports);
  const nItems = N.itemsOf(events, reports);
  check("itemsOf", oItems, nItems);
  const items = nItems;

  // per item / per event helpers
  const VIEW_KEYS = N.VIEWS.map(([k]) => k);
  items.forEach((it, i) => {
    check(`isPriority item#${i}`, O.isPriority(oItems[i]), N.isPriority(it));
    check(`priorityWhy item#${i}`, O.priorityWhy(oItems[i]), N.priorityWhy(it));
    check(`isRich item#${i}`, O.isRich(oItems[i]), N.isRich(it));
    for (const v of VIEW_KEYS) for (const general of [false, true]) check(`inView item#${i} ${v} general=${general}`, O.inView(oItems[i], v, { general }), N.inView(it, v, { general }));
  });
  events.forEach((e, i) => {
    check(`isPriorityEvent event#${i}`, O.isPriorityEvent(e), N.isPriorityEvent(e));
    check(`investorRelevant event#${i}`, O.investorRelevant(e), N.investorRelevant(e));
  });

  // the WSIG ranked list (optional): the priority helpers on the events it ranks, and that each one resolves
  let wsigUnresolved = 0;
  ranked.forEach((w, i) => {
    const at = items.findIndex((it) => it.kind === "event" && it.id === w.id);
    if (at < 0) {
      wsigUnresolved++;
      return;
    }
    check(`wsig#${i} isPriority`, O.isPriority(oItems[at]), N.isPriority(items[at]));
    check(`wsig#${i} priorityWhy`, O.priorityWhy(oItems[at]), N.priorityWhy(items[at]));
  });

  // filter values: the real option lists (referred to by index in the output)
  const optVals = (key) => N.counts(items, key).map(([v]) => v);
  const VAL = { area: optVals("area"), theme: optVals("theme"), type: optVals("type"), date: [...new Set(items.map((it) => it.date).filter(Boolean))].sort() };
  const label = (f) =>
    Object.entries(f)
      .filter(([k, v]) => v !== N.DEFAULT_FILTERS[k])
      .map(([k, v]) => (k in VAL ? `${k}#${VAL[k].indexOf(v)}` : `${k}=${v}`))
      .join(",") || "default";

  const combos = [];
  for (const past of [false, true])
    for (const general of [false, true]) {
      for (const days of ["", "7", "30", "90"])
        for (const founders of ["", "medium", "high"])
          for (const investors of ["", "yes"]) for (const confidence of ["", "structured"]) combos.push({ ...N.DEFAULT_FILTERS, past, general, days, founders, investors, confidence });
      for (const key of ["area", "theme", "type", "date"]) for (const v of VAL[key]) combos.push({ ...N.DEFAULT_FILTERS, past, general, [key]: v });
      for (const area of VAL.area.slice(0, 5)) for (const theme of VAL.theme.slice(0, 5)) combos.push({ ...N.DEFAULT_FILTERS, past, general, area, theme, days: "90" });
    }

  const SKIPS = [null, "days", "area", "theme", "type", "date"];
  const cutoffs = ["9999-12-31", N.addDays(today, 13)];
  const marksOf = (m) => [...m.entries()];
  let nonEmpty = 0;
  for (const v of VIEW_KEYS)
    for (const f of combos) {
      const key = `view=${v} ${label(f)}`;
      for (const skip of SKIPS) {
        const a = O.visible(oItems, v, f, skip);
        const b = N.visible(items, v, f, skip);
        check(`visible ${key} skip=${skip}`, ids(a), ids(b));
        if (skip === null) {
          if (b.length) nonEmpty++;
          for (const c of cutoffs) {
            const ga = O.dayGroups(a, c);
            const gb = N.dayGroups(b, c);
            check(`dayGroups ${key} cutoff=${c === cutoffs[0] ? "none" : "today+13"}`, { rest: ga.rest, g: ga.groups.map((g) => [g.day, ids(g.rich), ids(g.quiet)]) }, { rest: gb.rest, g: gb.groups.map((g) => [g.day, ids(g.rich), ids(g.quiet)]) });
          }
        }
        if (skip === "date") check(`dayMarks ${key}`, marksOf(O.dayMarks(a)), marksOf(N.dayMarks(b)));
        if (skip === "area" || skip === "theme" || skip === "type") check(`counts ${key} ${skip}`, O.counts(a, skip), N.counts(b, skip));
      }
    }
  for (const key of ["area", "theme", "type"]) check(`counts all ${key}`, O.counts(oItems, key), N.counts(items, key));
  check("dayMarks all", marksOf(O.dayMarks(oItems)), marksOf(N.dayMarks(items)));

  // calendar helpers over every month that holds an item (and the months around them)
  const months = new Set([today.slice(0, 7), ...VAL.date.map((d) => d.slice(0, 7))]);
  for (const ym of [...months]) for (const n of [-13, -1, 0, 1, 12]) months.add(N.shiftMonth(ym, n));
  for (const ym of months) {
    check(`monthGrid ${ym}`, O.monthGrid(ym), N.monthGrid(ym));
    for (const n of [-13, -1, 1, 12]) check(`shiftMonth ${ym} ${n}`, O.shiftMonth(ym, n), N.shiftMonth(ym, n));
  }
  for (const d of [today, ...VAL.date]) for (const n of [-2, 1, 13, 400]) check(`addDays date#${VAL.date.indexOf(d)} ${n}`, O.addDays(d, n), N.addDays(d, n));

  // bits: the day headings, the card times and the travel line
  for (const d of ["", today, ...VAL.date]) check(`dayLabel date#${VAL.date.indexOf(d)}`, OB.dayLabel(d, today), NB.dayLabel(d, today));
  events.forEach((e, i) => {
    check(`timeLabel event#${i}`, OB.timeLabel(e.when?.start_time), NB.timeLabel(e.when?.start_time));
    check(`travelLine event#${i}`, OB.travelLine(e.travel_hours), NB.travelLine(e.travel_hours));
  });

  console.log(
    JSON.stringify(
      {
        events: events.length,
        scout_reports: reports.length,
        items: items.length,
        suggestions: items.filter((it) => it.kind === "suggestion").length,
        option_values: { area: VAL.area.length, theme: VAL.theme.length, type: VAL.type.length, date: VAL.date.length },
        views: VIEW_KEYS.length,
        filter_combinations: combos.length,
        non_empty_lists: nonEmpty,
        months: months.size,
        wsig_ranked: ranked.length,
        wsig_unresolved: wsigUnresolved,
        compared,
        problems: problems.length,
      },
      null,
      2,
    ),
  );
  for (const p of problems.slice(0, 20)) console.log("  PROBLEM", p);
  process.exitCode = problems.length ? 1 : 0;
} finally {
  globalThis.Date = RealDate;
  rmSync(tmp, { recursive: true, force: true });
}
