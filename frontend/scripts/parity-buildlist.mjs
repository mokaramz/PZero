/**
 * Review 009 #2 — the full-pool Attention queue and every filter on the REAL snapshot: the new `buildList` on the NEW
 * payload vs the OLD frontend's `buildList` on the OLD payload. Real data stays in a scratch folder.
 *
 *   python -m projectzero.ops.parity_inbox real --dump <scratch dir>        (backend/)
 *   node scripts/parity-buildlist.mjs <scratch dir> <old repo>/frontend      (frontend/)
 *
 * Both modules are bundled with rolldown into a temp folder and run with the clock fixed (recScore reads Date.now()).
 * Population: the legacy survivors in old input order; the record merged into another survivor, and that survivor,
 * are reported separately; the additional (non-inbox) candidates must sit after them in a stable order.
 */
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

import { build } from "rolldown";

const [dir, oldFrontend] = process.argv.slice(2);
if (!dir || !oldFrontend) {
  console.error("usage: node scripts/parity-buildlist.mjs <dump dir> <old frontend dir>");
  process.exit(2);
}
const here = resolve(import.meta.dirname, "..");
const tmp = mkdtempSync(join(tmpdir(), "pz-buildlist-"));
const bundle = async (input, name) => {
  await build({ input, output: { file: join(tmp, name), format: "esm" }, resolve: { alias: { "@": join(here, "src") } }, logLevel: "silent" });
  return import(pathToFileURL(join(tmp, name)).href);
};
const NOW = Date.parse("2026-11-11T12:00:00Z");
Date.now = () => NOW;

try {
  const oldLogic = await bundle(join(oldFrontend, "src/features/inbox/logic.ts"), "old.mjs");
  const newList = await bundle(join(here, "src/features/deal-flow/model/list.ts"), "new.mjs");
  const newTriage = await bundle(join(here, "src/features/deal-flow/model/triage.ts"), "triage.mjs");
  const read = (f) => JSON.parse(readFileSync(join(dir, f), "utf-8"));
  const oldPayload = read("old.json");
  const newPayload = read("new.json");
  const aliases = read("aliases.json");
  const merged = new Set(Object.entries(aliases).filter(([a, [c]]) => a !== c).flatMap(([a, [c]]) => [a, c]));
  const legacy = new Set(oldPayload.candidates.map((c) => c.id));
  const oldPool = oldPayload.candidates.filter((c) => !merged.has(c.id));
  const newPool = newPayload.candidates.filter((c) => legacy.has(c.id) && !merged.has(c.id));
  const extra = newPayload.candidates.filter((c) => !legacy.has(c.id) && !merged.has(c.id));
  const skip = newTriage.isNonStartup(read("triage.json").proposals);
  const problems = [];
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  if (!same(newPool.map((c) => c.id), oldPool.map((c) => c.id))) problems.push("population or order differs");

  const VIEWS = [["eu", "both"], ["na", "both"], ["na", "us"], ["na", "ca"], ["unk", "both"], ["all", "both"]];
  const FILTERS = ["top", "pre", "thisrun", "new", "research", "watch", "kept", "rejected", "baseline"];
  const themes = ["", ...Object.keys(newPayload.themes)];
  let compared = 0;
  let cutoffs = 0;
  let tiesAtCutoff = 0;
  for (const [ws, naf] of VIEWS)
    for (const filter of FILTERS)
      for (const im of [false, true])
        for (const theme of themes) {
          const opts = { ws, naf, filter, im, theme, lastRun: newPayload.last_run, skip };
          const a = oldLogic.buildList(oldPool, opts);
          const b = newList.buildList(newPool, opts);
          const key = JSON.stringify({ ws, naf, filter, im, theme });
          if (!same(b.list.map((c) => c.id), a.list.map((c) => c.id))) problems.push(`order ${key}`);
          if (b.hidden !== a.hidden) problems.push(`hidden ${key}`);
          if (!same(b.counts, a.counts)) problems.push(`counts ${key}`);
          compared++;
          if (filter === "top" && a.hidden > 0) {
            cutoffs++;
            const full = oldPool.filter((c) => oldLogic.geoOk(c, ws, naf) && (!theme || (c.themes || []).includes(theme)) && c.decision === "new" && oldLogic.gateOk(c) && !skip(c));
            full.sort((x, y) => oldLogic.lensRank(x, y, im) || (y.priority || 0) - (x.priority || 0));
            const at = full[14];
            const next = full[15];
            if (at && next && oldLogic.lensRank(at, next, im) === 0 && (at.priority || 0) === (next.priority || 0)) tiesAtCutoff++;
          }
        }
  // the additional candidates: after every legacy survivor, in a stable order (first seen, then id) — checked by the
  // backend parity; here only that the full new pool keeps legacy first
  const ids = newPayload.candidates.map((c) => c.id);
  const firstExtra = Math.min(...extra.map((c) => ids.indexOf(c.id)));
  const lastLegacy = Math.max(...newPool.map((c) => ids.indexOf(c.id)));
  if (extra.length && firstExtra < lastLegacy) problems.push("an additional candidate sits among the legacy survivors");
  console.log(JSON.stringify({ population: newPool.length, merged_excluded: merged.size, additional: extra.length, compared, top_queues_with_cutoff: cutoffs, equal_score_ties_across_cutoff: tiesAtCutoff, problems: problems.length }, null, 2));
  for (const p of problems.slice(0, 20)) console.log("  PROBLEM", p);
  process.exitCode = problems.length ? 1 : 0;
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
