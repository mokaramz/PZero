// The contract's regex patterns must behave the same in ECMA-262 (JS validators, e.g. Grok's tooling) as in Python.
// JSON Schema patterns are ECMA-262 with the `u` flag. Mirror cases of backend/tests/dealflow/test_intake_contract.py.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const schema = JSON.parse(readFileSync(new URL("../intake_submission.schema.json", import.meta.url), "utf8"));
const re = (p) => new RegExp(p, "u");
const name = re(schema.$defs.name_text.pattern);
const statement = re(schema.$defs.statement.pattern);
const url = re(schema.$defs.web_url.pattern);
const placeholder = re(schema.$defs.entity.properties.registry_ids.additionalProperties.not.pattern);

test("names and facts in any writing system pass", () => {
  for (const s of ["王小明", "株式会社テックラボ", "شركة النور للتقنية", "Ελληνική", "한국로봇", "Ölwerk Süd"]) assert.ok(name.test(s), s);
  for (const s of ["2026年10月に東京大学からスピンアウトした", "تأسست الشركة في دبي", "Gegründet in Zürich, Oktober 2026"])
    assert.ok(statement.test(s), s);
});

test("blank or punctuation-only text is refused", () => {
  for (const s of ["   ", "---", "　　　", "。。。。", "———", "！？！？", "  "]) assert.ok(!name.test(s), JSON.stringify(s));
  for (const s of ["a b c d e f", "..........", "x", "\t\n  \n", "。。。。。"]) assert.ok(!statement.test(s), JSON.stringify(s));
});

test("only http(s) URLs with a dotted host pass", () => {
  assert.ok(url.test("https://www.tum.de/news/acme"));
  for (const u of ["mailto:a@b.com", "https://localhost/x", "https:///x", "ftp://a.example.com", "https://exa mple.com"])
    assert.ok(!url.test(u), u);
});

test("registry placeholders are recognised", () => {
  for (const p of ["None", "null", "N/A", "NA", "unknown", "TBD", "000", "--", "?", " none "]) assert.ok(placeholder.test(p), p);
  for (const v of ["079642993", "HRB 12345 München"]) assert.ok(!placeholder.test(v), v);
});
