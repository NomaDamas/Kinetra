#!/usr/bin/env node
// D0-02d: static visual preview of every ValueBadge / EvidenceLevel variant -> packages/ui/preview/index.html.
// Uses the built components (run `pnpm build` first), tokens.css and components.css; react-dom/server renders the markup.
// Deterministic; no scripts, no network, no font download (fonts are named only, as in the tokens).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createElement as h, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { EvidenceLevel, L2_VERDICTS, VALUE_BADGE_KINDS, VALUE_BADGE_LABELS, ValueBadge } from "../dist/src/index.js";

const out = join(resolve(dirname(fileURLToPath(import.meta.url)), ".."), "preview", "index.html");
const html = (el) => renderToStaticMarkup(el);
const row = (label, ...items) =>
  `<div class="row"><span class="lbl">${label}</span>${items.join("")}</div>`;
const section = (id, title, ...rows) => `<section id="${id}"><h2>${title}</h2>${rows.join("")}</section>`;
const badges = (props = {}) => VALUE_BADGE_KINDS.map((kind) => html(h(ValueBadge, { kind, ...props })));

const valueBadges = section(
  "value-badges",
  "값 배지 5종 (ValueBadge)",
  row("다섯 가지", ...badges()),
  row("팝오버 열림 (aria-expanded)", ...badges({ "aria-expanded": "true" })),
  row(
    "수식어 · 덮어쓰기 · 오래됨",
    html(h(ValueBadge, { kind: "declared", modifier: "카탈로그 밖" })),
    html(h(ValueBadge, { kind: "sim", stale: true })),
  ),
  `<div class="row gray"><span class="lbl">흑백</span>${badges().join("")}</div>`,
);

const evidence = section(
  "evidence",
  "증거 4단계 (EvidenceLevel)",
  row("L0", html(h(EvidenceLevel, { level: "L0" }))),
  row("L1", html(h(EvidenceLevel, { level: "L1" })), html(h(EvidenceLevel, { level: "L1", narrow: true }))),
  ...L2_VERDICTS.map((verdict) => row(`L2 ${verdict}`, html(h(EvidenceLevel, { level: "L2", verdict })))),
  row("L3 (실측 0건)", html(h(EvidenceLevel, { level: "L3" }))),
  row(
    "무효 · 모델 밖",
    html(h(EvidenceLevel, { level: "none", reason: "invalid" })),
    html(h(EvidenceLevel, { level: "none", reason: "out-of-model" })),
  ),
);

const page = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>@kinetra/ui 미리보기</title>
<link rel="stylesheet" href="../tokens/tokens.css">
<link rel="stylesheet" href="../src/components.css">
<style>
body { margin: 0; background: var(--kin-color-bg-app); color: var(--kin-color-text-primary); font: var(--kin-type-body); font-variant-numeric: tabular-nums; }
main { width: 1440px; box-sizing: border-box; padding: var(--kin-space-1200); display: flex; flex-direction: column; gap: var(--kin-space-800); }
h1 { margin: 0; font: var(--kin-type-heading); }
h2 { margin: 0 0 var(--kin-space-300); font: var(--kin-type-title); }
p { margin: 0; color: var(--kin-color-text-secondary); }
section { display: flex; flex-direction: column; }
.row { display: flex; align-items: center; gap: var(--kin-space-300); padding: var(--kin-space-200) 0; border-top: 1px solid var(--kin-color-border-subtle); }
.lbl { width: 220px; flex: none; font: var(--kin-type-label); color: var(--kin-color-text-secondary); }
.gray { filter: grayscale(1); }
</style>
</head>
<body>
<main>
<header><h1>@kinetra/ui 미리보기</h1><p>packages/ui 컴포넌트를 react-dom/server로 렌더링한 정적 페이지. 승인 보드: design/exports/design-system/source/ValueBadges.dc.html, Evidence.dc.html</p></header>
${valueBadges}
${evidence}
</main>
</body>
</html>
`;

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, page);
console.log(`wrote ${out} (${VALUE_BADGE_KINDS.map((k) => VALUE_BADGE_LABELS[k]).join(", ")})`);
