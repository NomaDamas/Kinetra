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
| `data/`, `assets/` | Planet data, parts, licensed assets. `assets/LEDGER.csv` is the provenance ledger: one row per asset or tool/runtime dependency (`kind` column), with license and credit text |
| `docs/` | Plan, process, decisions, architecture, research |
| `tools/` | Developer tooling (`tools/assets/credits.py`: generates `CREDITS.md` from `assets/LEDGER.csv`; `tools/rea/allowlist.txt`: the only targets REA may be pointed at, rules in [`docs/process/rea-policy.md`](docs/process/rea-policy.md), format check `uv run python tools/rea/check_allowlist.py`) |
| `scripts/` | `check_assets.py`: fails if an asset file (under `assets/` or `apps/**/public/`) has no ledger row, a ledger row has no file, or an unmodified asset's sha256 differs (`.github/workflows/assets.yml`) |
| `scripts/ci/` | CI guards (`check_web_scripts.mjs`; `check_pr_body.py`: fails a PR whose body lacks `## 대목표`, a verbatim `docs/plan/values.md` quote under `## 핵심 가치`, or exactly one `Closes #N` line, in template order) |
| `scripts/gh/` | GitHub bootstrap scripts (`bootstrap.sh`: labels and milestones from `issues.yaml`, idempotent; `--dry-run` to preview) |

## Setup

```bash
uv sync
uv run pytest packages -q   # CI: .github/workflows/engine.yml (PRs and main)
pnpm install --frozen-lockfile
pnpm lint && pnpm build && pnpm test   # CI: .github/workflows/web.yml (PRs and main)
```

## Asset and dependency ledger

Every asset and every tool/runtime dependency is a row in [`assets/LEDGER.csv`](assets/LEDGER.csv) (columns and the `asset` / `dependency` `kind` rule: `tools/assets/credits.py` docstring). [`CREDITS.md`](CREDITS.md) is generated from it and must not be edited by hand:

```bash
uv run python tools/assets/credits.py            # regenerate CREDITS.md
uv run python tools/assets/credits.py --check    # fail if CREDITS.md differs from the ledger
uv run python -m unittest discover -s tools/assets/tests -v
```

The ledger check (`.github/workflows/assets.yml`, PRs and main) ties the ledger to the files:

```bash
uv run python scripts/check_assets.py                      # exit 1 listing every violation
uv run python -m unittest discover -s scripts/tests -v
```

Every file under `assets/` and `apps/**/public/` needs a `kind=asset` row whose `경로` is that file, and every row's path must exist. For an asset recorded as unmodified (`변경 내역` starts with `없음`) the file's sha256 must equal `원본 해시`. For a modified asset `원본 해시` is the hash of the downloaded original, which the repository does not contain, so the hash is not compared (the script reports how many were skipped). `CREDITS.md` must equal the generated output. Symlinks are not allowed: any symlink (file, directory or broken) under `assets/` or `apps/**/public/` is a violation and is never followed, and every ledger path (asset or dependency) must stay inside the repository after symlinks are resolved. `node_modules/` is skipped only while searching `apps/` for `public` folders; inside `assets/` or a `public` folder it is counted like any other directory. A symlinked directory met while searching `apps/` (including `apps` itself) is a violation.

## PR body check

`.github/workflows/pr-body.yml` runs `scripts/ci/check_pr_body.py` on every PR open and body edit. The body must follow `.github/pull_request_template.md`: `## 대목표`, then `## 핵심 가치` with a verbatim quote (`> `) of one of V1–V5 from `docs/plan/values.md`, then exactly one line that is `Closes #N` (one leaf issue). `Refs #N` lines are allowed in addition but never replace `Closes`. Fenced code blocks (closed by the same char, at least as long, nothing after) and HTML comments (an unclosed `<!--` hides the rest) are not body text.

```bash
python3 scripts/ci/check_pr_body.py --body-file body.md   # exit 1 and the reasons on a violating body
python3 -m unittest discover -s scripts/ci/tests -p "test_check_pr_body.py" -v
```
