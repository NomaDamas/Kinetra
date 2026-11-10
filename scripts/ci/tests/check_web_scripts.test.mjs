import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { checkWorkspace } from "../check_web_scripts.mjs";

const SCRIPT = join(dirname(fileURLToPath(import.meta.url)), "..", "check_web_scripts.mjs");

function fixture(packages) {
  const root = mkdtempSync(join(tmpdir(), "kinetra-web-guard-"));
  writeFileSync(join(root, "pnpm-workspace.yaml"), "packages:\n  - apps/*\n  - packages/ui\n");
  for (const [dir, { pkg, files = [] }] of Object.entries(packages)) {
    mkdirSync(join(root, dir), { recursive: true });
    writeFileSync(join(root, dir, "package.json"), JSON.stringify(pkg));
    for (const f of files) {
      mkdirSync(dirname(join(root, dir, f)), { recursive: true });
      writeFileSync(join(root, dir, f), "export {};\n");
    }
  }
  return root;
}
const run = (root) => spawnSync(process.execPath, [SCRIPT, root], { encoding: "utf8" });
const ALL = { lint: "x", build: "x", test: "x" };

test("package with source but no scripts fails and is listed", () => {
  const root = fixture({ "apps/studio": { pkg: { name: "@k/studio" }, files: ["src/main.ts"] } });
  try {
    const r = run(root);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /@k\/studio .*missing lint, build, test/);
  } finally { rmSync(root, { recursive: true }); }
});

test("package with source missing only one script fails naming it", () => {
  const root = fixture({ "packages/ui": { pkg: { name: "@k/ui", scripts: { lint: "x", build: "x" } }, files: ["index.tsx"] } });
  try {
    const r = run(root);
    assert.equal(r.status, 1);
    assert.match(r.stderr, /@k\/ui .*missing test/);
  } finally { rmSync(root, { recursive: true }); }
});

test("empty-string script counts as missing", () => {
  const root = fixture({ "packages/ui": { pkg: { name: "@k/ui", scripts: { ...ALL, test: "  " } }, files: ["a.js"] } });
  try {
    assert.equal(run(root).status, 1);
  } finally { rmSync(root, { recursive: true }); }
});

test("package with source and all scripts passes", () => {
  const root = fixture({ "apps/studio": { pkg: { name: "@k/studio", scripts: ALL }, files: ["src/main.ts"] } });
  try {
    const r = run(root);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /OK   @k\/studio/);
    assert.match(r.stdout, /checked=1 skipped=0 violations=0/);
  } finally { rmSync(root, { recursive: true }); }
});

test("package without source is skipped with a reason, even with no scripts", () => {
  const root = fixture({ "packages/ui": { pkg: { name: "@k/ui" }, files: ["node_modules/dep/index.js", "dist/out.js", "README.md"] } });
  try {
    const r = run(root);
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /SKIP @k\/ui .*no source files/);
    assert.match(r.stdout, /checked=0 skipped=1 violations=0/);
    assert.match(r.stdout, /execute nothing/);
  } finally { rmSync(root, { recursive: true }); }
});

test("any file under src/ counts as source", () => {
  const root = fixture({ "apps/studio": { pkg: { name: "@k/studio" }, files: ["src/app.css"] } });
  try {
    assert.equal(run(root).status, 1);
  } finally { rmSync(root, { recursive: true }); }
});

test("checkWorkspace reports mixed results per package", () => {
  const root = fixture({
    "apps/studio": { pkg: { name: "@k/studio" }, files: ["src/main.ts"] },
    "packages/ui": { pkg: { name: "@k/ui" } },
  });
  try {
    const by = Object.fromEntries(checkWorkspace(root).map((r) => [r.name, r.status]));
    assert.deepEqual(by, { "@k/studio": "violation", "@k/ui": "skipped" });
  } finally { rmSync(root, { recursive: true }); }
});
