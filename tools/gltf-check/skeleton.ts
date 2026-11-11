// B-02 epic evidence: the structural skeleton (beam, plate, shell, payload, mount) drawn from one glb per instance placed by
// its pose, with a caption of the per-part masses and the total.
//
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/gltf-check capture:skeleton [outDir]
//
// Inputs are the committed files written by `uv run python packages/engine/tests/skeleton_sample.py`:
// `packages/engine/tests/fixtures/skeleton/{manifest.json,<instance>.glb}` (`test_structural.py` checks they are current).
// The run asserts: every instance loaded and sits at its pose (Project frame -> three.js: (x, y, z) -> (x, z, -y)); nothing is
// below the ground; the page's own sum of the per-part masses equals the engine's total; the caption shows the total and one
// row per part; the canvas holds drawn pixels and nothing is cut off. It writes `skeleton.png` (canvas and caption) and
// `skeleton-result.json` to outDir (default out/gltf-check). Exit code: 0 pass, 1 failed, 3 outside the resource guard.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import type { Browser } from "playwright-core";
import { PNG } from "pngjs";
import { DEFAULT_OUT, drawnPixels, guardProblem, serve } from "./capture.ts";
import { REPO_ROOT } from "./validate.ts";

export const SKELETON = join(REPO_ROOT, "packages", "engine", "tests", "fixtures", "skeleton");
const EXPECTED_INSTANCES = 7;

export interface SkeletonResult {
  instances: { id: string; mass_kg: number; pose_project: number[]; world_position_yup: number[]; box_min_yup: number[]; box_max_yup: number[] }[];
  manifest_total_kg: number;
  page_sum_kg: number;
  caption_total_text: string;
  caption_rows: number;
  scene_box_min_yup: number[];
  scene_box_max_yup: number[];
  max_ndc: number;
  camera_distance_m: number;
  gl: string;
}

/** Everything the evidence claims, as a list of problems (empty = pass). Pure, so `test/skeleton.test.ts` runs it offline. */
export function problems(r: SkeletonResult, drawn: number, manifestMasses: number[], manifestTotal: number): string[] {
  const out: string[] = [];
  if (r.instances.length !== EXPECTED_INSTANCES) out.push(`${r.instances.length} instances placed, expected ${EXPECTED_INSTANCES}`);
  if (r.caption_rows !== r.instances.length) out.push(`caption has ${r.caption_rows} part rows for ${r.instances.length} instances`);
  for (const i of r.instances) {
    const [x, y, z] = i.pose_project as [number, number, number];
    const want = [x, z, -y];
    want.forEach((w, k) => { if (Math.abs(i.world_position_yup[k]! - w) > 1e-5) out.push(`${i.id}: placed at ${i.world_position_yup} not at pose ${want}`); });
    if (!(i.box_max_yup[0]! > i.box_min_yup[0]! && i.box_max_yup[1]! > i.box_min_yup[1]! && i.box_max_yup[2]! > i.box_min_yup[2]!)) out.push(`${i.id}: empty bounding box`);
  }
  if (r.scene_box_min_yup[1]! < -1e-6) out.push(`part below the ground: min height ${r.scene_box_min_yup[1]}`);
  if (Math.abs(r.scene_box_min_yup[1]!) > 1e-6) out.push(`the skeleton does not rest on the ground: min height ${r.scene_box_min_yup[1]}`);
  if (r.instances.some((i, k) => i.mass_kg !== manifestMasses[k])) out.push("page masses differ from the manifest");
  if (Math.abs(r.page_sum_kg - manifestTotal) > 1e-12) out.push(`page sum ${r.page_sum_kg} kg differs from the engine total ${manifestTotal} kg`);
  if (r.manifest_total_kg !== manifestTotal) out.push("the page read another total than the manifest");
  if (r.caption_total_text !== `${manifestTotal.toFixed(7)} kg`) out.push(`caption total "${r.caption_total_text}" is not ${manifestTotal.toFixed(7)} kg`);
  if (!(drawn > 10000)) out.push(`only ${drawn} pixels drawn`);
  if (!(r.max_ndc < 1)) out.push(`the box corners reach |NDC| ${r.max_ndc}: a part is cut off`);
  return out;
}

export async function runSkeleton(outDir = DEFAULT_OUT): Promise<{ page: SkeletonResult; drawn: number; png: string; problems: string[] }> {
  mkdirSync(outDir, { recursive: true });
  const manifest = JSON.parse(readFileSync(join(SKELETON, "manifest.json"), "utf8")) as { instances: { mass_kg: number }[]; total_kg: number };
  const srv = await serve([["/skeleton/", SKELETON]]);
  let browser: Browser | undefined;
  try {
    browser = await chromium.launch({ args: [] });
    const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${srv.url}/page/skeleton.html`);
    await page.waitForFunction("window.__SKELETON_RESULT || window.__SKELETON_ERROR", undefined, { timeout: 30_000 });
    const failure = await page.evaluate("window.__SKELETON_ERROR");
    if (failure || errors.length) throw new Error(`page failed: ${failure ?? errors.join("; ")}`);
    const result = (await page.evaluate("window.__SKELETON_RESULT")) as SkeletonResult;
    const file = join(outDir, "skeleton.png");
    writeFileSync(file, await page.screenshot({ fullPage: true }));
    const drawn = drawnPixels(PNG.sync.read(await page.locator("#c").screenshot()));
    const found = problems(result, drawn, manifest.instances.map((i) => i.mass_kg), manifest.total_kg);
    writeFileSync(join(outDir, "skeleton-result.json"), JSON.stringify({ ...result, drawn_pixels: drawn, problems: found }, null, 2));
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
  const { page, drawn, png, problems: found } = await runSkeleton(process.argv[2] ? resolve(process.argv[2]) : DEFAULT_OUT);
  console.log(`wrote ${png}; drawn pixels ${drawn}; total ${page.manifest_total_kg} kg = page sum ${page.page_sum_kg} kg; GL ${page.gl}`);
  for (const i of page.instances) console.log(`${i.id}: ${i.mass_kg} kg at pose ${i.pose_project.map((v) => v.toFixed(4))}`);
  for (const p of found) console.error(`PROBLEM: ${p}`);
  process.exit(found.length === 0 ? 0 : 1);
}
