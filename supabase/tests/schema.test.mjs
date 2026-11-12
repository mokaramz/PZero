// Schema behaviour that review 001 asked to see demonstrated (findings #1, #2, #4) plus the core guarantees.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { before, describe, test } from "node:test";

import { PGlite } from "@electric-sql/pglite";

import { FIXTURES, freshDb, MIGRATIONS, rejects } from "./helpers.mjs";

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

describe("finding #1 — identifiers: weak names per company, strong ids globally", () => {
  let db;
  // Re-runnable import step for one company, as the legacy importer will do it (idempotent upserts).
  const importCompany = async (name, registry) => {
    const existing = await db.query(
      `select company_id from pz.company_identifiers
        where kind = 'registry' and namespace = 'duns' and value = $1`,
      [registry],
    );
    let id = existing.rows[0]?.company_id;
    if (!id) {
      id = (await db.query("insert into pz.companies (name) values ($1) returning id", [name])).rows[0].id;
      await db.query(
        `insert into pz.company_identifiers (company_id, kind, namespace, value) values ($1, 'registry', 'duns', $2)`,
        [id, registry],
      );
    }
    await db.query(
      `insert into pz.company_identifiers (company_id, kind, value)
       values ($1, 'normalized_name', $2) on conflict do nothing`, // the app normalises (migration 0002)
      [id, "nova robotics"],
    );
    return id;
  };

  before(async () => {
    db = await freshDb();
  });

  test("two companies with the same normalised name and different registries both keep their name", async () => {
    const a = await importCompany("Nova Robotics GmbH", "111111111");
    const b = await importCompany("Nova Robotics Ltd", "222222222");
    assert.notEqual(a, b);
    const names = await db.query(
      `select company_id from pz.company_identifiers where kind = 'normalized_name' and value = 'nova robotics'`,
    );
    assert.equal(names.rows.length, 2);
  });

  test("replaying the import changes nothing", async () => {
    const before = (await db.query("select count(*)::int n from pz.company_identifiers")).rows[0].n;
    await importCompany("Nova Robotics GmbH", "111111111");
    await importCompany("Nova Robotics Ltd", "222222222");
    const after = (await db.query("select count(*)::int n from pz.company_identifiers")).rows[0].n;
    const companies = (await db.query("select count(*)::int n from pz.companies")).rows[0].n;
    assert.equal(after, before);
    assert.equal(companies, 2);
  });

  test("a strong identifier can never belong to two companies", async () => {
    const [a, b] = (await db.query("select id from pz.companies order by name")).rows.map((r) => r.id);
    await db.query(`insert into pz.company_identifiers (company_id, kind, value) values ($1, 'domain', 'nova.ai')`, [a]);
    await rejects(
      db.query(`insert into pz.company_identifiers (company_id, kind, value) values ($1, 'domain', 'nova.ai')`, [b]),
      /company_identifiers_strong_unique/,
    );
    await rejects(
      db.query(
        `insert into pz.company_identifiers (company_id, kind, namespace, value) values ($1, 'registry', 'duns', '111111111')`,
        [b],
      ),
      /company_identifiers_strong_unique/,
    );
  });

  test("the same registry number in a different namespace is a different identifier", async () => {
    const [, b] = (await db.query("select id from pz.companies order by name")).rows.map((r) => r.id);
    await db.query(
      `insert into pz.company_identifiers (company_id, kind, namespace, value) values ($1, 'registry', 'handelsregister', '111111111')`,
      [b],
    );
  });

  test("registry and submitter keys need a namespace", async () => {
    const [a] = (await db.query("select id from pz.companies")).rows.map((r) => r.id);
    await rejects(
      db.query(`insert into pz.company_identifiers (company_id, kind, value) values ($1, 'submitter_key', 'x')`, [a]),
      /check/,
    );
  });
});

describe("finding #2 — legacy archive restores the original bytes", () => {
  let db;
  const fixture = readFileSync(join(FIXTURES, "crlf_sample.jsonl")); // BOM + CRLF line endings, odd key order

  before(async () => {
    db = await freshDb();
  });

  test("the fixture really has a BOM and CRLF endings", () => {
    assert.deepEqual([...fixture.subarray(0, 3)], [0xef, 0xbb, 0xbf]);
    assert.ok(fixture.includes(Buffer.from("\r\n")));
  });

  test("stored bytes come back identical and match the recorded SHA-256", async () => {
    await db.query(
      `insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, $5)`,
      ["news/sample.jsonl", sha256(fixture), fixture.length, fixture, JSON.stringify([{ b: 2, a: 1 }])],
    );
    const row = (await db.query(`select raw, sha256 from pz.legacy_documents where path = 'news/sample.jsonl'`)).rows[0];
    const restored = Buffer.from(row.raw);
    assert.ok(restored.equals(fixture), "restored bytes differ from the original file");
    assert.equal(sha256(restored), sha256(fixture));
    assert.equal(row.sha256, sha256(fixture));
  });

  test("a row whose bytes do not match its SHA-256 or size is refused", async () => {
    await rejects(
      db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw) values ('x.json', $1, $2, $3)`, [
        sha256(Buffer.from("other")),
        fixture.length,
        fixture,
      ]),
      /legacy_documents_sha_match/,
    );
    await rejects(
      db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw) values ('y.json', $1, $2, $3)`, [
        sha256(fixture),
        fixture.length + 1,
        fixture,
      ]),
      /legacy_documents_bytes_match/,
    );
  });

  test("archived files can never be changed or deleted", async () => {
    await rejects(db.query(`update pz.legacy_documents set parsed = null`), /append-only/);
    await rejects(db.query(`delete from pz.legacy_documents`), /append-only/);
  });
});

describe("finding #4 — every original id resolves after a merge, and on re-import", () => {
  let db;
  let companyId;
  // The importer's merge step: the Deal Flow candidate survives; the Scout Intake item becomes an alias.
  const importMerged = async () => {
    await db.query(
      `insert into pz.candidates (id, company_id, name, status, legacy_status, origins)
       values ('4225c719f2f2', $1, 'Freda', 'new', 'new', '{legacy_dealflow,legacy_scout00}')
       on conflict (id) do nothing`,
      [companyId],
    );
    await db.query(
      `insert into pz.candidate_aliases (namespace, alias_id, candidate_id, reason) values
         ('candidate', '4225c719f2f2', '4225c719f2f2', 'own_id'),
         ('scout_intake', 'si-002-freda', '4225c719f2f2', 'merge')
       on conflict (namespace, alias_id) do nothing`,
    );
  };

  before(async () => {
    db = await freshDb();
    companyId = (await db.query(`insert into pz.companies (name) values ('Freda') returning id`)).rows[0].id;
  });

  test("both old links resolve to the same candidate", async () => {
    await importMerged();
    const dealFlow = (await db.query(`select pz.resolve_candidate('candidate', '4225c719f2f2') id`)).rows[0].id;
    const intake = (await db.query(`select pz.resolve_candidate('scout_intake', 'si-002-freda') id`)).rows[0].id;
    assert.equal(dealFlow, "4225c719f2f2");
    assert.equal(intake, "4225c719f2f2");
  });

  test("re-import keeps exactly one candidate and the same aliases", async () => {
    await importMerged();
    assert.equal((await db.query("select count(*)::int n from pz.candidates")).rows[0].n, 1);
    assert.equal((await db.query("select count(*)::int n from pz.candidate_aliases")).rows[0].n, 2);
    assert.equal((await db.query(`select pz.resolve_candidate('scout_intake', 'si-002-freda') id`)).rows[0].id, "4225c719f2f2");
  });

  test("an unknown id resolves to nothing", async () => {
    assert.equal((await db.query(`select pz.resolve_candidate('native_scout', 'sig-nope') id`)).rows[0].id, null);
  });

  test("a second open candidate for the same company is refused (re-reports attach, never duplicate)", async () => {
    await rejects(
      db.query(`insert into pz.candidates (company_id, name) values ($1, 'Freda again')`, [companyId]),
      /candidates_one_open_per_company/,
    );
  });
});

describe("core guarantees", () => {
  let db;
  before(async () => {
    db = await freshDb();
  });

  test("observations and the model ledger are append-only", async () => {
    await db.exec(`
      insert into pz.candidates (id, name) values ('aaaaaaaaaaaa', 'X');
      insert into pz.observations (candidate_id, origin) values ('aaaaaaaaaaaa', 'grok');
      insert into pz.model_ledger (purpose, usd) values ('test', 0.01);
    `);
    await rejects(db.query(`update pz.observations set origin = 'manual'`), /append-only/);
    await rejects(db.query(`delete from pz.model_ledger`), /append-only/);
  });

  test("statuses outside the unified vocabulary are refused", async () => {
    await rejects(db.query(`insert into pz.candidates (name, status) values ('Y', 'NEW INTAKE')`), /candidates_status_check/);
  });

  test("row level security is on for every table and the API roles hold no grants", async () => {
    const off = await db.query(
      `select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'pz' and c.relkind = 'r' and not c.relrowsecurity`,
    );
    assert.deepEqual(off.rows, []);
    const grants = await db.query(
      `select table_name, grantee from information_schema.role_table_grants
        where table_schema = 'pz' and grantee in ('anon', 'authenticated', 'PUBLIC')`,
    );
    assert.deepEqual(grants.rows, []);
  });

  test("anon cannot even reach the schema", async () => {
    await db.exec("set role anon");
    try {
      await rejects(db.query("select * from pz.candidates"), /permission denied/);
    } finally {
      await db.exec("reset role");
    }
  });
});

describe("rev 2 #2 — pz.record_submission is an atomic insert-if-absent", () => {
  let db;
  const call = (sha) =>
    db.query(
      `select * from pz.record_submission('grok', 'grok', 'MW-1', $1, '1.0', '{"entities": []}'::jsonb, 'accepted', '{}'::jsonb)`,
      [sha],
    );

  before(async () => {
    db = await freshDb();
  });

  test("first call inserts, the replay reports the winner's id without an error", async () => {
    const sha = "a".repeat(64);
    const first = (await call(sha)).rows[0];
    const second = (await call(sha)).rows[0];
    assert.equal(first.inserted, true);
    assert.equal(second.inserted, false);
    assert.equal(second.submission_id, first.submission_id);
    assert.equal((await db.query("select count(*)::int n from pz.intake_submissions")).rows[0].n, 1);
  });

  test("overlapping calls: exactly one inserted, one duplicate, one row", async () => {
    const sha = "b".repeat(64);
    const results = await Promise.all([call(sha), call(sha)]);
    assert.deepEqual(results.map((r) => r.rows[0].inserted).sort(), [false, true]);
    const n = (await db.query("select count(*)::int n from pz.intake_submissions where sha256 = $1", [sha])).rows[0].n;
    assert.equal(n, 1);
  });

  test("API roles cannot execute it", async () => {
    await db.exec("set role anon");
    try {
      await rejects(call("c".repeat(64)), /permission denied/);
    } finally {
      await db.exec("reset role");
    }
  });
});

describe("rev 2 #1 — placeholders can never become strong identifiers", () => {
  let db;
  before(async () => {
    db = await freshDb();
  });

  test("the database refuses placeholder registry ids and domains, but not as weak aliases", async () => {
    const id = (await db.query(`insert into pz.companies (name) values ('Alpha') returning id`)).rows[0].id;
    for (const v of ["None", "null", " N/A ", "unknown", "000", "-", "?"]) {
      await rejects(
        db.query(`insert into pz.company_identifiers (company_id, kind, namespace, value) values ($1, 'registry', 'duns', $2)`, [id, v]),
        /company_identifiers_no_placeholder/,
      );
    }
    await rejects(
      db.query(`insert into pz.company_identifiers (company_id, kind, value) values ($1, 'domain', 'none')`, [id]),
      /company_identifiers_no_placeholder/,
    );
    await db.query(`insert into pz.company_identifiers (company_id, kind, value) values ($1, 'alias', 'None')`, [id]);
  });
});

describe("migration 0002 — names are normalised by the application", () => {
  test("normalized_name is a plain column and the SQL normaliser is gone", async () => {
    const db = await freshDb();
    const cols = await db.query(
      `select table_name, is_generated from information_schema.columns
        where table_schema = 'pz' and column_name = 'normalized_name' order by table_name`,
    );
    assert.deepEqual(cols.rows, [
      { table_name: "companies", is_generated: "NEVER" },
      { table_name: "people", is_generated: "NEVER" },
    ]);
    const fn = await db.query(`select count(*)::int n from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                                where n.nspname = 'pz' and p.proname = 'normalize_name'`);
    assert.equal(fn.rows[0].n, 0);
    await db.query(`insert into pz.companies (name, normalized_name) values ('Ölwerk Süd GmbH', 'ölwerk süd')`);
  });
});

describe("migration 0003 — a Conviction entry keeps its per-claim verification record", () => {
  test("verified is a JSON object, defaults to {}, and refuses anything else", async () => {
    const db = await freshDb();
    const col = await db.query(
      `select data_type, column_default from information_schema.columns
        where table_schema = 'pz' and table_name = 'conviction_entries' and column_name = 'verified'`,
    );
    assert.equal(col.rows[0].data_type, "jsonb");
    const co = (await db.query(`insert into pz.companies (name) values ('Flagged Co') returning id`)).rows[0].id;
    await db.query(
      `insert into pz.conviction_entries (company_id, slug, status, verified) values ($1, 'flagged', 'new', $2)`,
      [co, JSON.stringify({ founders: true, traction: false, funding: false })],
    );
    const row = await db.query(`select verified from pz.conviction_entries where slug = 'flagged'`);
    assert.deepEqual(row.rows[0].verified, { founders: true, traction: false, funding: false });
    const co2 = (await db.query(`insert into pz.companies (name) values ('Other Co') returning id`)).rows[0].id;
    await rejects(
      db.query(`insert into pz.conviction_entries (company_id, slug, status, verified) values ($1, 'other', 'new', '[true]')`, [co2]),
      /conviction_entries_verified_is_object/,
    );
  });

  test("it refuses to run over existing entries instead of inventing flags", async () => {
    const { PGlite } = await import("@electric-sql/pglite");
    const { readdirSync } = await import("node:fs");
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
    const third = files.find((f) => f.includes("conviction_verified_flags"));
    for (const f of files.filter((f) => f < third)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
    const co = (await db.query(`insert into pz.companies (name) values ('Early Co') returning id`)).rows[0].id;
    await db.query(`insert into pz.conviction_entries (company_id, slug, status, verified) values ($1, 'early', 'new', true)`, [co]);
    await rejects(db.exec(readFileSync(join(MIGRATIONS, third), "utf8")), /conviction_entries is not empty/);
  });
});

describe("migration 0004 — every Conviction write is an append-only event", () => {
  test("events are written, never changed, and their action is one of create / save / status", async () => {
    const db = await freshDb();
    const co = (await db.query(`insert into pz.companies (name) values ('Evented Co') returning id`)).rows[0].id;
    const entry = (
      await db.query(`insert into pz.conviction_entries (company_id, slug, status) values ($1, 'evented', 'new') returning id`, [co])
    ).rows[0].id;
    await db.query(
      `insert into pz.conviction_events (entry_id, slug, actor, action, before, after) values ($1, 'evented', 'operator', 'status', $2, $3)`,
      [entry, JSON.stringify({ status: "new" }), JSON.stringify({ status: "contacted" })],
    );
    const row = await db.query(`select before, after, detail from pz.conviction_events`);
    assert.deepEqual(row.rows[0], { before: { status: "new" }, after: { status: "contacted" }, detail: {} });
    await rejects(db.query(`update pz.conviction_events set slug = 'x'`), /append-only/);
    await rejects(db.query(`delete from pz.conviction_events`), /append-only/);
    await rejects(
      db.query(`insert into pz.conviction_events (entry_id, slug, actor, action, after) values ($1, 'evented', 'operator', 'delete', '{}')`, [entry]),
      /conviction_events_action_check/,
    );
    const rls = await db.query(`select relrowsecurity from pg_class where relname = 'conviction_events'`);
    assert.equal(rls.rows[0].relrowsecurity, true);
  });
});

describe("migration 0005 — a person's non-profile link is a weak url identifier", () => {
  test("url and alias are weak (shared by two people), a profile stays globally unique", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.people (id, name) values ('p-a', 'Ada'), ('p-b', 'Bea')`);
    for (const p of ["p-a", "p-b"]) {
      await db.query(`insert into pz.person_identifiers (person_id, kind, value) values ($1, 'url', 'https://acme.example.com')`, [p]);
      await db.query(`insert into pz.person_identifiers (person_id, kind, value) values ($1, 'alias', 'adal')`, [p]);
    }
    await db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-a', 'profile_url', 'https://github.com/ada')`);
    const rows = await db.query(`select kind, strength, count(*)::int n from pz.person_identifiers group by 1, 2 order by 1`);
    assert.deepEqual(rows.rows, [
      { kind: "alias", strength: "weak", n: 2 },
      { kind: "profile_url", strength: "strong", n: 1 },
      { kind: "url", strength: "weak", n: 2 },
    ]);
    await rejects(
      db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-b', 'profile_url', 'https://github.com/ada')`),
      /person_identifiers_strong_unique/,
    );
    await rejects(
      db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-a', 'url', 'https://acme.example.com')`),
      /person_identifiers_per_person_unique/,
    );
    await rejects(
      db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-a', 'website', 'x')`),
      /person_identifiers_kind_check/,
    );
  });

  test("it applies over existing identifiers without changing any strength", async () => {
    const { PGlite } = await import("@electric-sql/pglite");
    const { readdirSync } = await import("node:fs");
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
    const fifth = files.find((f) => f.includes("person_weak_url"));
    for (const f of files.filter((f) => f < fifth)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
    await db.query(`insert into pz.people (id, name) values ('p-a', 'Ada')`);
    await db.query(`insert into pz.person_identifiers (person_id, kind, value)
                    values ('p-a', 'orcid', 'https://orcid.org/0000-0002-1825-0097'), ('p-a', 'alias', 'adal'),
                           ('p-a', 'profile_url', 'https://acme.example.com')`);
    await rejects(
      db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-a', 'url', 'https://a.example.com')`),
      /person_identifiers_kind_check/,
    );
    await db.exec(readFileSync(join(MIGRATIONS, fifth), "utf8"));
    const rows = await db.query(`select kind, value, strength from pz.person_identifiers order by id`);
    assert.deepEqual(rows.rows.map((r) => [r.kind, r.strength]), [["orcid", "strong"], ["alias", "weak"], ["profile_url", "strong"]]);
    await db.query(`insert into pz.people (id, name) values ('p-b', 'Bea')`);
    await rejects(
      db.query(`insert into pz.person_identifiers (person_id, kind, value) values ('p-b', 'orcid', 'https://orcid.org/0000-0002-1825-0097')`),
      /person_identifiers_strong_unique/,
    );
  });
});

describe("migration 0006 — every Network people write is an append-only person event", () => {
  test("events reference the text person id, are never changed, and their action is a known one", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.people (id, name) values ('p-ada-lovelace', 'Ada Lovelace')`);
    await db.query(
      `insert into pz.person_events (person_id, actor, action, before, after) values ('p-ada-lovelace', 'operator', 'save', $1, $2)`,
      [JSON.stringify({ next_action: "" }), JSON.stringify({ next_action: "call" })],
    );
    const row = await db.query(`select person_id, before, after, detail from pz.person_events`);
    assert.deepEqual(row.rows[0], {
      person_id: "p-ada-lovelace",
      before: { next_action: "" },
      after: { next_action: "call" },
      detail: {},
    });
    for (const action of ["create", "talented", "watch_log"]) {
      await db.query(`insert into pz.person_events (person_id, actor, action, after) values ('p-ada-lovelace', 'operator', $1, '{}')`, [action]);
    }
    await rejects(db.query(`update pz.person_events set actor = 'x'`), /append-only/);
    await rejects(db.query(`delete from pz.person_events`), /append-only/);
    await rejects(db.query(`delete from pz.people where id = 'p-ada-lovelace'`), /append-only/); // the history keeps the person
    await rejects(
      db.query(`insert into pz.person_events (person_id, actor, action, after) values ('p-ada-lovelace', 'operator', 'delete', '{}')`),
      /person_events_action_check/,
    );
    await rejects(
      db.query(`insert into pz.person_events (person_id, actor, action, after) values ('p-nobody', 'operator', 'save', '{}')`),
      /person_events_person_id_fkey/,
    );
    await rejects(
      db.query(`insert into pz.person_events (person_id, actor, action) values ('p-ada-lovelace', 'operator', 'save')`),
      /null value/,
    );
    const rls = await db.query(`select relrowsecurity from pg_class where relname = 'person_events'`);
    assert.equal(rls.rows[0].relrowsecurity, true);
    const grants = await db.query(
      `select count(*)::int n from information_schema.role_table_grants
        where table_schema = 'pz' and table_name = 'person_events' and grantee in ('anon', 'authenticated', 'PUBLIC')`,
    );
    assert.equal(grants.rows[0].n, 0);
  });
});

describe("migration 0007 — an event's dates as stated, and the event leads", () => {
  test("dates and times are stored as stated; the derived span is all-or-nothing and forward", async () => {
    const db = await freshDb();
    await db.query(
      `insert into pz.events (id, name, start_date, start_time, end_date, end_time, starts_at, ends_at)
       values ('ev-a', 'Demo day', '2026-09-20', '18:30', '2026-09-20', null,
               '2026-09-20 18:30+02', '2026-09-21 00:00+02')`,
    );
    await db.query(`insert into pz.events (id, name, end_date) values ('ev-undated', 'Undated', '2026-09-22')`);
    const row = await db.query(`select start_date::text, start_time, end_time from pz.events where id = 'ev-a'`);
    assert.deepEqual(row.rows[0], { start_date: "2026-09-20", start_time: "18:30", end_time: null });
    await rejects(
      db.query(`insert into pz.events (id, name, start_date, start_time, starts_at, ends_at)
                values ('ev-b', 'B', '2026-09-20', '24:00', '2026-09-20 00:00+02', '2026-09-21 00:00+02')`),
      /events_start_time_is_hhmm/,
    );
    await rejects(
      db.query(`insert into pz.events (id, name, end_time) values ('ev-c', 'C', '18:30')`),
      /events_time_needs_a_date/,
    );
    await rejects(
      db.query(`insert into pz.events (id, name, start_date) values ('ev-d', 'D', '2026-09-20')`),
      /events_span_iff_start/,
    );
    await rejects(
      db.query(`insert into pz.events (id, name, start_date, starts_at, ends_at)
                values ('ev-e', 'E', '2026-09-20', '2026-09-20 00:00+02', '2026-09-20 00:00+02')`),
      /events_span_is_forward/,
    );
  });

  test("leads are their own locked-down table with the old decision vocabulary", async () => {
    const db = await freshDb();
    await db.query(
      `insert into pz.event_leads (id, title, lead_date, date_raw, legacy) values ('evlead-1', 'Meetup', '2026-12-03', '2026-12-03', '{}')`,
    );
    const row = await db.query(`select decision, attrs, lead_date::text from pz.event_leads`);
    assert.deepEqual(row.rows[0], { decision: "new", attrs: {}, lead_date: "2026-12-03" });
    for (const decision of ["dismissed", "converted"]) {
      await db.query(`update pz.event_leads set decision = $1`, [decision]);
    }
    await rejects(db.query(`update pz.event_leads set decision = 'maybe'`), /event_leads_decision_check/);
    await rejects(db.query(`insert into pz.event_leads (id) values ('evlead-1')`), /event_leads_pkey/);
    const touched = await db.query(`select updated_at > created_at as touched from pz.event_leads`);
    assert.equal(touched.rows[0].touched, true);
    const rls = await db.query(`select relrowsecurity from pg_class where relname = 'event_leads'`);
    assert.equal(rls.rows[0].relrowsecurity, true);
    const grants = await db.query(
      `select count(*)::int n from information_schema.role_table_grants
        where table_schema = 'pz' and table_name = 'event_leads' and grantee in ('anon', 'authenticated', 'PUBLIC')`,
    );
    assert.equal(grants.rows[0].n, 0);
  });

  test("it refuses to run over existing events instead of inventing their dates", async () => {
    const { PGlite } = await import("@electric-sql/pglite");
    const { readdirSync } = await import("node:fs");
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
    const seventh = files.find((f) => f.includes("event_dates"));
    for (const f of files.filter((f) => f < seventh)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
    await db.query(`insert into pz.events (id, name, starts_at) values ('ev-early', 'Early', '2026-09-20 00:00+02')`);
    await rejects(db.exec(readFileSync(join(MIGRATIONS, seventh), "utf8")), /events is not empty/);
    const cols = await db.query(
      `select count(*)::int n from information_schema.columns where table_schema = 'pz' and table_name = 'events' and column_name = 'start_date'`,
    );
    assert.equal(cols.rows[0].n, 0); // nothing half-applied
    const leads = await db.query(`select to_regclass('pz.event_leads') is null as absent`);
    assert.equal(leads.rows[0].absent, true);
  });
});

describe("migration 0008 — every Events write is an append-only history row; debrief leads have their own origin", () => {
  test("a history row has exactly one target, a known action, and is never changed", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.events (id, name) values ('ev-a', 'Demo day')`);
    await db.query(`insert into pz.event_leads (id, title) values ('evlead-1', 'Meetup')`);
    await db.query(
      `insert into pz.event_history (event_id, actor, action, before, after) values ('ev-a', 'operator', 'save', $1, $2)`,
      [JSON.stringify({ status: "new" }), JSON.stringify({ status: "planned" })],
    );
    await db.query(`insert into pz.event_history (lead_id, actor, action, after) values ('evlead-1', 'operator', 'convert', '{}')`);
    for (const action of ["create", "merge", "verify", "lead_decision", "debrief", "scout_add"]) {
      await db.query(`insert into pz.event_history (event_id, actor, action, after) values ('ev-a', 'operator', $1, '{}')`, [action]);
    }
    const row = await db.query(`select event_id, lead_id, before, after, detail from pz.event_history order by id limit 1`);
    assert.deepEqual(row.rows[0], { event_id: "ev-a", lead_id: null, before: { status: "new" }, after: { status: "planned" }, detail: {} });
    await rejects(db.query(`insert into pz.event_history (actor, action, after) values ('operator', 'save', '{}')`), /event_history_one_target/);
    await rejects(
      db.query(`insert into pz.event_history (event_id, lead_id, actor, action, after) values ('ev-a', 'evlead-1', 'operator', 'save', '{}')`),
      /event_history_one_target/,
    );
    await rejects(
      db.query(`insert into pz.event_history (event_id, actor, action, after) values ('ev-a', 'operator', 'delete', '{}')`),
      /event_history_action_check/,
    );
    await rejects(
      db.query(`insert into pz.event_history (event_id, actor, action, after) values ('ev-nobody', 'operator', 'save', '{}')`),
      /event_history_event_id_fkey/,
    );
    await rejects(db.query(`update pz.event_history set actor = 'x'`), /append-only/);
    await rejects(db.query(`delete from pz.event_history`), /append-only/);
    await rejects(db.query(`delete from pz.events where id = 'ev-a'`), /append-only/); // the history keeps the event
    const rls = await db.query(`select relrowsecurity from pg_class where relname = 'event_history'`);
    assert.equal(rls.rows[0].relrowsecurity, true);
  });

  test("intake accepts the server-side origin event_debrief, and still refuses an unknown one", async () => {
    const db = await freshDb();
    const insert = (origin, sha) =>
      db.query(
        `insert into pz.intake_submissions (origin, submitted_by, sha256, contract_version, payload) values ($1, 'operator', $2, '1.0', '{}')`,
        [origin, sha],
      );
    await insert("event_debrief", "a".repeat(64));
    await insert("legacy_dealflow", "b".repeat(64));
    await rejects(insert("event_scan", "c".repeat(64)), /intake_submissions_origin_check/);
  });
});

describe("migration 0009 — watcher baselines are live state; the scan writes its own history actions", () => {
  test("one baseline per watcher source, always a JSON array, and the scan actions are known", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.event_watch_snapshots (source_id, url, lines) values ('s-w', 'https://w.example.com/', '[]')`);
    await db.query(
      `insert into pz.event_watch_snapshots (source_id, url, lines, seeded_from) values ('s-v', 'https://v.example.com/', $1, '.watch/ev-abc.json')`,
      [JSON.stringify(["a line"])],
    );
    await rejects(
      db.query(`insert into pz.event_watch_snapshots (source_id, url, lines) values ('s-w', 'https://w.example.com/', '[]')`),
      /event_watch_snapshots_pkey/,
    );
    await rejects(
      db.query(`insert into pz.event_watch_snapshots (source_id, url, lines) values ('s-x', 'https://x.example.com/', '{}')`),
      /event_watch_snapshots_lines_check/,
    );
    await db.query(`insert into pz.events (id, name) values ('ev-a', 'Demo day')`);
    await db.query(`insert into pz.event_leads (id, title) values ('evlead-1', 'Meetup')`);
    for (const action of ["scan_create", "scan_merge"]) {
      await db.query(`insert into pz.event_history (event_id, actor, action, after) values ('ev-a', 'operator', $1, '{}')`, [action]);
    }
    await db.query(`insert into pz.event_history (lead_id, actor, action, after) values ('evlead-1', 'operator', 'scan_lead', '{}')`);
    await rejects(
      db.query(`insert into pz.event_history (event_id, actor, action, after) values ('ev-a', 'operator', 'scan_delete', '{}')`),
      /event_history_action_check/,
    );
    const rls = await db.query(`select relrowsecurity from pg_class where relname = 'event_watch_snapshots'`);
    assert.equal(rls.rows[0].relrowsecurity, true);
  });
});

describe("migration 0010 — one Radar milestone per Conviction entry", () => {
  test("radar_milestone is a known action, written once per entry", async () => {
    const db = await freshDb();
    const co = (await db.query(`insert into pz.companies (name) values ('Radared Co') returning id`)).rows[0].id;
    const entry = (
      await db.query(`insert into pz.conviction_entries (company_id, slug, status) values ($1, 'radared', 'new') returning id`, [co])
    ).rows[0].id;
    const credit = () =>
      db.query(
        `insert into pz.conviction_events (entry_id, slug, actor, action, before, after, detail) values ($1, 'radared', 'system', 'radar_milestone', $2, $3, $4)`,
        [entry, JSON.stringify({ q_milestones: null }), JSON.stringify({ q_milestones: ["radar"] }), JSON.stringify({ source_id: null, legacy_credit: false, counted: false })],
      );
    await credit();
    await rejects(credit(), /conviction_events_one_radar_milestone/);
    await db.query(`insert into pz.conviction_events (entry_id, slug, actor, action, after) values ($1, 'radared', 'operator', 'status', '{}')`, [entry]);
    await db.query(`insert into pz.conviction_events (entry_id, slug, actor, action, after) values ($1, 'radared', 'operator', 'status', '{}')`, [entry]);
    await rejects(
      db.query(`insert into pz.conviction_events (entry_id, slug, actor, action, after) values ($1, 'radared', 'operator', 'radar_delete', '{}')`, [entry]),
      /conviction_events_action_check/,
    );
  });
});

describe("migration 0011 — the content log: items, append-only events, one idempotent backfill", () => {
  const archive = (db, body) => db.query(`insert into pz.documents (key, body) values ('content.json', $1)`, [JSON.stringify(body)]);

  test("the backfill maps the archived log in order, once; a retry keeps later edits", async () => {
    const db = await freshDb();
    await archive(db, { note: "kept", items: [{ id: "c-2", title: "Second", kind: "draft", inbound: 3 }, { id: "c-1", title: "First" }] });
    assert.equal((await db.query(`select pz.backfill_content_items() as n`)).rows[0].n, 2);
    const rows = await db.query(`select id, pos, title, kind, attrs->'record'->'inbound' as inbound from pz.content_items order by pos`);
    assert.deepEqual(rows.rows.map((r) => [r.id, r.pos, r.title, r.kind, r.inbound]), [["c-2", 0, "Second", "draft", 3], ["c-1", 1, "First", null, null]]);
    await db.query(`update pz.content_items set title = 'Edited', attrs = jsonb_set(attrs, '{record,title}', '"Edited"') where id = 'c-1'`);
    assert.equal((await db.query(`select pz.backfill_content_items() as n`)).rows[0].n, 0);
    assert.equal((await db.query(`select title from pz.content_items where id = 'c-1'`)).rows[0].title, "Edited");
  });

  test("a malformed log raises and writes nothing", async () => {
    for (const body of [{ items: [{ id: "a" }, { id: 7 }] }, { items: [{ id: "a" }, { id: "a" }] }, { items: [{ title: "no id" }] }, { items: {} }, ["x"]]) {
      const db = await freshDb();
      await archive(db, body);
      await rejects(db.query(`select pz.backfill_content_items()`), /content\.json/);
      assert.equal((await db.query(`select count(*)::int as n from pz.content_items`)).rows[0].n, 0);
    }
  });

  test("events are append-only with known actions; ids are non-empty; RLS is on", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.content_items (id, pos) values ('c-x', 0)`);
    await db.query(`insert into pz.content_item_events (item_id, actor, action, after) values ('c-x', 'operator', 'create', '{}')`);
    await rejects(db.query(`update pz.content_item_events set actor = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.content_item_events (item_id, actor, action, after) values ('c-x', 'operator', 'purge', '{}')`), /content_item_events_action_check/);
    await rejects(db.query(`insert into pz.content_items (id, pos) values ('', 1)`), /content_items_id_check/);
    await rejects(db.query(`insert into pz.content_items (id, pos) values ('c-y', 0)`), /content_items_pos_key/);
    for (const t of ["content_items", "content_item_events"]) {
      assert.equal((await db.query(`select relrowsecurity from pg_class where relname = $1`, [t])).rows[0].relrowsecurity, true);
    }
  });
});

describe("migration 0013 — a coverage adoption is one append-only row per candidate", () => {
  test("adoptions reference a source, are unique per candidate and never change; adopt is a source event", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.sources (id, name, kind) values ('cov-x1', 'Example watcher', 'watcher')`);
    await db.query(`insert into pz.coverage_adoptions (candidate_id, source_id, families, by) values ('cand-x1', 'cov-x1', '{grants}', 'operator')`);
    await rejects(db.query(`insert into pz.coverage_adoptions (candidate_id, source_id, by) values ('cand-x1', 'cov-x1', 'operator')`), /coverage_adoptions_pkey/);
    await rejects(db.query(`insert into pz.coverage_adoptions (candidate_id, source_id, by) values ('cand-x2', 'no-such', 'operator')`), /foreign key/);
    await rejects(db.query(`update pz.coverage_adoptions set note = 'x'`), /append-only/);
    await db.query(`insert into pz.source_events (source_id, actor, action, before, after) values ('cov-x1', 'operator', 'adopt', '{}', '{}')`);
    await rejects(db.query(`insert into pz.source_events (source_id, actor, action, before, after) values ('cov-x1', 'operator', 'scan', '{}', '{}')`), /source_events_action_check/);
    assert.equal((await db.query(`select relrowsecurity from pg_class where relname = 'coverage_adoptions'`)).rows[0].relrowsecurity, true);
  });
});

describe("migration 0014 — founder calls in their ORIGINAL order, from the byte-exact archive", () => {
  const archive = async (db, text) => {
    const raw = Buffer.from(text, "utf8");
    const sha = (await import("node:crypto")).createHash("sha256").update(raw).digest("hex");
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ('founder_calls.json', $1, $2, $3, $4)`,
      [sha, raw.length, raw, text]);
  };
  // insertion order differs from JSONB order (JSONB sorts keys by length, then bytes): long ids first, a short id last
  const text = JSON.stringify({ version: 1, label: "x", companies: { "co-zzzz-long": { id: "co-zzzz-long", name: "Zeta" }, "co-a": { id: "co-a", name: "Alpha" } },
    founders: { "fo-yy-long": { id: "fo-yy-long", name: "Y", company_id: "co-zzzz-long" }, "fo-b": { id: "fo-b", name: "B", company_id: "co-a" } },
    calls: { "ca-x-long-2": { id: "ca-x-long-2", date: "2026-11-01", founder_id: "fo-yy-long" }, "ca-1": { id: "ca-1", date: "2026-11-01", founder_id: "fo-b" } } });

  test("positions follow the raw insertion order; a retry keeps edits", async () => {
    const db = await freshDb();
    await archive(db, text);
    assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 6);
    for (const [t, ids] of [["fc_companies", ["co-zzzz-long", "co-a"]], ["fc_founders", ["fo-yy-long", "fo-b"]], ["fc_calls", ["ca-x-long-2", "ca-1"]]]) {
      assert.deepEqual((await db.query(`select id from pz.${t} order by pos`)).rows.map((r) => r.id), ids);
    }
    await db.query(`update pz.fc_calls set attrs = jsonb_set(attrs, '{record,date}', '"2026-11-02"') where id = 'ca-1'`);
    assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 0);
    assert.equal((await db.query(`select attrs->'record'->>'date' as d from pz.fc_calls where id = 'ca-1'`)).rows[0].d, "2026-11-02");
  });

  test("a malformed archive raises and writes nothing; events are append-only", async () => {
    for (const empty of [`{}`, `{"version": 1}`, `{"calls": {}}`]) {  // absent or empty: nothing to map, no error
      const db = await freshDb();
      await archive(db, empty);
      assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 0);
    }
    for (const bad of [`[1]`, `{"calls": null}`, `{"calls": []}`, `{"calls": {"ca-1": 5}}`, `{"calls": {"ca-1": {"id": "ca-2"}}}`, `{"calls": {"ca-1": {}, "ca-1": {}}}`]) {
      const db = await freshDb();
      await archive(db, bad);
      await rejects(db.query(`select pz.backfill_founder_calls()`), /founder_calls\.json/);
      assert.equal((await db.query(`select count(*)::int as n from pz.fc_calls`)).rows[0].n, 0);
    }
    const db = await freshDb();
    await db.query(`insert into pz.fc_events (actor, action, before, after) values ('operator', 'save', '{}', '{}')`);
    await rejects(db.query(`update pz.fc_events set actor = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.fc_events (actor, action, before, after) values ('operator', 'delete', '{}', '{}')`), /fc_events_action_check/);
  });
});

describe("migration 0015 — evaluator sessions in their ORIGINAL order, from the byte-exact archive", () => {
  const archive = async (db, text) => {
    const raw = Buffer.from(text, "utf8");
    const sha = (await import("node:crypto")).createHash("sha256").update(raw).digest("hex");
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ('evaluations.json', $1, $2, $3, $4)`,
      [sha, raw.length, raw, text]);
  };
  test("positions follow the raw insertion order of the sessions object; a retry keeps edits; malformed raises", async () => {
    const db = await freshDb();
    // a long id first, a short id last (JSONB would reverse them); both created at the same instant
    await archive(db, JSON.stringify({ sessions: { "ev-20261101090000-aaaaaa": { id: "ev-20261101090000-aaaaaa", created: "2026-11-01 09:00", status: "ended", subject: { kind: "company", name: "Long" } },
      "ev-1": { id: "ev-1", created: "2026-11-01 09:00", status: "open", subject: { kind: "external", name: "Short" } } } }));
    assert.equal((await db.query(`select pz.backfill_evaluations() as n`)).rows[0].n, 2);
    assert.deepEqual((await db.query(`select id from pz.eval_sessions order by pos`)).rows.map((r) => r.id), ["ev-20261101090000-aaaaaa", "ev-1"]);
    assert.equal((await db.query(`select subject_kind from pz.eval_sessions where id = 'ev-1'`)).rows[0].subject_kind, "external");
    assert.equal((await db.query(`select pz.backfill_evaluations() as n`)).rows[0].n, 0);
    for (const empty of [`{}`, `{"version": 1}`, `{"sessions": {}}`]) {  // absent or empty: nothing to map, no error
      const d2 = await freshDb();
      await archive(d2, empty);
      assert.equal((await d2.query(`select pz.backfill_evaluations() as n`)).rows[0].n, 0);
    }
    for (const bad of [`[1]`, `{"sessions": null}`, `{"sessions": []}`, `{"sessions": {"ev-1": 5}}`, `{"sessions": {"ev-1": {"id": "ev-2"}}}`,
                       `{"sessions": {"ev-1": {"id": 1}}}`, `{"sessions": {"ev-1": {}, "ev-1": {}}}`]) {
      const d2 = await freshDb();
      await archive(d2, bad);
      await rejects(d2.query(`select pz.backfill_evaluations()`), /evaluations\.json/);
      assert.equal((await d2.query(`select count(*)::int as n from pz.eval_sessions`)).rows[0].n, 0);
    }
    await db.query(`insert into pz.eval_events (session_id, actor, action, after) values ('ev-1', 'operator', 'answer', '{}')`);
    await rejects(db.query(`update pz.eval_events set actor = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.eval_events (session_id, actor, action, after) values ('ev-1', 'operator', 'purge', '{}')`), /eval_events_action_check/);
  });
});

describe("migrations 0014 / 0015 — an archive with the optional UTF-8 BOM maps like one without (Codex H-192 / H-195)", () => {
  const withBom = async (db, path, doc) => {
    const text = JSON.stringify(doc);
    const raw = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(text, "utf8")]);
    const sha = (await import("node:crypto")).createHash("sha256").update(raw).digest("hex");
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, $5)`,
      [path, sha, raw.length, raw, text]);
    return raw;
  };
  test("the upgrade: a BOM archive already present before 0014 survives 0014 and 0015 in sequence", async () => {
    const { PGlite } = await import("@electric-sql/pglite");
    const { readdirSync } = await import("node:fs");
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
    const m14 = files.find((f) => f.includes("founder_calls"));
    for (const f of files.filter((f) => f < m14)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
    const raw = await withBom(db, "founder_calls.json", { version: 1, label: "Invented", companies: { "co-zzzz-long": { id: "co-zzzz-long", name: "Long Co" }, "co-a": { id: "co-a", name: "Short Co" } } });
    for (const f of files.filter((f) => f >= m14)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));  // 0014 (its backfill), 0015, ...
    assert.deepEqual((await db.query(`select id, name from pz.fc_companies order by pos`)).rows, [{ id: "co-zzzz-long", name: "Long Co" }, { id: "co-a", name: "Short Co" }]);
    assert.deepEqual(Buffer.from((await db.query(`select raw from pz.legacy_documents where path = 'founder_calls.json'`)).rows[0].raw), raw);
    assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 0);  // the importer's later call: idempotent
  });

  test("the upgrade from 0014 as first committed (3470852): 0015 alone installs the reader and refreshes the backfill", async () => {
    const { PGlite } = await import("@electric-sql/pglite");
    const { readdirSync } = await import("node:fs");
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    const files = readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql")).sort();
    const m14 = files.find((f) => f.includes("founder_calls"));
    for (const f of files.filter((f) => f < m14)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));
    await db.exec(readFileSync(join(FIXTURES, "0014_founder_calls_as_committed_3470852.sql"), "utf8"));  // no BOM reader
    for (const f of files.filter((f) => f > m14)) await db.exec(readFileSync(join(MIGRATIONS, f), "utf8"));  // 0015, ...
    const fcRaw = await withBom(db, "founder_calls.json", { version: 1, label: "Invented", companies: { "co-zzzz-long": { id: "co-zzzz-long", name: "Long Co" }, "co-a": { id: "co-a", name: "Short Co" } } });
    const evRaw = await withBom(db, "evaluations.json", { version: 1, sessions: { "ev-20261101090000-aaaaaa": { id: "ev-20261101090000-aaaaaa" }, "ev-1": { id: "ev-1" } } });
    assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 2);
    assert.equal((await db.query(`select pz.backfill_evaluations() as n`)).rows[0].n, 2);
    assert.deepEqual((await db.query(`select id from pz.fc_companies order by pos`)).rows.map((r) => r.id), ["co-zzzz-long", "co-a"]);
    assert.deepEqual((await db.query(`select id from pz.eval_sessions order by pos`)).rows.map((r) => r.id), ["ev-20261101090000-aaaaaa", "ev-1"]);
    for (const [p, raw] of [["founder_calls.json", fcRaw], ["evaluations.json", evRaw]]) {
      assert.deepEqual(Buffer.from((await db.query(`select raw from pz.legacy_documents where path = $1`, [p])).rows[0].raw), raw);
    }
  });

  test("both backfills and the archive reader skip the BOM; the archived bytes are kept", async () => {
    const db = await freshDb();
    const fcRaw = await withBom(db, "founder_calls.json", { version: 1, label: "Invented", companies: { "co-zzzz-long": { id: "co-zzzz-long", name: "Long Co" }, "co-a": { id: "co-a", name: "Short Co" } } });
    const evRaw = await withBom(db, "evaluations.json", { version: 1, sessions: { "ev-20261101090000-aaaaaa": { id: "ev-20261101090000-aaaaaa", status: "open" }, "ev-1": { id: "ev-1", status: "ended" } } });
    assert.equal((await db.query(`select pz.backfill_founder_calls() as n`)).rows[0].n, 2);
    assert.equal((await db.query(`select pz.backfill_evaluations() as n`)).rows[0].n, 2);
    assert.deepEqual((await db.query(`select id from pz.fc_companies order by pos`)).rows.map((r) => r.id), ["co-zzzz-long", "co-a"]);
    assert.deepEqual((await db.query(`select id from pz.eval_sessions order by pos`)).rows.map((r) => r.id), ["ev-20261101090000-aaaaaa", "ev-1"]);
    const keys = async (p) => (await db.query(`select array_agg(k order by o) as k from json_object_keys(pz.archived_json($1)) with ordinality as t(k, o)`, [p])).rows[0].k;
    assert.deepEqual(await keys("founder_calls.json"), ["version", "label", "companies"]);  // the top level, in order
    assert.deepEqual(await keys("evaluations.json"), ["version", "sessions"]);
    for (const [p, raw] of [["founder_calls.json", fcRaw], ["evaluations.json", evRaw]]) {
      const kept = (await db.query(`select raw from pz.legacy_documents where path = $1`, [p])).rows[0].raw;
      assert.deepEqual(Buffer.from(kept), raw);  // the BOM stays in the archive
    }
  });
});

describe("migration 0016 — Founder Radar companies and research in their ORIGINAL order, the records' own key order kept", () => {
  const archive = async (db, path, text, bom = false) => {
    const body = Buffer.from(text, "utf8");
    const raw = bom ? Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), body]) : body;
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, $5)`,
      [path, sha256(raw), raw.length, raw, text]);
  };
  // long keys first (JSONB would put the short ones first), and a research record whose proposals / pages maps are
  // not in JSONB order either
  const companies = { companies: { "name:invented-longer-robotics": { founder_refs: {}, facts: [] }, "dom:a.example": { notes: "x" } } };
  const research = { domains: { "name:invented-longer-robotics": { domain: "", pages: { "https://zz.example/long": { chars: 1 }, "https://a.example/": { chars: 2 } },
    proposals: { "pr-zzzzzzzzzzzz": { status: "pending" }, "pr-a": { status: "pending" } }, pairings: {}, history: [] } } };
  test("positions follow the raw order; the stored json keeps the inner key order; a retry keeps edits; BOM", async () => {
    const db = await freshDb();
    await archive(db, "radar_companies.json", JSON.stringify(companies), true);
    await archive(db, "radar_research.json", JSON.stringify(research));
    assert.equal((await db.query(`select pz.backfill_founder_radar() as n`)).rows[0].n, 3);
    assert.deepEqual((await db.query(`select key from pz.radar_companies order by pos`)).rows.map((r) => r.key), ["name:invented-longer-robotics", "dom:a.example"]);
    const keys = async (expr) => (await db.query(`select array_agg(k order by o) as k from json_object_keys((${expr})) with ordinality as t(k, o)`)).rows[0].k;
    assert.deepEqual(await keys(`select record -> 'proposals' from pz.radar_research`), ["pr-zzzzzzzzzzzz", "pr-a"]);
    assert.deepEqual(await keys(`select record -> 'pages' from pz.radar_research`), ["https://zz.example/long", "https://a.example/"]);
    assert.deepEqual(await keys(`select record from pz.radar_research`), ["domain", "pages", "proposals", "pairings", "history"]);
    await db.query(`update pz.radar_companies set record = '{"notes": "edited"}'::json where key = 'dom:a.example'`);
    assert.equal((await db.query(`select pz.backfill_founder_radar() as n`)).rows[0].n, 0);
    assert.equal((await db.query(`select record->>'notes' as n from pz.radar_companies where key = 'dom:a.example'`)).rows[0].n, "edited");
  });

  test("a malformed archive raises and writes nothing; events are append-only", async () => {
    for (const [path, bad] of [["radar_companies.json", `[1]`], ["radar_companies.json", `{"companies": null}`], ["radar_companies.json", `{"companies": []}`],
                               ["radar_companies.json", `{"companies": {"k": 5}}`], ["radar_companies.json", `{"companies": {"": {}}}`],
                               ["radar_research.json", `{"domains": {"k": {}, "k": {}}}`]]) {
      const db = await freshDb();
      await archive(db, path, bad);
      await rejects(db.query(`select pz.backfill_founder_radar()`), /radar_(companies|research)\.json/);
      assert.equal((await db.query(`select (select count(*) from pz.radar_companies) + (select count(*) from pz.radar_research) as n`)).rows[0].n, 0);
    }
    const db = await freshDb();
    for (const empty of [`{}`, `{"companies": {}}`]) {
      const d2 = await freshDb();
      await archive(d2, "radar_companies.json", empty);
      assert.equal((await d2.query(`select pz.backfill_founder_radar() as n`)).rows[0].n, 0);
    }
    await db.query(`insert into pz.radar_events (entity, key, actor, action, after) values ('company', 'k', 'operator', 'company', '{}')`);
    await rejects(db.query(`update pz.radar_events set actor = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.radar_events (entity, key, actor, action, after) values ('company', 'k', 'operator', 'purge', '{}')`), /radar_events_action_check/);
  });

  test("the merge tombstone and the new person-event actions", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.people (id, name) values ('p-a', 'Ada Invented'), ('p-b', 'Bea Invented')`);
    await db.query(`update pz.people set merged_into = 'p-a' where id = 'p-b'`);
    await rejects(db.query(`update pz.people set merged_into = 'p-a' where id = 'p-a'`), /people_not_merged_into_itself/);
    await rejects(db.query(`update pz.people set merged_into = 'p-nobody' where id = 'p-a'`), /foreign key/);
    for (const action of ["radar", "merge", "merged"]) {
      await db.query(`insert into pz.person_events (person_id, actor, action, after) values ('p-a', 'operator', $1, '{}')`, [action]);
    }
    await rejects(db.query(`insert into pz.person_events (person_id, actor, action, after) values ('p-a', 'operator', 'delete', '{}')`), /person_events_action_check/);
  });
});

describe("migration 0017 — the Founder Radar runs' events", () => {
  test("scan and research events on records and documents; still append-only", async () => {
    const db = await freshDb();
    for (const [entity, action] of [["document", "scan"], ["research", "research"], ["metrics", "snapshot"], ["company", "company"]]) {
      await db.query(`insert into pz.radar_events (entity, key, actor, action, after) values ($1, 'k', 'operator', $2, '{}')`, [entity, action]);
    }
    await rejects(db.query(`insert into pz.radar_events (entity, key, actor, action, after) values ('people', 'k', 'operator', 'scan', '{}')`), /radar_events_entity_check/);
    await rejects(db.query(`insert into pz.radar_events (entity, key, actor, action, after) values ('document', 'k', 'operator', 'delete', '{}')`), /radar_events_action_check/);
    await rejects(db.query(`update pz.radar_events set actor = 'x'`), /append-only/);
  });
});

describe("migration 0018 — the four Validation logs as one append-only table, backfilled by archive line", () => {
  const MIGRATION = "20261112000018_validation_log.sql";
  const archive = async (db, path, raw) => {
    const bytes = Buffer.isBuffer(raw) ? raw : Buffer.from(raw, "utf8");
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, null)`,
      [path, sha256(bytes), bytes.length, bytes]);
  };
  /** Every migration before 0018 applied (an existing database) with archives already imported, then 0018. */
  const before0018 = async (archives = {}) => {
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    for (const file of readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql") && f < MIGRATION).sort()) {
      await db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
    }
    for (const [path, raw] of Object.entries(archives)) await archive(db, path, raw);
    await db.exec(readFileSync(join(MIGRATIONS, MIGRATION), "utf8"));
    return db;
  };
  const rows = async (db, log) =>
    (await db.query(`select line, source, archive_line from pz.validation_log where log = $1 order by seq`, [log])).rows;
  const count = async (db) => (await db.query(`select count(*)::int as n from pz.validation_log`)).rows[0].n;
  const backfill = async (db) => (await db.query(`select pz.backfill_validation() as n`)).rows[0].n;
  const dup = `{"a": 1}`;
  const OUT = `{"id": "oc-1"}\n${dup}\n${dup}\nnot json\n{"id": "oc-4"}\n`; // identical lines at different positions

  test("the existing path: 0018 maps the imported archives; a rerun adds nothing; duplicates survive", async () => {
    const db = await before0018({ "validation/outcomes.jsonl": OUT, "validation/snapshots.jsonl": `{"date": "2026-11-01"}\n` });
    assert.deepEqual((await rows(db, "outcomes")).map((r) => [r.line, r.archive_line]),
      [[`{"id": "oc-1"}`, 1], [dup, 2], [dup, 3], ["not json", 4], [`{"id": "oc-4"}`, 5]]);
    assert.equal((await rows(db, "snapshots")).length, 1);
    assert.equal(await backfill(db), 0);
    assert.equal(await count(db), 6);
  });

  test("the fresh path: 0018 on an empty schema, then the importer's call after the archives arrive", async () => {
    const db = await freshDb();
    assert.equal(await count(db), 0);
    await archive(db, "validation/audits.jsonl", `{"id": "au-1"}\n{"id": "au-2"}`); // no final line end: still 2 lines
    assert.equal(await backfill(db), 2);
    assert.deepEqual((await rows(db, "audits")).map((r) => r.line), [`{"id": "au-1"}`, `{"id": "au-2"}`]);
    assert.equal(await backfill(db), 0);
  });

  test("a rerun after a live row adds nothing and keeps the order; a missing archived line is then refused", async () => {
    const db = await freshDb();
    await archive(db, "validation/outcomes.jsonl", OUT);
    await backfill(db);
    await db.query(`insert into pz.validation_log (log, line, source) values ('outcomes', $1, 'app'), ('outcomes', $1, 'app')`, [dup]);
    const order = (await rows(db, "outcomes")).map((r) => r.line);
    assert.equal(await backfill(db), 0);
    assert.deepEqual((await rows(db, "outcomes")).map((r) => r.line), order);
    assert.equal(order.filter((l) => l === dup).length, 4); // two archived, two identical operator submissions
    // a log with live rows whose archive still has a line not imported (written past the importer): refused
    const d2 = await freshDb();
    await d2.query(`insert into pz.validation_log (log, line, source) values ('outcomes', $1, 'app')`, [dup]);
    await archive(d2, "validation/outcomes.jsonl", OUT);
    await rejects(d2.query(`select pz.backfill_validation()`), /not imported and the log already has live rows/);
    assert.equal(await count(d2), 1);
  });

  test("a later archive line is added in order; a missing line BEFORE an imported one is refused", async () => {
    // lines 1 and 2 imported earlier, the archive now holds a third: only line 3 is added, after them
    const db = await freshDb();
    await db.query(`insert into pz.validation_log (log, line, source, archive_line) values
                    ('snapshots', '{"d": 1}', 'import', 1), ('snapshots', '{"d": 2}', 'import', 2)`);
    await archive(db, "validation/snapshots.jsonl", `{"d": 1}
{"d": 2}
{"d": 3}
`);
    assert.equal(await backfill(db), 1);
    assert.deepEqual((await rows(db, "snapshots")).map((r) => [r.line, r.archive_line]), [[`{"d": 1}`, 1], [`{"d": 2}`, 2], [`{"d": 3}`, 3]]);
    // an imported row at line 2 without line 1: the missing line 1 cannot be placed first
    const d2 = await freshDb();
    await d2.query(`insert into pz.validation_log (log, line, source, archive_line) values ('snapshots', '{"d": 2}', 'import', 2)`);
    await archive(d2, "validation/snapshots.jsonl", `{"d": 1}
{"d": 2}
`);
    await rejects(d2.query(`select pz.backfill_validation()`), /archived line 1 is missing before imported line 2/);
    assert.equal(await count(d2), 1);
  });

  test("BOM, CRLF, CR-only, a torn last line and an undecodable archive", async () => {
    const db = await freshDb();
    await archive(db, "validation/outcomes.jsonl", Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(`{"id": "a"}\r\n{"id": "b"}\r\n`)]));
    await archive(db, "validation/audits.jsonl", `{"id": "c"}\r{"id": "d"}\r`); // CR-only line ends (old text mode)
    await archive(db, "validation/snapshots.jsonl", `{"date": "2026-11-01"}\n{"date": "2026-11-0`); // torn
    await archive(db, "validation/scout_feedback.jsonl", Buffer.from([0x7b, 0xff, 0xfe, 0x7d, 0x0a])); // not UTF-8
    await backfill(db);
    assert.deepEqual((await rows(db, "outcomes")).map((r) => r.line), [`{"id": "a"}`, `{"id": "b"}`]); // no BOM, no CR
    assert.deepEqual((await rows(db, "audits")).map((r) => r.line), [`{"id": "c"}`, `{"id": "d"}`]);
    assert.deepEqual((await rows(db, "snapshots")).map((r) => r.line), [`{"date": "2026-11-01"}`, `{"date": "2026-11-0`]);
    assert.deepEqual(await rows(db, "scout_feedback"), []); // the old read_text: undecodable -> ""
  });

  test("append-only; an import has a positive archive line and an app row none; the log names", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.validation_log (log, line, source) values ('outcomes', '{}', 'app')`);
    await rejects(db.query(`update pz.validation_log set line = 'x'`), /append-only/);
    await rejects(db.query(`delete from pz.validation_log`), /append-only/);
    await rejects(db.query(`insert into pz.validation_log (log, line, source, archive_line) values ('outcomes', '{}', 'app', 3)`), /validation_log_archive_line_check/);
    await rejects(db.query(`insert into pz.validation_log (log, line, source) values ('outcomes', '{}', 'import')`), /validation_log_archive_line_check/);
    await rejects(db.query(`insert into pz.validation_log (log, line, source, archive_line) values ('outcomes', '{}', 'import', 0)`), /validation_log_archive_line_check/);
    await rejects(db.query(`insert into pz.validation_log (log, line, source) values ('news', '{}', 'app')`), /validation_log_log_check/);
    await db.query(`insert into pz.validation_log (log, line, source, archive_line) values ('audits', '{}', 'import', 1)`);
    await rejects(db.query(`insert into pz.validation_log (log, line, source, archive_line) values ('audits', '{}', 'import', 1)`), /duplicate key/);
  });

  test("Codex H-241: a NUL line keeps its valid neighbours and its position; a rerun adds nothing (both paths)", async () => {
    const nul = Buffer.concat([Buffer.from(`{"id": "oc-1"}\n{"id": `), Buffer.from([0x00]), Buffer.from(`"x"}\r\n{"id": "oc-3"}\n`)]);
    for (const db of [await before0018({ "validation/outcomes.jsonl": nul }), await freshDb()]) {
      if ((await count(db)) === 0) {
        await archive(db, "validation/outcomes.jsonl", nul);
        assert.equal(await backfill(db), 3);
      }
      assert.deepEqual((await rows(db, "outcomes")).map((r) => [r.line, r.archive_line]),
        [[`{"id": "oc-1"}`, 1], [null, 2], [`{"id": "oc-3"}`, 3]]);
      assert.equal(await backfill(db), 0);
      assert.equal(await count(db), 3);
      // the archive keeps the original bytes
      const raw = (await db.query(`select raw from pz.legacy_documents where path = 'validation/outcomes.jsonl'`)).rows[0].raw;
      assert.deepEqual(Buffer.from(raw), nul);
    }
    // a NUL line whose other bytes are not UTF-8 makes the whole file unreadable, as the old read_text
    const bad = await freshDb();
    await archive(bad, "validation/audits.jsonl", Buffer.concat([Buffer.from(`{"id": "au-1"}\n`), Buffer.from([0x00, 0xff]), Buffer.from(`\n`)]));
    assert.equal(await backfill(bad), 0);
    // only an imported row may have no line
    await rejects(bad.query(`insert into pz.validation_log (log, line, source) values ('outcomes', null, 'app')`), /validation_log_line_check/);
  });
});

describe("migration 0019 — News events and actions as tables, backfilled in key / line order", () => {
  const MIGRATION = "20261112000019_news.sql";
  const archive = async (db, path, raw) => {
    const bytes = Buffer.isBuffer(raw) ? raw : Buffer.from(raw, "utf8");
    const parsed = path.endsWith(".json") ? bytes.toString("utf8").replace(/^﻿/, "") : null;
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, $5)`,
      [path, sha256(bytes), bytes.length, bytes, parsed]);
  };
  const before0019 = async (archives = {}, documents = {}) => {
    const db = new PGlite();
    await db.exec("create role anon nologin; create role authenticated nologin;");
    for (const file of readdirSync(MIGRATIONS).filter((f) => f.endsWith(".sql") && f < MIGRATION).sort()) {
      await db.exec(readFileSync(join(MIGRATIONS, file), "utf8"));
    }
    for (const [path, raw] of Object.entries(archives)) await archive(db, path, raw);
    for (const [key, body] of Object.entries(documents)) await db.query(`insert into pz.documents (key, body) values ($1, $2)`, [key, body]);
    await db.exec(readFileSync(join(MIGRATIONS, MIGRATION), "utf8"));
    return db;
  };
  const keys = async (db, expr) => (await db.query(`select array_agg(k order by o) as k from json_object_keys((${expr})) with ordinality as t(k, o)`)).rows[0].k;
  const ids = async (db) => (await db.query(`select event_id from pz.news_events order by pos`)).rows.map((r) => r.event_id);
  const backfill = async (db) => (await db.query(`select pz.backfill_news() as n`)).rows[0].n;
  // long keys first (JSONB would put the short ones first), and a record whose own keys are not in JSONB order
  const DOC = `{"version": 2, "events": {"nw-zzzzzzzz-long": {"headline": "Invented Alder raises", "backcast": [], "a": 1}, "nw-a": {"headline": "Invented Birch"}}, "seeded": ["nw-case"]}`;
  const ACTIONS = `{"kind": "outcome_decision", "event_id": "nw-a"}\n{"kind": "miss_audit", "event_id": "nw-a"}\n`;

  test("the existing path: key order, the record key order, the rest with events at its place; a rerun adds nothing", async () => {
    const db = await before0019({ "news/events.json": Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(DOC)]), "news/actions.jsonl": ACTIONS });
    assert.deepEqual(await ids(db), ["nw-zzzzzzzz-long", "nw-a"]);
    assert.deepEqual(await keys(db, `select record from pz.news_events where event_id = 'nw-zzzzzzzz-long'`), ["headline", "backcast", "a"]);
    assert.deepEqual(await keys(db, `select body from pz.news_events_rest`), ["version", "events", "seeded"]);
    assert.equal((await db.query(`select body->'events' is null or json_typeof(body->'events') = 'null' as p from pz.news_events_rest`)).rows[0].p, true);
    assert.deepEqual((await db.query(`select line, archive_line from pz.news_actions order by seq`)).rows.map((r) => r.archive_line), [1, 2]);
    assert.equal(await backfill(db), 0);
  });

  test("the fresh path, and a documents-only installation (JSONB order, as it reads today)", async () => {
    const db = await freshDb();
    assert.equal((await db.query(`select count(*)::int as n from pz.news_events`)).rows[0].n, 0);
    await archive(db, "news/events.json", DOC);
    assert.equal(await backfill(db), 2);
    assert.deepEqual(await ids(db), ["nw-zzzzzzzz-long", "nw-a"]);
    const docs = await before0019({}, { "news/events.json": DOC });
    assert.deepEqual((await docs.query(`select count(*)::int as n from pz.news_events`)).rows[0].n, 2);
    assert.deepEqual((await docs.query(`select body->'seeded' as s from pz.news_events_rest`)).rows[0].s, ["nw-case"]);
  });

  test("a rerun keeps an edited event, the persisted seeded list and the history", async () => {
    const db = await before0019({ "news/events.json": DOC });
    await db.query(`update pz.news_events set record = '{"headline": "edited", "backcast": [{"added_by": "mohamed"}]}'::json where event_id = 'nw-a'`);
    await db.query(`update pz.news_events_rest set body = '{"version": 2, "events": null, "seeded": ["nw-case", "nw-new"]}'::json`);
    await db.query(`insert into pz.news_event_history (event_id, action, after) values ('nw-a', 'backcast', '{}')`);
    assert.equal(await backfill(db), 0);
    assert.equal((await db.query(`select record->>'headline' as h from pz.news_events where event_id = 'nw-a'`)).rows[0].h, "edited");
    assert.deepEqual((await db.query(`select body->'seeded' as s from pz.news_events_rest`)).rows[0].s, ["nw-case", "nw-new"]);
    assert.equal((await db.query(`select count(*)::int as n from pz.news_event_history`)).rows[0].n, 1);
  });

  test("a malformed document raises and writes nothing; the action rules of 0018; append-only", async () => {
    for (const bad of [`[1]`, `{"events": []}`, `{"events": {"k": 5}}`, `{"events": {"": {}}}`]) {
      const db = await freshDb();
      await archive(db, "news/events.json", bad);
      await rejects(db.query(`select pz.backfill_news()`), /news\/events\.json/);
      assert.equal((await db.query(`select count(*)::int as n from pz.news_events`)).rows[0].n, 0);
    }
    const db = await freshDb();
    await db.query(`insert into pz.news_actions (line, source) values ('{}', 'app')`);
    await archive(db, "news/actions.jsonl", ACTIONS);
    await rejects(db.query(`select pz.backfill_news()`), /not imported and the log already has live rows/);
    await rejects(db.query(`update pz.news_actions set line = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.news_actions (line, source, archive_line) values ('{}', 'app', 1)`), /news_actions_archive_line_check/);
    await rejects(db.query(`insert into pz.news_actions (line, source) values (null, 'app')`), /news_actions_line_check/);
    await db.query(`insert into pz.news_event_history (event_id, action, after) values ('nw-a', 'seed', '{}')`);
    await rejects(db.query(`delete from pz.news_event_history`), /append-only/);
    await rejects(db.query(`insert into pz.news_event_history (event_id, action, after) values ('nw-a', 'delete', '{}')`), /news_event_history_action_check/);
    const nul = await freshDb();
    await archive(nul, "news/actions.jsonl", Buffer.concat([Buffer.from(`{"a": 1}\n{"b": `), Buffer.from([0]), Buffer.from(`}\n{"c": 3}\n`)]));
    await nul.query(`select pz.backfill_news()`);
    assert.deepEqual((await nul.query(`select line from pz.news_actions order by seq`)).rows.map((r) => r.line), [`{"a": 1}`, null, `{"c": 3}`]);
  });
});

describe("migration 0020 — the News run's logs and documents, backfilled; the run's history actions", () => {
  const archive = async (db, path, raw) => {
    const bytes = Buffer.isBuffer(raw) ? raw : Buffer.from(raw, "utf8");
    await db.query(`insert into pz.legacy_documents (path, sha256, bytes, raw, parsed) values ($1, $2, $3, $4, null)`,
      [path, sha256(bytes), bytes.length, bytes]);
  };
  const backfill = async (db) => (await db.query(`select pz.backfill_news_files() as n`)).rows[0].n;
  const keys = async (db, expr) => (await db.query(`select array_agg(k order by o) as k from json_object_keys((${expr})) with ordinality as t(k, o)`)).rows[0].k;

  test("logs by line per log, documents in their key order (archive first, else the documents row); reruns keep runs' writes", async () => {
    const db = await freshDb();
    await archive(db, "news/runs.jsonl", `{"run_id": "news-1"}\n{"run_id": "news-1"}\n`); // duplicates survive
    await archive(db, "news/disagreements.jsonl", `{"event_id": "nw-a"}\n`);
    await archive(db, "news/source_metrics.json", `{"windows": {"90": {}}, "at": "2026-11-11T16:05:00"}`);
    await archive(db, "news/source_state.json", `{not json`); // unreadable: the old tolerant default ...
    await db.query(`insert into pz.documents (key, body) values ('news/feed_cooldown.json', '{}'), ('news/source_state.json', '{"Sifted": {"state": "ACTIVE"}}')`);
    assert.equal(await backfill(db), 6); // 3 lines + metrics + cooldown + state (... else the documents row)
    assert.deepEqual((await db.query(`select log, archive_line from pz.news_logs order by seq`)).rows.map((r) => [r.log, r.archive_line]),
      [["runs", 1], ["runs", 2], ["disagreements", 1]]);
    assert.deepEqual(await keys(db, `select body from pz.news_documents where key = 'news/source_metrics.json'`), ["windows", "at"]);
    assert.equal((await db.query(`select body->'Sifted'->>'state' as s from pz.news_documents where key = 'news/source_state.json'`)).rows[0].s, "ACTIVE");
    await db.query(`update pz.news_documents set body = '{"edited": true}'::json where key = 'news/source_metrics.json'`);
    await db.query(`insert into pz.news_logs (log, line, source) values ('runs', '{"run_id": "news-2"}', 'app')`);
    assert.equal(await backfill(db), 0); // a rerun adds nothing and keeps what a run wrote
    assert.equal((await db.query(`select body->>'edited' as e from pz.news_documents where key = 'news/source_metrics.json'`)).rows[0].e, "true");
  });

  test("the 0018 line rules, the CHECKs, append-only, the new history actions", async () => {
    const db = await freshDb();
    await db.query(`insert into pz.news_logs (log, line, source) values ('runs', '{}', 'app')`);
    await archive(db, "news/runs.jsonl", `{"run_id": "news-1"}\n`);
    await rejects(db.query(`select pz.backfill_news_files()`), /not imported and the log already has live rows/);
    await rejects(db.query(`update pz.news_logs set line = 'x'`), /append-only/);
    await rejects(db.query(`insert into pz.news_logs (log, line, source) values ('cards', '{}', 'app')`), /news_logs_log_check/);
    await rejects(db.query(`insert into pz.news_logs (log, line, source, archive_line) values ('runs', '{}', 'app', 1)`), /news_logs_archive_line_check/);
    await rejects(db.query(`insert into pz.news_logs (log, line, source) values ('runs', null, 'app')`), /news_logs_line_check/);
    await rejects(db.query(`insert into pz.news_documents (key, body) values ('news/events.json', '{}')`), /news_documents_key_check/);
    for (const action of ["ingest", "rederive", "card", "seed", "backcast"]) {
      await db.query(`insert into pz.news_event_history (event_id, action, after) values ('nw-a', $1, '{}')`, [action]);
    }
    await rejects(db.query(`insert into pz.news_event_history (event_id, action, after) values ('nw-a', 'purge', '{}')`), /news_event_history_action_check/);
  });
});
