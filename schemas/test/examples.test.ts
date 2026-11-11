// C-01 epic (#60): the three example projects read as `Project` from @kinetra/schemas.
// `pnpm lint`/`pnpm build` (tsc --noEmit) type-checks every typed access below against the generated types.ts,
// `pnpm test` runs them. The Python validator (packages/core/scripts/validate_examples.py) is the real judge of
// validity (JSON Schema and model); this file proves a TypeScript client can read the same files with the types.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Actuator, Badge, Project, Quantity, Unit } from "../types.ts";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));

/** Read an example as a `Project`. JSON.parse yields `any`, so the annotation is the one unchecked step (the Python
 * validator and the assertion below judge validity); every field access after it is typed. */
const readProject = (name: string): Project => {
  const project: Project = JSON.parse(readFileSync(here(`../examples/Project.${name}.json`), "utf8"));
  assert.ok(typeof project === "object" && project !== null && "world" in project, `${name}: a Project has a world`);
  return project;
};

const badgeSchema: { enum: Badge[] } = JSON.parse(readFileSync(here("../Badge.schema.json"), "utf8"));
const unitSchema: { enum: Unit[] } = JSON.parse(readFileSync(here("../Unit.schema.json"), "utf8"));
const badges = new Set<string>(badgeSchema.enum);
const units = new Set<string>(unitSchema.enum);

/** Every Quantity-shaped object (value, unit, badge, source) anywhere in the tree. */
function* quantities(node: unknown): Generator<Quantity> {
  if (Array.isArray(node)) {
    for (const v of node) yield* quantities(v);
  } else if (typeof node === "object" && node !== null) {
    // Shape found by walking arbitrary JSON, so it is unknowable to the compiler; the keys were just checked.
    if ("value" in node && "unit" in node && "badge" in node) yield node as Quantity;
    for (const v of Object.values(node)) yield* quantities(v);
  }
}

test("the empty project reads: a world and nothing else", () => {
  const p = readProject("empty");
  assert.equal(p.world.planet, "earth");
  assert.deepEqual(p.design?.instances ?? [], []);
  assert.deepEqual(p.design?.actuators ?? [], []);
  assert.deepEqual(p.world.terrain_props ?? [], []);
  assert.deepEqual(p.assumptions?.assumptions ?? [], []);
});

test("the four-wheel car reads: four wheels, two motors on hinges", () => {
  const p = readProject("four-wheel-car");
  const instances = p.design?.instances ?? [];
  assert.equal(instances.filter((i) => i.part === "wheel").length, 4);
  const motors: Actuator[] = (p.design?.actuators ?? []).filter((a) => a.kind === "motor");
  assert.equal(motors.length, 2);
  const hinges = new Set((p.design?.joints ?? []).filter((j) => j.kind === "hinge").map((j) => j.id));
  for (const m of motors) assert.ok(m.joint != null && hinges.has(m.joint), `${m.id} drives a hinge`);
  const [ramp] = p.world.terrain_props ?? [];
  assert.equal(ramp?.kind, "ramp");
  if (ramp?.kind === "ramp") assert.equal(ramp.incline.unit, "rad"); // narrowed by the `kind` tag
});

test("the rocket-car skeleton reads: a scheduled thruster that drives no joint", () => {
  const p = readProject("rocket-car-skeleton");
  const thrusters = (p.design?.actuators ?? []).filter((a) => a.kind === "thruster");
  assert.equal(thrusters.length, 1);
  const [thruster] = thrusters;
  assert.ok(thruster && (thruster.joint ?? null) === null);
  const entries = (p.design?.schedule?.entries ?? []).filter((e) => e.actuator === thruster.id);
  assert.ok(entries.length >= 1);
  for (const e of entries) assert.ok(e.command >= 0 && e.command <= 1 && e.start < e.end);
  assert.equal(p.world.planet, "moon");
});

test("every number in the examples has a badge from the closed vocabulary and a unit from the closed unit set", () => {
  for (const name of ["empty", "four-wheel-car", "rocket-car-skeleton"]) {
    const found = [...quantities(readProject(name))];
    for (const q of found) {
      assert.ok(badges.has(q.badge), `${name}: badge ${q.badge}`);
      assert.ok(units.has(q.unit), `${name}: unit ${q.unit}`);
      assert.ok(Number.isFinite(q.value), `${name}: finite value`);
      assert.ok(q.source.ref.length > 0, `${name}: source.ref`);
    }
    if (name !== "empty") assert.ok(found.length > 0, `${name} carries numbers`);
  }
});

test("a fixture carries no real-performance claim: no cite and no sim badge", () => {
  for (const name of ["four-wheel-car", "rocket-car-skeleton"]) {
    for (const q of quantities(readProject(name))) {
      assert.ok(q.badge === "declared" || q.badge === "default", `${name}: ${q.badge}`);
    }
  }
});

test("Project type: world is required, design and assumptions are optional", () => {
  const minimal: Project = { world: { planet: "earth" } };
  assert.equal(minimal.world.planet, "earth");
  // @ts-expect-error a Project needs a world
  const noWorld: Project = {};
  // @ts-expect-error an actuator kind is "motor" or "thruster", not "engine"
  const badKind: Actuator = { id: "t", kind: "engine", instance: "i" };
  void [noWorld, badKind];
});
