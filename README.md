# Kinetra Studio

Build anything on an empty plain on Earth, Mars or the Moon with an agent, run it under that planet's physics, and export it as a Halo (replay video + play link) with an honest verdict.

This is a fresh start. The previous product (hackathon era) is preserved at the git tag [`legacy-v0`](https://github.com/NomaDamas/Kinetra/tree/legacy-v0).

## Plan

- [`docs/plan/studio-plan.md`](docs/plan/studio-plan.md): product, UX/UI, architecture, roadmap (source of truth)
- [`docs/plan/values.md`](docs/plan/values.md): core values V1–V5 and goals, quoted verbatim in every issue and PR
- [`docs/plan/issues.yaml`](docs/plan/issues.yaml): every epic, issue and sub-issue (seeded to GitHub Issues)
- [`docs/process/done-definition.md`](docs/process/done-definition.md), [`docs/process/review-rubric.md`](docs/process/review-rubric.md): what "100% done" means and the review → triage → merge loop

## Layout

| Path | Purpose |
|---|---|
| `apps/studio` | Studio web client |
| `packages/core` | Engine-independent Project model and command layer |
| `packages/engine` | Physics engine adapters |
| `packages/judge` | Necessary-condition screen, search, Monte-Carlo verdicts |
| `packages/ui` | Design-system tokens and components |
| `design/` | Claude Design briefs and approved exports |
| `data/`, `assets/` | Planet data, parts, licensed assets |
| `docs/` | Plan, process, decisions, architecture, research |
| `tools/` | Developer tooling |
| `scripts/gh/` | GitHub bootstrap scripts (`bootstrap.sh`: labels and milestones from `issues.yaml`, idempotent; `--dry-run` to preview) |

## Setup

```bash
uv sync
uv run pytest packages -q   # CI: .github/workflows/engine.yml (PRs and main)
pnpm install --frozen-lockfile
pnpm lint && pnpm build && pnpm test   # CI: .github/workflows/web.yml (PRs and main)
```
