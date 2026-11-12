// Offline tests of the skeleton evidence checks (no browser).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SKELETON, problems } from "../skeleton.ts";
import { passes, validateDir } from "../validate.ts";
import type { SkeletonManifest, SkeletonResult } from "../skeleton.ts";

const manifest = JSON.parse(readFileSync(join(SKELETON, "manifest.json"), "utf8")) as SkeletonManifest;
const masses = manifest.instances.map((i) => i.mass_kg);

/** What a correct page reports for the committed manifest (positions are the pose turned into three.js's Y up). */
function good(): SkeletonResult {
  return {
    instances: manifest.instances.map((i) => {
      const { x, y, z } = i.pose.position;
      return { id: i.id, mass_kg: i.mass_kg, pose_project: [x, y, z], world_position_yup: [x, z, -y], box_min_yup: [0, 0, 0], box_max_yup: [1, 1, 1] };
    }),
    manifest_total_kg: manifest.total_kg,
    page_sum_kg: masses.reduce((s, m) => s + m, 0),
    caption_total_text: `${manifest.total_kg.toFixed(7)} kg`,
    caption_rows: masses.length,
    scene_box_min_yup: [-1, 0, -1],
    scene_box_max_yup: [1, 1, 1],
    max_ndc: 0.9,
    camera_distance_m: 2,
    gl: "test",
  };
}

test("a correct page report has no problems", () => {
  assert.deepEqual(problems(good(), 50000, manifest), []);
});

test("the committed manifest total is the sum of the part masses written in it", () => {
  assert.ok(Math.abs(masses.reduce((s, m) => s + m, 0) - manifest.total_kg) < 1e-12);
  assert.ok(Math.abs(manifest.total_kg - 9.6863928) < 1e-12);
});

test("wrong sum, wrong caption, misplaced part, buried part, cut-off view and empty canvas are each a problem", () => {
  const r = good();
  assert.match(problems({ ...r, page_sum_kg: r.page_sum_kg + 0.01 }, 50000, manifest).join(), /differs from the engine total/);
  assert.match(problems({ ...r, caption_total_text: "9.0000000 kg" }, 50000, manifest).join(), /caption total/);
  assert.match(problems({ ...r, caption_rows: 3 }, 50000, manifest).join(), /caption has 3/);
  const moved = { ...r, instances: r.instances.map((i, k) => (k === 2 ? { ...i, world_position_yup: [9, 9, 9] } : i)) };
  assert.match(problems(moved, 50000, manifest).join(), /not at the manifest pose/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, -0.1, 0] }, 50000, manifest).join(), /below the ground/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, 0.2, 0] }, 50000, manifest).join(), /does not rest on the ground/);
  assert.match(problems({ ...r, max_ndc: 1.2 }, 50000, manifest).join(), /cut off/);
  assert.match(problems(r, 100, manifest).join(), /pixels drawn/);
});

test("the placement is judged against the manifest pose by id, not the pose the page says it read", () => {
  const r = good();
  // the page claims another pose and draws the part there: consistent with itself, wrong against the engine's manifest
  const lied = { ...r, instances: r.instances.map((i, k) => (k === 1 ? { ...i, pose_project: [5, 6, 7], world_position_yup: [5, 7, -6] } : i)) };
  const found = problems(lied, 50000, manifest).join();
  assert.match(found, /the page read pose 5,6,7/);
  assert.match(found, /not at the manifest pose/);
  // the right poses in another order are fine: matching is by id
  assert.deepEqual(problems({ ...r, instances: [...r.instances].reverse() }, 50000, manifest), []);
  assert.match(problems({ ...r, instances: r.instances.slice(1) }, 50000, manifest).join(), /not drawn: keel-beam/);
  const extra = { ...r.instances[0]!, id: "ghost" };
  assert.match(problems({ ...r, instances: [...r.instances, extra] }, 50000, manifest).join(), /does not have: ghost/);
  assert.match(problems({ ...r, instances: [...r.instances, r.instances[0]!] }, 50000, manifest).join(), /more than once: keel-beam/);
});

test("the glb of every skeleton instance passes the Khronos validator with no errors and no warnings", async () => {
  const reports = await validateDir(SKELETON);
  assert.deepEqual(reports.map((r) => r.file.replace(/\.glb$/, "")), manifest.instances.map((i) => i.id).sort());
  for (const r of reports) assert.ok(passes(r), `${r.file}: ${JSON.stringify(r.messages)}`);
});
