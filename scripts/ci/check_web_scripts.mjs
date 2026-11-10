#!/usr/bin/env node
// P0-04b guard: a pnpm workspace package that has source files must define
// `lint`, `build` and `test` scripts, so the web CI cannot silently stay empty.
// Usage: node scripts/ci/check_web_scripts.mjs [repoRoot]   (default: cwd)
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

export const REQUIRED_SCRIPTS = ["lint", "build", "test"];
const SOURCE_EXT = /\.(ts|tsx|js|jsx)$/;
const IGNORED_DIRS = new Set(["node_modules", "dist"]);

// pnpm-workspace.yaml: only the `packages:` list of `- pattern` lines is read.
export function readWorkspacePatterns(root) {
  const text = readFileSync(join(root, "pnpm-workspace.yaml"), "utf8");
  const patterns = [];
  let inPackages = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, "").trimEnd();
    if (!line.trim()) continue;
    if (/^packages\s*:/.test(line)) {
      inPackages = true;
      continue;
    }
    if (/^\S/.test(line)) inPackages = false;
    const m = inPackages && line.match(/^\s*-\s*['"]?([^'"]+?)['"]?\s*$/);
    if (m) patterns.push(m[1]);
  }
  return patterns;
}

// Supports `dir/*` and exact `dir/sub` patterns (what this repo uses).
export function expandPatterns(root, patterns) {
  const dirs = new Set();
  for (const p of patterns) {
    if (p.endsWith("/*")) {
      const base = join(root, p.slice(0, -2));
      if (!existsSync(base)) continue;
      for (const e of readdirSync(base, { withFileTypes: true })) {
        if (e.isDirectory() && !IGNORED_DIRS.has(e.name)) dirs.add(join(base, e.name));
      }
    } else if (p.includes("*")) {
      throw new Error(`unsupported workspace pattern: ${p}`);
    } else {
      dirs.add(join(root, p));
    }
  }
  return [...dirs]
    .filter((d) => existsSync(join(d, "package.json")))
    .sort();
}

export function findSourceFiles(dir) {
  const found = [];
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.isDirectory()) {
        if (!IGNORED_DIRS.has(e.name)) walk(join(d, e.name));
      } else if (SOURCE_EXT.test(e.name)) {
        found.push(join(d, e.name));
      }
    }
  };
  walk(dir);
  // `src/**` counts as source even for other file types.
  const src = join(dir, "src");
  if (existsSync(src) && statSync(src).isDirectory()) {
    const walkAll = (d) => {
      for (const e of readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory()) walkAll(join(d, e.name));
        else if (!found.includes(join(d, e.name))) found.push(join(d, e.name));
      }
    };
    walkAll(src);
  }
  return found;
}

export function checkWorkspace(root) {
  const results = [];
  for (const dir of expandPatterns(root, readWorkspacePatterns(root))) {
    const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
    const rel = relative(root, dir);
    const sources = findSourceFiles(dir);
    if (sources.length === 0) {
      results.push({ name: pkg.name, dir: rel, status: "skipped", reason: "no source files", missing: [] });
      continue;
    }
    const scripts = pkg.scripts ?? {};
    const missing = REQUIRED_SCRIPTS.filter((s) => typeof scripts[s] !== "string" || !scripts[s].trim());
    results.push({
      name: pkg.name,
      dir: rel,
      status: missing.length ? "violation" : "ok",
      reason: `${sources.length} source file(s)`,
      missing,
    });
  }
  return results;
}

export function main(root = process.cwd()) {
  const results = checkWorkspace(root);
  for (const r of results) {
    if (r.status === "skipped") console.log(`SKIP ${r.name} (${r.dir}): ${r.reason}; lint/build/test not required`);
    else if (r.status === "ok") console.log(`OK   ${r.name} (${r.dir}): ${r.reason}; has ${REQUIRED_SCRIPTS.join(", ")}`);
    else console.log(`FAIL ${r.name} (${r.dir}): ${r.reason}; missing scripts: ${r.missing.join(", ")}`);
  }
  const violators = results.filter((r) => r.status === "violation");
  const checked = results.filter((r) => r.status !== "skipped").length;
  console.log(`checked=${checked} skipped=${results.length - checked} violations=${violators.length}`);
  if (checked === 0) {
    console.log("NOTE: no workspace package has source files yet, so pnpm lint/build/test execute nothing.");
  }
  if (violators.length) {
    console.error(`Packages with source must define ${REQUIRED_SCRIPTS.join(", ")} scripts:`);
    for (const v of violators) console.error(`  ${v.name} (${v.dir}): missing ${v.missing.join(", ")}`);
    return 1;
  }
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv[2] ?? process.cwd()));
}
