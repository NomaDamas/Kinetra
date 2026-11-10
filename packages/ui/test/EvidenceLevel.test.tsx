import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { EvidenceLevel, L2_VERDICTS } from "../src/index.ts";
import { asReactSvg, boardText, componentsCss, resolveVars, ruleBody } from "./boards.ts";

const html = (el: Parameters<typeof renderToStaticMarkup>[0]): string => renderToStaticMarkup(el);
const hex = (text: string): string[] => [...text.matchAll(/#[0-9A-Fa-f]{6}/g)].map((m) => m[0].toLowerCase());
const text = (out: string): string => out.replace(/<svg.*?<\/svg>/g, "").replace(/<[^>]+>/g, "|").replace(/\|+/g, "|");

// Evidence.dc.html, section "단계와 고정 문구": the pill `<div …height:28px…>` per stage.
const board = boardText("Evidence.dc.html");
function boardPill(code: string, phrase: string): string {
  const re = new RegExp(`<div style="display:inline-flex;align-items:center;gap:8px;height:28px[^"]*">(?:(?!</div>).)*?${code}</span>(?:(?!</div>).)*?${phrase}(?:(?!</div>).)*?</div>`);
  const m = re.exec(board);
  if (!m) throw new Error(`board pill ${code}/${phrase} not found`);
  return m[0];
}
const boardBars = (pill: string): string => /<svg width="30"[^>]*>(.*?)<\/svg>/.exec(pill)![1]!;

describe("EvidenceLevel snapshots", () => {
  it("L0", () => expect(html(<EvidenceLevel level="L0" />)).toMatchSnapshot());
  it("L1", () => expect(html(<EvidenceLevel level="L1" />)).toMatchSnapshot());
  it("L1 narrow", () => expect(html(<EvidenceLevel level="L1" narrow />)).toMatchSnapshot());
  for (const verdict of L2_VERDICTS) {
    it(`L2 ${verdict}`, () => expect(html(<EvidenceLevel level="L2" verdict={verdict} />)).toMatchSnapshot());
  }
  it("L3 (0 measurements)", () => expect(html(<EvidenceLevel level="L3" />)).toMatchSnapshot());
  it("none: invalid", () => expect(html(<EvidenceLevel level="none" reason="invalid" />)).toMatchSnapshot());
  it("none: out of model", () => expect(html(<EvidenceLevel level="none" reason="out-of-model" />)).toMatchSnapshot());
  it("announce", () => expect(html(<EvidenceLevel level="L1" announce />)).toMatchSnapshot());
});

describe("EvidenceLevel contract (brief 5절)", () => {
  it("fixed phrases per stage", () => {
    expect(text(html(<EvidenceLevel level="L0" />))).toBe("|L0|조립|질량, 무게중심, 정역학 경고|");
    expect(text(html(<EvidenceLevel level="L1" />))).toBe("|L1|미리보기|1회 실행. 판정이 아닙니다|");
    expect(text(html(<EvidenceLevel level="L1" narrow />))).toBe("|L1|1회 실행 · 판정 아님|");
    expect(text(html(<EvidenceLevel level="L2" verdict="FEASIBLE_FOUND" />))).toBe("|L2|판정|FEASIBLE_FOUND|");
    expect(text(html(<EvidenceLevel level="L3" />))).toBe("|L3|실측|실물 검증 없음|");
    expect(text(html(<EvidenceLevel level="none" reason="invalid" />))).toBe("|무효: 다시 판정해야 합니다|");
    expect(text(html(<EvidenceLevel level="none" reason="out-of-model" />))).toBe("|모델 밖: 판정할 수 없습니다|");
  });

  it("L2 weak evidence is marked in words, in the bars' label and by the weak modifier", () => {
    const out = html(<EvidenceLevel level="L2" verdict="NOT_FOUND_IN_BUDGET" />);
    expect(out).toContain("약한 증거");
    expect(out).toContain('aria-label="증거 강도 3/4, 약한 증거"');
    expect(out).toContain("kin-evidence--weak");
    expect(html(<EvidenceLevel level="L2" verdict="FEASIBLE_FOUND" />)).not.toContain("kin-evidence--weak");
  });

  it("the colour class depends on the stage only, never on the verdict (5.2 rule 1)", () => {
    const cls = (out: string): string => /class="kin-evidence kin-evidence--(l\d|none)/.exec(out)![1]!;
    for (const v of L2_VERDICTS) expect(cls(html(<EvidenceLevel level="L2" verdict={v} />))).toBe("l2");
    expect(cls(html(<EvidenceLevel level="L3" />))).toBe("none");
    expect(cls(html(<EvidenceLevel level="none" reason="invalid" />))).toBe("none");
    expect(cls(html(<EvidenceLevel level="none" reason="out-of-model" />))).toBe("none");
  });

  it("verdict shapes differ while the colour stays the same (shape, not colour, tells the result)", () => {
    const shapes = new Set(L2_VERDICTS.map((v) => html(<EvidenceLevel level="L2" verdict={v} />).match(/<svg width="12".*?<\/svg>/)![0]));
    expect(shapes.size).toBe(L2_VERDICTS.length);
  });

  it("no success/failure colouring: no status tokens in the evidence rules", () => {
    expect(componentsCss.slice(componentsCss.indexOf("EvidenceLevel"))).not.toContain("color-status");
  });

  it("strength bars (filled count and aria-label) match the approved board", () => {
    const cases: [string, string, string, string][] = [
      ["L0", "질량, 무게중심, 정역학 경고", html(<EvidenceLevel level="L0" />), "1/4"],
      ["L1", "1회 실행. 판정이 아닙니다", html(<EvidenceLevel level="L1" />), "2/4"],
      ["L2", "FEASIBLE_FOUND", html(<EvidenceLevel level="L2" verdict="FEASIBLE_FOUND" />), "3/4"],
      ["L3", "실물 검증 없음", html(<EvidenceLevel level="L3" />), "0/4"],
    ];
    for (const [code, phrase, out, strength] of cases) {
      const pill = boardPill(code, phrase);
      expect(boardBars(pill)).toContain(`<path`);
      const mine = /<svg width="30"[^>]*>(.*?)<\/svg>/.exec(out)![1]!;
      expect(mine).toBe(asReactSvg(boardBars(pill)));
      expect(out).toContain(`aria-label="증거 강도 ${strength}"`);
    }
  });

  it("resolves to the colours of the approved board per stage", () => {
    const stages: [string, string, string, string][] = [
      [".kin-evidence--l0", "L0", "질량, 무게중심, 정역학 경고", "solid"],
      [".kin-evidence--l1", "L1", "1회 실행. 판정이 아닙니다", "solid"],
      [".kin-evidence--l2", "L2", "FEASIBLE_FOUND", "solid"],
      [".kin-evidence--none", "L3", "실물 검증 없음", "solid"],
    ];
    for (const [selector, code, phrase] of stages) {
      const colors = new Set(hex(resolveVars(ruleBody(selector))));
      const boardColors = new Set(hex(boardPill(code, phrase)));
      expect(colors).toEqual(boardColors);
    }
  });

  it("pill size matches the board: 28 px high, 12 px padding, radius pill, label type", () => {
    const base = resolveVars(ruleBody(".kin-evidence"));
    expect(base).toContain("height: 28px");
    expect(base).toContain("padding: 0 12px");
    expect(base).toContain("border-radius: 999px");
    expect(base).toContain("font: 500 12px/16px");
    expect(resolveVars(ruleBody(".kin-evidence--weak"))).toContain("border-style: dashed");
  });
});
