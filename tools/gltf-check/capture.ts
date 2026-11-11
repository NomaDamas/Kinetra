// B-01c evidence: the committed part fixtures loaded by three.js's GLTFLoader in headless Chromium, drawn, screenshotted.
//
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/gltf-check capture [outDir]
//
// A local static server (127.0.0.1, random port) serves the fixtures, the page and three.js from node_modules; nothing
// leaves the machine. The run asserts what the loader made of the material slot (colour is linear, metalness,
// roughness) and that the canvas holds drawn pixels, then writes `parts-gltf.png` and `result.json` to outDir
// (default out/gltf-check). Exit code: 0 pass, 1 failed, 3 refused to start a browser outside the resource guard.
import { createServer } from "node:http";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import type { Browser } from "playwright-core";
import { PNG } from "pngjs";
import { FIXTURES, REPO_ROOT } from "./validate.ts";

const HERE = fileURLToPath(new URL(".", import.meta.url));
export const FILES = ["mounting-plate-al6061", "drive-shaft-steel", "sensor-mast-user-material", "reflectance-ior"];
export const DEFAULT_OUT = join(REPO_ROOT, "out", "gltf-check");
const BACKGROUND = [0x14, 0x18, 0x1f];
const TYPES: Record<string, string> = { ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".glb": "model/gltf-binary" };

export function guardProblem(env: NodeJS.ProcessEnv = process.env): string | null {
  if (env.CI === "true" || env.KINETRA_GUARD_PASSED === "1") return null;
  return "a local browser run must start through the resource guard:\n  uv run python tools/dev/resource_guard.py --profile heavy -- <this command>";
}

/** Linear value of an sRGB component in [0, 1] (IEC 61966-2-1), the expectation the page's colours are compared with. */
export function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** Count of pixels that differ from the page background by more than 6 per channel. */
export function drawnPixels(png: PNG): number {
  let n = 0;
  for (let i = 0; i < png.data.length; i += 4) {
    if ([0, 1, 2].some((k) => Math.abs(png.data[i + k]! - BACKGROUND[k]!) > 6)) n++;
  }
  return n;
}

function serve(): Promise<{ url: string; close: () => void }> {
  const roots: [string, string][] = [
    ["/fixtures/", FIXTURES],
    ["/page/", join(HERE, "page")],
    ["/node_modules/three/", resolve(HERE, "node_modules", "three")],
  ];
  const server = createServer((req, res) => {
    const path = decodeURIComponent((req.url ?? "/").split("?")[0]!);
    const hit = roots.find(([prefix]) => path.startsWith(prefix));
    const file = hit ? resolve(hit[1], path.slice(hit[0].length)) : null;
    if (!hit || !file || !(file === hit[1] || file.startsWith(hit[1] + sep)) || !existsSync(file) || !statSync(file).isFile()) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" }).end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => {
    const addr = server.address() as { port: number };
    ok({ url: `http://127.0.0.1:${addr.port}`, close: () => server.close() });
  }));
}

export interface PageResult {
  results: { name: string; materials: number; color_linear: number[]; metalness: number; roughness: number; ior: number | null; size_m: number[]; voids: number }[];
  /** Voids the files list but do not cut (`extras.kinetra.voids`): the evidence page outlines them and says so. */
  undrawn_voids: number;
  /** Largest |x| or |y| of the bounding-box corners in normalised device coordinates; under 1 means nothing is cut off. */
  max_ndc: number;
  camera_distance_m: number;
  gl: string;
}

export async function run(outDir = DEFAULT_OUT): Promise<{ page: PageResult; drawn: number; png: string }> {
  mkdirSync(outDir, { recursive: true });
  const srv = await serve();
  let browser: Browser | undefined;
  try {
    browser = await chromium.launch({ args: [] }); // inside the try: a failed launch still closes the server
    const page = await browser.newPage({ viewport: { width: 1280, height: 480 } });
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    await page.goto(`${srv.url}/page/index.html?files=${FILES.join(",")}`);
    await page.waitForFunction("window.__GLTF_RESULT || window.__GLTF_ERROR", undefined, { timeout: 30_000 });
    const failure = await page.evaluate("window.__GLTF_ERROR");
    if (failure || errors.length) throw new Error(`page failed: ${failure ?? errors.join("; ")}`);
    const result = (await page.evaluate("window.__GLTF_RESULT")) as PageResult;
    const file = join(outDir, "parts-gltf.png");
    const buf = await page.locator("#c").screenshot();
    writeFileSync(file, buf);
    const drawn = drawnPixels(PNG.sync.read(buf));
    writeFileSync(join(outDir, "result.json"), JSON.stringify({ ...result, drawn_pixels: drawn }, null, 2));
    return { page: result, drawn, png: file };
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
  const { page, drawn, png } = await run(process.argv[2] ? resolve(process.argv[2]) : DEFAULT_OUT);
  console.log(`wrote ${png}; drawn pixels ${drawn}; max |NDC| of the box corners ${page.max_ndc.toFixed(3)}; undrawn voids ${page.undrawn_voids}; GL ${page.gl}`);
  for (const r of page.results) console.log(`${r.name}: colour(linear)=${r.color_linear.map((v) => v.toFixed(4))} metalness=${r.metalness} roughness=${r.roughness} ior=${r.ior} size=${r.size_m.map((v) => v.toFixed(3))} voids=${r.voids}`);
  process.exit(drawn > 10000 && page.max_ndc < 1 ? 0 : 1);
}
