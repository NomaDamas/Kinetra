// Offline tests of the skeleton evidence checks (no browser).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SKELETON, problems } from "../skeleton.ts";
import { passes, validateDir } from "../validate.ts";
import type { SkeletonResult } from "../skeleton.ts";

const manifest = JSON.parse(readFileSync(join(SKELETON, "manifest.json"), "utf8")) as {
  instances: { id: string; mass_kg: number; pose: { position: { x: number; y: number; z: number } } }[];
  total_kg: number;
};
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
  assert.deepEqual(problems(good(), 50000, masses, manifest.total_kg), []);
});

test("the committed manifest total is the sum of the part masses written in it", () => {
  assert.ok(Math.abs(masses.reduce((s, m) => s + m, 0) - manifest.total_kg) < 1e-12);
  assert.ok(Math.abs(manifest.total_kg - 9.6863928) < 1e-12);
});

test("wrong sum, wrong caption, misplaced part, buried part, cut-off view and empty canvas are each a problem", () => {
  const r = good();
  assert.match(problems({ ...r, page_sum_kg: r.page_sum_kg + 0.01 }, 50000, masses, manifest.total_kg).join(), /differs from the engine total/);
  assert.match(problems({ ...r, caption_total_text: "9.0000000 kg" }, 50000, masses, manifest.total_kg).join(), /caption total/);
  assert.match(problems({ ...r, caption_rows: 3 }, 50000, masses, manifest.total_kg).join(), /caption has 3/);
  const moved = { ...r, instances: r.instances.map((i, k) => (k === 2 ? { ...i, world_position_yup: [9, 9, 9] } : i)) };
  assert.match(problems(moved, 50000, masses, manifest.total_kg).join(), /not at pose/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, -0.1, 0] }, 50000, masses, manifest.total_kg).join(), /below the ground/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, 0.2, 0] }, 50000, masses, manifest.total_kg).join(), /does not rest on the ground/);
  assert.match(problems({ ...r, max_ndc: 1.2 }, 50000, masses, manifest.total_kg).join(), /cut off/);
  assert.match(problems(r, 100, masses, manifest.total_kg).join(), /pixels drawn/);
});

test("the glb of every skeleton instance passes the Khronos validator with no errors and no warnings", async () => {
  const reports = await validateDir(SKELETON);
  assert.deepEqual(reports.map((r) => r.file.replace(/\.glb$/, "")), manifest.instances.map((i) => i.id).sort());
  for (const r of reports) assert.ok(passes(r), `${r.file}: ${JSON.stringify(r.messages)}`);
});
