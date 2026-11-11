// Browser test (run through the resource guard): the drive car's glb files load and sit at their poses, and the side
// table shows each drive part's key specs with the part definitions' values, badges and sources.
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { guardProblem } from "../capture.ts";
import { runDriveCar } from "../drive-car.ts";

const problem = guardProblem();
if (problem) throw new Error(problem);

test("the drive car is drawn from one glb per instance placed by pose, beside its parts list and key specs with sources", async () => {
  const { page, drawn, problems } = await runDriveCar(mkdtempSync(join(tmpdir(), "drive-car-")));
  assert.deepEqual(problems, []);
  assert.ok(drawn > 10000);
  assert.equal(page.instances.length, 14);
  assert.ok(page.specs.length >= 9);
});
