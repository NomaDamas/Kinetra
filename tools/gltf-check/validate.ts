// B-01c: the official Khronos glTF validator (gltf-validator, Apache-2.0) on the committed part fixtures.
//
//   pnpm --filter @kinetra/gltf-check validate [dir]       (default: packages/engine/tests/fixtures/gltf)
//
// The fixtures are written by `uv run python packages/engine/tests/gltf_samples.py` and checked to be current by
// `uv run pytest packages/engine -k gltf`. A fixture passes with zero errors AND zero warnings (hints and infos are
// reported but do not fail). Exit code: 0 all pass, 1 at least one fails or no fixture was found.
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import validator from "gltf-validator";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const FIXTURES = join(REPO_ROOT, "packages", "engine", "tests", "fixtures", "gltf");

export interface Report {
  file: string;
  errors: number;
  warnings: number;
  infos: number;
  hints: number;
  messages: { code: string; message: string; severity: number; pointer?: string }[];
  version: string;
  triangles: number;
  extensionsUsed: string[];
}

export async function validateBytes(file: string, bytes: Uint8Array): Promise<Report> {
  const r = await validator.validateBytes(bytes, { uri: file, maxIssues: 50 });
  return {
    file,
    errors: r.issues.numErrors,
    warnings: r.issues.numWarnings,
    infos: r.issues.numInfos,
    hints: r.issues.numHints,
    messages: r.issues.messages,
    version: String(r.info.version),
    triangles: Number(r.info.totalTriangleCount ?? 0),
    extensionsUsed: r.info.extensionsUsed ?? [],
  };
}

export function passes(r: Report): boolean {
  return r.errors === 0 && r.warnings === 0 && r.version === "2.0";
}

export async function validateDir(dir: string): Promise<Report[]> {
  const files = readdirSync(dir).filter((f) => f.endsWith(".glb")).sort();
  const out: Report[] = [];
  for (const f of files) out.push(await validateBytes(f, new Uint8Array(readFileSync(join(dir, f)))));
  return out;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const reports = await validateDir(process.argv[2] ? resolve(process.argv[2]) : FIXTURES);
  for (const r of reports) {
    console.log(`${passes(r) ? "PASS" : "FAIL"} ${r.file}: glTF ${r.version}, ${r.triangles} triangles, errors=${r.errors} warnings=${r.warnings} infos=${r.infos} hints=${r.hints}`);
    for (const m of r.messages) console.log(`  [${m.severity}] ${m.code} ${m.pointer ?? ""} ${m.message}`);
  }
  process.exit(reports.length > 0 && reports.every(passes) ? 0 : 1);
}
