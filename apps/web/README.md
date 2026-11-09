# Kinetra web demo

Static single-page app (Vite + React + TypeScript + @react-three/fiber + drei). **Judge = MuJoCo, Actor = Three.js**:
the page only replays precomputed engine output; it never simulates physics and never invents verdicts.

## Run

```bash
cd apps/web
pnpm install
pnpm dev            # http://localhost:5173
pnpm build          # tsc -b (strict) + vite build -> dist/
pnpm preview
```

The app reads the engine's demo bundle from `public/demo/` (contract: `docs/demo-bundle.md`):

```
public/demo/index.json
public/demo/<scenario>/scenario.json + traj_<k>.json
public/demo/autoresearch/{ledger,calibration,integration,excitation}.json
public/assets/g1/*.glb          # optional meshes; missing meshes fall back to primitives
```

Generate them with the engine scripts (`packages/engine/scripts/build_rocket_bundle.py`,
`build_humanoid_bundle.py`, `build_autoresearch_bundle.py`).

### Dev fixtures (not real bundles)

```bash
packages/engine/.venv/bin/python apps/web/scripts/make_fixtures.py   # writes apps/web/fixtures/demo
pnpm dev   # then open http://localhost:5173/?fixtures=1   (a red DEV FIXTURES badge is shown)
```
Fixtures are built from spike outputs, are served only by the dev server (`/fixtures/**`) and are never part of `pnpm build`.

### Optional local engine API

Free-text ideas that match no recorded scenario call `POST http://localhost:8000/run` (body `{idea, assumption_overrides}`,
response shaped like `scenario.json`; `variants[].trajectory` may be an inline Trajectory) if `GET /health` answers. Otherwise the page
says so honestly. Editing non-control assumptions only changes results when that engine is reachable; the slider on the control
assumption snaps across the precomputed variants.

## Deploy (Cloudflare Pages / Workers static assets)

```bash
pnpm build
pnpm dlx wrangler pages deploy dist --project-name kinetra-demo     # Pages
# or, with the included wrangler.jsonc (assets.directory = ./dist, SPA fallback):
pnpm dlx wrangler deploy
```
Make sure `public/demo/**` and `public/assets/**` were generated before building (they are copied into `dist/`). Nothing is deployed by this repo's scripts.

## Conventions
- MuJoCo Z-up, quaternions `[w,x,y,z]`. The scene root group is rotated -90 deg about X (MuJoCo (x,y,z) -> Three (x,z,-y)); quaternions are only reordered to xyzw.
- Mesh geoms: `Geom.mesh` is a path relative to `/assets/` (e.g. `g1/pelvis_link.glb`), vertices in the raw MuJoCo frame; colour comes from `Geom.rgba`; missing GLB -> primitive fallback.
- Thruster flames: bodies named `thr_<name>` (local +Z = force on the vehicle, flame points along -Z) with a series `thrust_<name>`.
- Contact/landing `events` with `pos` are drawn as markers once the playhead passes them.

## Known limits
- Agent steps are a recorded log replayed with cosmetic delays (wall_seconds are the real recorded values).
- The slider cannot show values between precomputed variants by design.
- Bundle size: the JS chunk is ~1.3 MB (three.js); fine for a static demo.
