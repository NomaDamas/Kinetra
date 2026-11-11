// C-01d: the generated types.ts is usable from TypeScript. `pnpm lint` (tsc) is the real assertion for the
// `@ts-expect-error` lines: if a wrong value ever type-checks, tsc reports the unused directive and lint fails.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Badge, DesignSpec, Material, Quantity, Unit, World } from "../types.ts";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const source = { ref: "types.test.ts fixture", declared_by: "test", declared_at: "2026-11-11T00:00:00Z" };

test("a Material literal type-checks and a wrong unit does not", () => {
  const material: Material = {
    id: "example-material",
    name: "Example",
    density: { value: 1000, unit: "kg/m^3", badge: "declared", source },
    yield_strength: { value: 1e7, unit: "Pa", badge: "declared", source },
    elastic_modulus: { value: 1e9, unit: "Pa", badge: "declared", source },
    friction: { value: 0.5, unit: "1", badge: "default", source: { ref: "fixture default" } },
  };
  assert.equal(material.density.unit, "kg/m^3");
  // @ts-expect-error density is in kg/m^3, not g/cm^3
  const bad: Material = { ...material, density: { ...material.density, unit: "g/cm^3" } };
  void bad;
});

test("the badge and unit vocabularies are closed", () => {
  const badge: Badge = "cite";
  const unit: Unit = "N*m";
  // @ts-expect-error not a badge
  const noBadge: Badge = "measured";
  // @ts-expect-error not in the unit vocabulary
  const noUnit: Unit = "mm";
  void [badge, unit, noBadge, noUnit];
});

test("a Quantity needs a badge and a source", () => {
  // @ts-expect-error source is required
  const bare: Quantity = { value: 1, unit: "m", badge: "declared" };
  void bare;
});

test("a field with a default is optional; a required one is not", () => {
  const empty: DesignSpec = {};
  // @ts-expect-error World.planet is required
  const noPlanet: World = {};
  assert.deepEqual(empty, {});
  void noPlanet;
});

test("every example under schemas/examples names a schema file and has its required top-level keys", () => {
  const dir = here("../examples/");
  const examples = readdirSync(dir).filter((f) => f.endsWith(".json"));
  assert.ok(examples.length >= 3, "at least three examples");
  for (const file of examples) {
    const name = file.split(".")[0]!;
    const schema = JSON.parse(readFileSync(here(`../${name}.schema.json`), "utf8")) as { required?: string[] };
    const example = JSON.parse(readFileSync(dir + file, "utf8")) as Record<string, unknown>;
    for (const key of schema.required ?? []) assert.ok(key in example, `${file} lacks required key ${key}`);
  }
});
