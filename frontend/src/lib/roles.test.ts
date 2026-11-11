/**
 * Role labels (docs/design-system.md → Roles): the UI says "Smooth Operator" / "Manager", never a personal name for a
 * ROLE. Real names stay where they are factual data (call participants, intro paths …) — those lines are listed here
 * explicitly, so a new role use of a name can never slip in unnoticed. Also guards the "no AI branding" rule.
 */
import { describe, expect, it } from "vitest";

import { PATHS } from "@/components/Icon";
import { asRole, ROLE } from "./roles";

/** Every app source file as raw text (Vite's glob — no Node APIs), tests excluded. */
const SOURCES = Object.entries(
  import.meta.glob("/src/**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<string, string>,
).filter(([path]) => !path.includes(".test."));

/** Lines where a real name is FACTUAL DATA (a default for the real person in a call record, a real intro path). */
const FACTUAL = [
  'participants: (c ? c.participants : ["Mohamed", founderName])',
  'na_owner: na0?.owner || "Mohamed"',
  'fc.owners.length ? fc.owners : ["Mohamed"]',
  '{ id: "omar", label: "Via Omar", test: viaOmar }',
];

describe("asRole", () => {
  it("maps role uses of the names in system-generated labels", () => {
    expect(asRole("Ask Omar about the possible portfolio conflict")).toBe("Ask Manager about the possible portfolio conflict");
    expect(asRole("Omar's feedback · needs Mohamed")).toBe("Manager's feedback · needs Smooth Operator");
    expect(asRole("CONFLICT — OMAR")).toBe("CONFLICT — MANAGER");
    expect(asRole("Omarion stays")).toBe("Omarion stays"); // whole words only
    expect(asRole("Waiting for human")).toBe("Waiting for Smooth Operator");
    expect(asRole(null)).toBe("");
    expect(ROLE).toMatchObject({ operator: "Smooth Operator", manager: "Manager", machine: "Machine" });
  });
});

describe("UI copy speaks in roles, not personal names", () => {
  it("no role use of Mohamed / Omar in any UI string (comments, identifiers and factual-data lines excepted)", () => {
    expect(SOURCES.length).toBeGreaterThan(40);
    const hits: string[] = [];
    for (const [path, text] of SOURCES) {
      if (path.endsWith("/lib/roles.ts")) continue;
      text.split("\n").forEach((line: string, i: number) => {
        const t = line.trim();
        if (t.startsWith("//") || t.startsWith("*") || t.startsWith("/*") || t.startsWith("{/*")) return;
        if (FACTUAL.some((x) => line.includes(x))) return;
        if (/\b(Mohamed|Omar)\b/.test(line)) hits.push(`${path}:${i + 1}: ${t.slice(0, 100)}`);
      });
    }
    expect(hits).toEqual([]);
  });

  it("no generic AI imagery: no sparkle / robot / brain glyphs, no AI-symbol icons", () => {
    const glyphs = SOURCES.filter(([, src]) => /[✨🤖🧠🪄💫⭐🌟]/u.test(src)).map(([p]) => p);
    expect(glyphs).toEqual([]);
    expect(Object.keys(PATHS).join(" ")).not.toMatch(/sparkle|magic|wand|robot|brain|bot\b|\bai\b|orb|star/i);
  });
});
