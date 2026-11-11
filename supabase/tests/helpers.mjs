import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { PGlite } from "@electric-sql/pglite";

const here = dirname(fileURLToPath(import.meta.url));
export const MIGRATIONS = join(here, "..", "migrations");
export const FIXTURES = join(here, "fixtures");

/** A fresh database with Supabase's API roles and every migration applied in order. */
export async function freshDb() {
  const db = new PGlite();
  await db.exec("create role anon nologin; create role authenticated nologin;");
  for (const file of readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort()) {
    await db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
  }
  return db;
}

/** Resolves if the statement fails with a message matching `pattern`; throws if it succeeds. */
export async function rejects(promise, pattern) {
  try {
    await promise;
  } catch (err) {
    if (pattern && !pattern.test(String(err.message))) throw new Error(`wrong error: ${err.message}`);
    return err;
  }
  throw new Error("expected the statement to be refused, but it succeeded");
}
