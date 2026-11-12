// B-03 epic evidence: the drive car (wheels, motors, thruster, battery, tank, spring-dampers) drawn from one glb per
// instance placed by its pose, with a side table of the parts list and each drive part's key specs, badges and sources.
//
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/gltf-check capture:drive-car [outDir]
//
// Inputs are the committed files written by `uv run python packages/engine/tests/drive_car_sample.py`:
// `packages/engine/tests/fixtures/drive-car/{manifest.json,<instance>.glb}` (`test_drive_parts.py` checks they are current
// and that the manifest's specs are the part definitions'). The run asserts: every instance of the manifest is drawn once
// (same id set) and sits at the manifest's pose for its id (Project frame -> three.js: (x, y, z) -> (x, z, -y);
// `assembly.ts`); nothing is below the ground and the car stands on it; the parts
// list covers every instance; every spec row shows the manifest's value, unit, badge and source; the canvas holds drawn
// pixels and nothing is cut off. It writes `drive-car.png` (canvas and table) and `drive-car-result.json` to outDir
// (default out/gltf-check). Exit code: 0 pass, 1 failed, 3 outside the resource guard.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import type { Browser } from "playwright-core";
import { PNG } from "pngjs";
import { placementProblems } from "./assembly.ts";
import type { PlacedInstance } from "./assembly.ts";
import { DEFAULT_OUT, drawnPixels, guardProblem, serve } from "./capture.ts";
import { REPO_ROOT } from "./validate.ts";

export const DRIVE_CAR = join(REPO_ROOT, "packages", "engine", "tests", "fixtures", "drive-car");
const EXPECTED_INSTANCES = 14;
const ROLES = ["wheel", "motor", "thruster", "battery", "tank", "spring_damper"];
/** Tessellated wheels: the lowest drawn vertex may sit this far above the ground the tire touches. */
const GROUND_TOLERANCE_M = 1e-3;

export interface DriveCarManifest {
  instances: { id: string; part: string; part_name: string; role: string | null; glb: string; pose: { position: { x: number; y: number; z: number } } }[];
  specs: { part: string; part_name: string; name: string; value: number; unit: string; badge: string; badge_label: string; source_ref: string }[];
}

export interface DriveCarResult {
  instances: PlacedInstance[];
  part_rows: number;
  part_instances: number;
  specs: { part_name: string; name: string; value: number; value_text: string; badge: string; badge_text: string; source_title: string; source_text: string }[];
  scene_box_min_yup: number[];
  scene_box_max_yup: number[];
  max_ndc: number;
  camera_distance_m: number;
  gl: string;
}

/** Six significant digits, no trailing zeros: how the page prints a value (page/drive-car.js `fmt`). */
export function fmt(v: number): string {
  return String(Number(v.toPrecision(6)));
}

/** Everything the evidence claims, as a list of problems (empty = pass). Pure, so `test/drive-car.test.ts` runs it offline. */
export function problems(r: DriveCarResult, drawn: number, m: DriveCarManifest): string[] {
  const out: string[] = [];
  if (m.instances.length !== EXPECTED_INSTANCES) out.push(`the manifest has ${m.instances.length} instances, expected ${EXPECTED_INSTANCES}`);
  for (const role of ROLES) if (!m.instances.some((i) => i.role === role)) out.push(`no ${role} in the car`);
  out.push(...placementProblems(r.instances, m.instances));
  if (r.scene_box_min_yup[1]! < -1e-6) out.push(`part below the ground: min height ${r.scene_box_min_yup[1]}`);
  else if (r.scene_box_min_yup[1]! > GROUND_TOLERANCE_M) out.push(`the car does not stand on the ground: min height ${r.scene_box_min_yup[1]}`);
  if (r.part_instances !== m.instances.length) out.push(`the parts list covers ${r.part_instances} instances of ${m.instances.length}`);
  if (r.part_rows !== new Set(m.instances.map((i) => i.part)).size) out.push(`the parts list has ${r.part_rows} rows`);
  if (r.specs.length !== m.specs.length) out.push(`the table has ${r.specs.length} spec rows, the manifest ${m.specs.length}`);
  m.specs.forEach((s, k) => {
    const row = r.specs[k];
    if (!row) return;
    const at = `spec ${s.part}/${s.name}`;
    if (row.part_name !== s.part_name || row.name !== s.name) out.push(`${at}: the row is ${row.part_name}/${row.name}`);
    if (row.value !== s.value) out.push(`${at}: value ${row.value} is not ${s.value}`);
    if (row.value_text !== `${fmt(s.value)} ${s.unit}`) out.push(`${at}: shows "${row.value_text}", not "${fmt(s.value)} ${s.unit}"`);
    if (row.badge !== s.badge || row.badge_text !== s.badge_label) out.push(`${at}: badge ${row.badge} "${row.badge_text}" is not ${s.badge} "${s.badge_label}"`);
    if (row.source_title !== s.source_ref) out.push(`${at}: the source is not the part definition's`);
    if (!row.source_text.startsWith(s.source_ref.slice(0, 40))) out.push(`${at}: the shown source does not start with the part definition's`);
  });
  if (!(drawn > 10000)) out.push(`only ${drawn} pixels drawn`);
  if (!(r.max_ndc < 1)) out.push(`the box corners reach |NDC| ${r.max_ndc}: a part is cut off`);
  return out;
}

export function readManifest(): DriveCarManifest {
  return JSON.parse(readFileSync(join(DRIVE_CAR, "manifest.json"), "utf8")) as DriveCarManifest;
}

export async function runDriveCar(outDir = DEFAULT_OUT): Promise<{ page: DriveCarResult; drawn: number; png: string; problems: string[] }> {
  mkdirSync(outDir, { recursive: true });
  const manifest = readManifest();
  const srv = await serve([["/drive-car/", DRIVE_CAR]]);
  let browser: Browser | undefined;
  try {
    browser = await chromium.launch({ args: [] });
    const page = await browser.newPage({ viewport: { width: 1680, height: 1000 } });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${srv.url}/page/drive-car.html`);
    await page.waitForFunction("window.__DRIVE_CAR_RESULT || window.__DRIVE_CAR_ERROR", undefined, { timeout: 30_000 });
    const failure = await page.evaluate("window.__DRIVE_CAR_ERROR");
    if (failure || errors.length) throw new Error(`page failed: ${failure ?? errors.join("; ")}`);
    const result = (await page.evaluate("window.__DRIVE_CAR_RESULT")) as DriveCarResult;
    const file = join(outDir, "drive-car.png");
    writeFileSync(file, await page.screenshot({ fullPage: true }));
    const drawn = drawnPixels(PNG.sync.read(await page.locator("#c").screenshot()));
    const found = problems(result, drawn, manifest);
    writeFileSync(join(outDir, "drive-car-result.json"), JSON.stringify({ ...result, drawn_pixels: drawn, problems: found }, null, 2));
    return { page: result, drawn, png: file, problems: found };
  } finally {
    await browser?.close();
    srv.close();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const problem = guardProblem();
  if (problem) {
    console.error(problem);
    process.exit(3);
  }
  const { page, drawn, png, problems: found } = await runDriveCar(process.argv[2] ? resolve(process.argv[2]) : DEFAULT_OUT);
  console.log(`wrote ${png}; drawn pixels ${drawn}; ${page.instances.length} instances; ${page.specs.length} spec rows; GL ${page.gl}`);
  for (const s of page.specs) console.log(`${s.part_name} ${s.name}: ${s.value_text} [${s.badge_text}] ${s.source_text.slice(0, 60)}`);
  for (const p of found) console.error(`PROBLEM: ${p}`);
  process.exit(found.length === 0 ? 0 : 1);
}
