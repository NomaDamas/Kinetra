// Offline tests of the drive-car evidence checks (no browser).
import assert from "node:assert/strict";
import { test } from "node:test";
import { DRIVE_CAR, fmt, problems, readManifest } from "../drive-car.ts";
import { passes, validateDir } from "../validate.ts";
import type { DriveCarResult } from "../drive-car.ts";

const manifest = readManifest();

/** What a correct page reports for the committed manifest (positions are the pose turned into three.js's Y up). */
function good(): DriveCarResult {
  return {
    instances: manifest.instances.map((i) => {
      const { x, y, z } = i.pose.position;
      return { id: i.id, pose_project: [x, y, z], world_position_yup: [x, z, -y], box_min_yup: [0, 0, 0], box_max_yup: [1, 1, 1] };
    }),
    part_rows: new Set(manifest.instances.map((i) => i.part)).size,
    part_instances: manifest.instances.length,
    specs: manifest.specs.map((s) => ({
      part_name: s.part_name,
      name: s.name,
      value: s.value,
      value_text: `${fmt(s.value)} ${s.unit}`,
      badge: s.badge,
      badge_text: s.badge_label,
      source_title: s.source_ref,
      source_text: `${s.source_ref.slice(0, 110)}…`,
    })),
    scene_box_min_yup: [-1, 0.0002, -1],
    scene_box_max_yup: [1, 1, 1],
    max_ndc: 0.9,
    camera_distance_m: 2,
    gl: "test",
  };
}

const spec = (r: DriveCarResult, k: number, patch: Partial<DriveCarResult["specs"][number]>): DriveCarResult => ({
  ...r,
  specs: r.specs.map((s, i) => (i === k ? { ...s, ...patch } : s)),
});

test("a correct page report has no problems", () => {
  assert.deepEqual(problems(good(), 50000, manifest), []);
});

test("the page prints six significant digits", () => {
  assert.equal(fmt(2.0593964999999996), "2.0594");
  assert.equal(fmt(8.896443230521), "8.89644");
  assert.equal(fmt(168480), "168480");
  assert.equal(fmt(1), "1");
  assert.equal(fmt(14.4), "14.4");
});

test("the committed manifest is the car of the issue: every drive part and its key specs with sources", () => {
  const roles = manifest.instances.map((i) => i.role);
  assert.equal(roles.filter((r) => r === "wheel").length, 4);
  for (const r of ["motor", "thruster", "battery", "tank", "spring_damper"]) assert.ok(roles.includes(r), r);
  const names = manifest.specs.map((s) => `${s.part}/${s.name}`);
  for (const n of [
    "wheel/tread_friction_static",
    "motor-37d-12v-50-1/rated_voltage",
    "motor-37d-12v-50-1/stall_torque (torque_speed at 0 rad/s)",
    "thruster-vacco-48003040/rated_thrust",
    "battery-pack-4s/nominal_voltage",
    "battery-pack-4s/energy_capacity",
    "spring-damper-lee-lc032b08/stiffness",
    "spring-damper-lee-lc032b08/damping",
  ]) assert.ok(names.includes(n), n);
  for (const s of manifest.specs) assert.ok(s.source_ref.length > 0 && s.badge_label.length > 0, s.name);
});

test("a wrong value, unit, badge or source, a missing row, a misplaced or buried part, a cut-off view and an empty canvas are each a problem", () => {
  const r = good();
  assert.match(problems(spec(r, 2, { value: 11 }), 50000, manifest).join(), /value 11 is not 12/);
  assert.match(problems(spec(r, 2, { value_text: "12 kV" }), 50000, manifest).join(), /shows "12 kV"/);
  assert.match(problems(spec(r, 5, { badge: "cite", badge_text: "인용" }), 50000, manifest).join(), /badge cite/);
  assert.match(problems(spec(r, 0, { source_title: "made up" }), 50000, manifest).join(), /source is not the part definition's/);
  assert.match(problems(spec(r, 0, { source_text: "made up" }), 50000, manifest).join(), /shown source/);
  assert.match(problems({ ...r, specs: r.specs.slice(1) }, 50000, manifest).join(), /spec rows/);
  assert.match(problems({ ...r, part_instances: 13 }, 50000, manifest).join(), /covers 13 instances/);
  const moved = { ...r, instances: r.instances.map((i, k) => (k === 3 ? { ...i, world_position_yup: [9, 9, 9] } : i)) };
  assert.match(problems(moved, 50000, manifest).join(), /not at the manifest pose/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, -0.1, 0] }, 50000, manifest).join(), /below the ground/);
  assert.match(problems({ ...r, scene_box_min_yup: [0, 0.2, 0] }, 50000, manifest).join(), /does not stand on the ground/);
  assert.match(problems({ ...r, max_ndc: 1.2 }, 50000, manifest).join(), /cut off/);
  assert.match(problems(r, 100, manifest).join(), /pixels drawn/);
});

test("the placement is judged against the manifest pose by id, not the pose the page says it read", () => {
  const r = good();
  const lied = { ...r, instances: r.instances.map((i, k) => (k === 1 ? { ...i, pose_project: [5, 6, 7], world_position_yup: [5, 7, -6] } : i)) };
  const found = problems(lied, 50000, manifest).join();
  assert.match(found, /the page read pose 5,6,7/);
  assert.match(found, /not at the manifest pose/);
  assert.deepEqual(problems({ ...r, instances: [...r.instances].reverse() }, 50000, manifest), []);
  assert.match(problems({ ...r, instances: r.instances.slice(1) }, 50000, manifest).join(), /not drawn: chassis/);
  const extra = { ...r.instances[0]!, id: "ghost" };
  assert.match(problems({ ...r, instances: [...r.instances, extra] }, 50000, manifest).join(), /does not have: ghost/);
  assert.match(problems({ ...r, instances: [...r.instances, r.instances[0]!] }, 50000, manifest).join(), /more than once: chassis/);
});

test("the glb of every drive-car instance passes the Khronos validator with no errors and no warnings", async () => {
  const reports = await validateDir(DRIVE_CAR);
  assert.deepEqual(reports.map((r) => r.file.replace(/\.glb$/, "")), manifest.instances.map((i) => i.id).sort());
  for (const r of reports) assert.ok(passes(r), `${r.file}: ${JSON.stringify(r.messages)}`);
});
