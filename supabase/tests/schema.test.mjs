// Schema behaviour that review 001 asked to see demonstrated (findings #1, #2, #4) plus the core guarantees.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { before, describe, test } from "node:test";

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
