// B-01c: the official validator on the committed fixtures, offline (no browser).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { FIXTURES, passes, validateBytes, validateDir } from "../validate.ts";

test("every committed part fixture passes the Khronos validator with no errors and no warnings", async () => {
  const reports = await validateDir(FIXTURES);
  assert.deepEqual(
    reports.map((r) => r.file),
    [
      "ballast-weight-declared-mass.glb",
      "battery-18650-declared-mass.glb",
      "battery-pack-4s-declared-mass.glb",
      "beam-al6061.glb",
      "drive-shaft-steel.glb",
      "motor-37d-12v-50-1-declared-mass.glb",
      "mounting-plate-al6061.glb",
      "payload-declared-mass.glb",
      "payload-mount-al6061.glb",
      "plate-al6061.glb",
      "reflectance-ior.glb",
      "sensor-mast-user-material.glb",
      "shell-al6061.glb",
      "tank-al6061.glb",
      "thruster-vacco-48003040-steel.glb",
      "wheel-pom.glb",
    ],
  );
  for (const r of reports) assert.ok(passes(r), `${r.file}: ${JSON.stringify(r.messages)}`);
});

test("the ior fixture declares KHR_materials_ior and the validator accepts it", async () => {
  const r = (await validateDir(FIXTURES)).find((x) => x.file === "reflectance-ior.glb");
  assert.ok(r);
  assert.deepEqual(r.extensionsUsed, ["KHR_materials_ior"]);
});

test("the validator rejects a damaged fixture (the check can fail)", async () => {
  const bytes = new Uint8Array(readFileSync(join(FIXTURES, "mounting-plate-al6061.glb")));
  const jsonLength = new DataView(bytes.buffer, bytes.byteOffset).getUint32(12, true);
  const broken = bytes.slice();
  const text = new TextDecoder().decode(broken.subarray(20, 20 + jsonLength));
  // point a primitive at an accessor that does not exist
  const damaged = text.replace('"indices":2', '"indices":9');
  assert.notEqual(damaged, text, "the fixture JSON must contain an indices reference to damage");
  broken.set(new TextEncoder().encode(damaged), 20);
  const r = await validateBytes("damaged.glb", broken);
  assert.ok(r.errors > 0 && !passes(r));
});
