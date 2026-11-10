# Kinetra Studio

Build anything on an empty plain on Earth, Mars or the Moon with an agent, run it under that planet's physics, and export it as a Halo (replay video + play link) with an honest verdict.

This is a fresh start. The previous product (hackathon era) is preserved at the git tag [`legacy-v0`](https://github.com/NomaDamas/Kinetra/tree/legacy-v0).

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

## Setup

```bash
uv sync
pnpm install --frozen-lockfile
```
