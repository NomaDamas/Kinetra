// A browser run is a heavy run (docs/process/dev-resources.md). Same rule as tools/screenshots/capture.ts: outside CI it must be started
// through the resource guard, which sets KINETRA_GUARD_PASSED=1 for the command it wraps:
//   uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/webxr xr
export function guardProblem(env = process.env) {
  if (env.CI === "true" || env.KINETRA_GUARD_PASSED === "1") return null;
  return "a local browser run must start through the resource guard:\n  uv run python tools/dev/resource_guard.py --profile heavy -- <this command>";
}
