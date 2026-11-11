// `pnpm --dir spikes/webxr xr`: run the scenario once, print the evidence JSON and one line per check, exit 1 if any check fails.
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/webxr xr [--out results/a0-02b-xr.json]
// Exit codes: 0 all checks pass, 1 a check failed or the run threw, 3 started outside the resource guard.
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { guardProblem } from "./guard.mjs";
import { runXr } from "./driver.mjs";

const problem = guardProblem();
if (problem) {
  console.error(problem);
  process.exit(3);
}
const i = process.argv.indexOf("--out");
const out = i > 0 ? resolve(process.argv[i + 1]) : null;
try {
  const { result, checks } = await runXr();
  const text = JSON.stringify({ result, checks }, null, 1) + "\n";
  if (out) writeFileSync(out, text); else process.stdout.write(text);
  let failed = 0;
  for (const [name, ok] of Object.entries(checks)) {
    console.error(`${ok ? "PASS" : "FAIL"} ${name}`);
    if (!ok) failed++;
  }
  process.exit(failed ? 1 : 0);
} catch (e) {
  console.error(e);
  process.exit(1);
}
