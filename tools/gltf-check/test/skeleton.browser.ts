// Browser test (run through the resource guard): the skeleton's glb files load, sit at their poses, and the caption's total is the sum of its parts.
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { guardProblem } from "../capture.ts";
import { runSkeleton } from "../skeleton.ts";

const problem = guardProblem();
if (problem) throw new Error(problem);

test("the structural skeleton is drawn from one glb per instance placed by pose, and its caption total is the sum of the parts", async () => {
  const { page, drawn, problems } = await runSkeleton(mkdtempSync(join(tmpdir(), "skeleton-")));
  assert.deepEqual(problems, []);
  assert.ok(drawn > 10000);
  assert.equal(page.instances.length, 7);
  assert.ok(Math.abs(page.page_sum_kg - 9.6863928) < 1e-9, `page sum ${page.page_sum_kg}`);
});
