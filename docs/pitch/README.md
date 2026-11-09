# Kinetra pitch + scripted "live" demo

Honest by construction: the demo plays **recorded, seeded, reproducible runs** (tag stays on screen), never live compute.
Every spoken/shown number is read from the bundle JSON or `docs/judgment-spec.md` §D by `tools/film/build_script.py`.

## Pipeline
```bash
python3 tools/film/build_script.py                 # bundle -> docs/pitch/script.json (KO+EN lines, UI actions)
python3 tools/film/build_audio.py [ko|en]          # macOS `say` (Yuna / Samantha) -> apps/web/public/present/timeline.<lang>.json + narration.<lang>.m4a (cached in out/film/cache)
cd apps/web && pnpm exec vite build -c vite.present.config.ts   # presenter -> out/film/site (separate entry present.html; App.tsx untouched)
tools/film/.venv/bin/python tools/film/record.py ko   # Playwright + system Chrome, records video, writes out/film/sync_log.ko.json
```
Setup of the recorder venv: `cd tools/film && uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python playwright`.
Re-run `build_script.py` + `build_audio.py` after any bundle change; actions find variants by value (read from the bundle), never by index.

## Present live from the same deck
`cd apps/web && pnpm dev` then open `http://localhost:5173/present.html?lang=ko` (or `lang=en`). Space = play/pause (audio drives the clock),
←/→ = previous/next scene, R = restart. Slides cover the app; app scenes drive the real UI (chip click, slider tick, Apply fix, replay, Autoresearch tab).
Film mode (`?film=1`) uses a wall clock instead of audio and hides the HUD.

## Honesty checklist
- "recorded run, seeded & reproducible" tag visible on every frame; narration says "recorded, seeded, reproducible run" in demo scenes.
- Cost figures only from §D `sourced` rows, with source + caveat on slide; rocket hot-fire cost: no number shown.
- NOT_FOUND is always "weak evidence, not proof"; the fix is shown with its re-simulated p and CI (fragile if low).
- Autoresearch: "synthetic data, sim-to-real not validated"; toy 10 kg article.
- Business model flagged UNVALIDATED; no customers, revenue or traction claimed. Drift/Luminary lines are verbatim from the brief.
- Humanoid scene is generated only if `public/demo/{humanoid,g1_jump}/scenario.json` exists at script-build time (`meta.humanoid_included`).

## Speaker notes + likely questions
| Slide/scene | Say | Q → honest answer |
|---|---|---|
| Problem | Sourced rates only; hot-fire has no source. | "Is $1,000/h real?" → NASA educational slide, old, facility rate only. |
| Insight | Judge=MuJoCo, actor=Three.js. | "Why not an LLM?" → numbers must come from tools; LLM never produces a verdict. |
| Demo 1 roadster | Weak-evidence wording; fix is optimizer output, re-simulated. | "Is the sim live?" → No: recorded seeded runs; the local engine API (localhost:8000) can run it live. "How is this different from asking Claude Code for a MuJoCo script?" → we fix templates, assumptions panel with sources, MC with CI, verdict-wording rules and a necessary-condition screen; one-off scripts have none of that guarantee, but a good engineer could reproduce parts. |
| Demo 2 humanoid | Same rules. | "Does the G1 really jump this?" → simplified model, needs validation. |
| Autoresearch | Ledger with gates; synthetic. | "Does it work on real hardware?" → unknown; not validated. |
| Asymmetry | found strong / violated strong / not found weak. | "Why trust 'impossible'?" → only for necessary conditions at the favorable end of assumptions. |
| Differentiation | verbatim lines. | "Zoo?" → different layer (CAD); we make no comparison claim. |
| Business | Hypothesis. | "Who pays?" → unvalidated; interviews are the next step. |
| Roadmap / Ask | Real data, templates, first users. | "Traction?" → none yet. |
