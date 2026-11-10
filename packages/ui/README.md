# @kinetra/ui

Design-system tokens and React components, taken from the approved Claude Design export `design/exports/design-system/` (founder approval: #33, 2026-11-10). Screens are out of scope (D0-03, D1).

| Path | What |
|---|---|
| `tokens/tokens.css`, `tokens/tokens.ts` | Generated from `design/exports/design-system/tokens.json` by `scripts/build-tokens.mjs`. Checked in, deterministic (same input bytes, same output bytes). `tokens.css` declares the same `--kin-*` variables as the export's `tokens.css`, plus its focus ring and reduced-motion rules |
| `src/components.css` | Component styles. Reads tokens only; no colour literals |
| `src/ValueBadge.tsx` | `ValueBadge`, five kinds: `sim`, `cite`, `default`, `declared`, `estimate` (+ `modifier`, + `stale` for `sim`). Always a focusable button, never disabled |
| `src/EvidenceLevel.tsx` | `EvidenceLevel`: `L0`, `L1` (+`narrow`), `L2` (`FEASIBLE_FOUND`, `INFEASIBLE_NECESSARY_CONDITION`, `NOT_FOUND_IN_BUDGET` = weak evidence), `L3` (0 measurements: always shown), `none` (`invalid`, `out-of-model`). The colour is the evidence strength, never the verdict (brief 5.2) |
| `scripts/build-preview.mjs`, `preview/index.html` | Static page with every `ValueBadge` / `EvidenceLevel` variant (react-dom/server over the built `dist/`, tokens.css, components.css). Screenshot: `design/exports/_impl/d0-02d/preview.png`, next to the approved boards' render `approved-boards.png` |
| `test/` | vitest. Snapshots plus checks against the approved boards (`source/ValueBadges.dc.html`, `source/Evidence.dc.html`): glyph paths, strength bars, colours, border shape, sizes |

```bash
pnpm --filter ui tokens        # regenerate tokens/ after the export's tokens.json changes
pnpm --filter ui lint          # tsc --noEmit + tokens are up to date (--check)
pnpm --filter ui build         # tokens + tsc -> dist/
pnpm --filter ui preview       # after build: regenerate preview/index.html
pnpm --filter ui test          # vitest (snapshots in test/__snapshots__; review the diff before `vitest -u`)
```

Use: `import "@kinetra/ui/tokens.css"; import "@kinetra/ui/components.css"; import { ValueBadge, EvidenceLevel } from "@kinetra/ui";`

## `/design-sync` round trip

Not done yet. It needs the interactive `claude` and a claude.ai login, so it is run from a PTY (`docs/decisions/design-pty.md`) and recorded in #34. After it runs, the repository tokens and the Claude Design project should show no difference; record the result there.
