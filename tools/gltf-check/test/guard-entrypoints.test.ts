// Offline: the entry points of this tool that start a browser refuse to run outside the resource guard.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const bare = () => {
  const env = { ...process.env };
  delete env.CI;
  delete env.KINETRA_GUARD_PASSED;
  delete env.NODE_TEST_CONTEXT; // set by the outer `node --test`: a nested `--test` would otherwise run in child mode and exit 0
  return env;
};
const run = (args: string[]) => spawnSync(process.execPath, args, { cwd: ROOT, env: bare(), encoding: "utf8", timeout: 30_000 });

test("capture.ts exits 3 with the guard message outside the guard", () => {
  const r = run(["capture.ts"]);
  assert.equal(r.status, 3, r.stderr);
  assert.match(r.stderr, /resource guard/);
});

test("skeleton.ts exits 3 with the guard message outside the guard", () => {
  const r = run(["skeleton.ts"]);
  assert.equal(r.status, 3, r.stderr);
  assert.match(r.stderr, /resource guard/);
});

test("every test/*.browser.ts refuses to run outside the guard and starts no browser", () => {
  const files = readdirSync(join(ROOT, "test")).filter((f) => f.endsWith(".browser.ts"));
  assert.ok(files.length > 0);
  for (const f of files) {
    const r = run(["--test", join("test", f)]);
    assert.notEqual(r.status, 0, `${f} ran outside the guard`);
    assert.match(r.stdout + r.stderr, /resource guard/, f);
    assert.doesNotMatch(r.stdout, /^ok \d+ - /m, `${f} ran a test`);
  }
});
