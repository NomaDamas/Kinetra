// Imported first by every *.browser.ts: a local browser run must come through the resource guard (P0-09), same rule as
// capture.ts / webgl-check.ts (CI=true or KINETRA_GUARD_PASSED=1). Throwing at import stops the file before any browser starts.
import { guardProblem } from "../capture.ts";

const problem = guardProblem();
if (problem) throw new Error(`browser tests refused: ${problem}`);
