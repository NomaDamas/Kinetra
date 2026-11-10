import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { VALUE_BADGE_KINDS, VALUE_BADGE_LABELS, ValueBadge } from "../src/index.ts";
import { asReactSvg, boardText, componentsCss, resolveVars, ruleBody } from "./boards.ts";

const html = (el: Parameters<typeof renderToStaticMarkup>[0]): string => renderToStaticMarkup(el);
const hex = (text: string): string[] => [...text.matchAll(/#[0-9A-Fa-f]{6}/g)].map((m) => m[0].toLowerCase());

// The board's first button per label: ValueBadges.dc.html, section "다섯 가지".
const board = boardText("ValueBadges.dc.html");
function boardButton(label: string): string {
  const m = new RegExp(`<button type="button"[^>]*>(?:(?!</button>).)*?</svg>${label}</span></button>`).exec(board);
  if (!m) throw new Error(`board button ${label} not found`);
  return m[0];
}

describe("ValueBadge snapshots", () => {
  for (const kind of VALUE_BADGE_KINDS) {
    it(`${kind}`, () => {
      expect(html(<ValueBadge kind={kind} />)).toMatchSnapshot();
    });
  }
  it("modifier prefix", () => {
    expect(html(<ValueBadge kind="declared" modifier="카탈로그 밖" />)).toMatchSnapshot();
  });
  it("sim stale (오래됨)", () => {
    expect(html(<ValueBadge kind="sim" stale />)).toMatchSnapshot();
  });
  it("popover open (aria-expanded)", () => {
    expect(html(<ValueBadge kind="cite" aria-expanded="true" />)).toMatchSnapshot();
  });
});

describe("ValueBadge contract (brief 4절)", () => {
  it("has the five kinds with the approved labels", () => {
    expect(VALUE_BADGE_KINDS).toEqual(["sim", "cite", "default", "declared", "estimate"]);
    expect(VALUE_BADGE_LABELS).toEqual({
      sim: "시뮬",
      cite: "인용",
      default: "기본값",
      declared: "사용자 선언",
      estimate: "추정",
    });
  });

  it("is a focusable button that cannot be disabled, with a label and a glyph (not colour alone)", () => {
    for (const kind of VALUE_BADGE_KINDS) {
      const out = html(<ValueBadge kind={kind} />);
      expect(out).toMatch(/^<button[^>]*type="button"/);
      expect(out).not.toContain("disabled");
      expect(out).toContain(VALUE_BADGE_LABELS[kind]);
      expect(out).toContain('aria-hidden="true"');
    }
  });

  it("rejects `disabled` at the type level", () => {
    // @ts-expect-error badges are never disabled: reading the evidence is never blocked (V1)
    void (<ValueBadge kind="sim" disabled />);
    // @ts-expect-error only `sim` can be stale
    void (<ValueBadge kind="cite" stale />);
  });

  it("never lets `disabled` or `aria-disabled` reach the DOM, even through a spread or `as any`", () => {
    const sneaky = { disabled: true, "aria-disabled": true } as any;
    for (const kind of VALUE_BADGE_KINDS) {
      const out = html(<ValueBadge kind={kind} {...sneaky} />);
      expect(out).not.toContain("disabled");
    }
  });

  it("forwards button props (click opens the evidence popover)", () => {
    const out = html(<ValueBadge kind="sim" aria-haspopup="dialog" aria-controls="pop" />);
    expect(out).toContain('aria-haspopup="dialog"');
    expect(out).toContain('aria-controls="pop"');
  });

  it("uses the glyph paths of the approved board", () => {
    for (const kind of VALUE_BADGE_KINDS) {
      const board_ = boardButton(VALUE_BADGE_LABELS[kind]);
      const boardGlyph = /aria-hidden="true">(.*?)<\/svg>/.exec(board_)![1]!;
      expect(html(<ValueBadge kind={kind} />)).toContain(asReactSvg(boardGlyph));
    }
  });

  const SELECTOR = {
    sim: ".kin-value-badge--sim",
    cite: ".kin-value-badge--cite",
    default: ".kin-value-badge--default",
    declared: ".kin-value-badge--declared",
    estimate: ".kin-value-badge--estimate",
  } as const;

  it("resolves to the colours and border shape of the approved board", () => {
    for (const kind of VALUE_BADGE_KINDS) {
      const b = boardButton(VALUE_BADGE_LABELS[kind]);
      const boardColors = hex(b).sort();
      const text = resolveVars(ruleBody(SELECTOR[kind]));
      const pill = resolveVars(ruleBody(`${SELECTOR[kind]} .kin-value-badge__pill`));
      expect([...hex(text), ...hex(pill)].sort()).toEqual(boardColors);
      const boardBorder = /border:1px (solid|dashed)/.exec(b)?.[1];
      expect(/border: 1px (solid|dashed)/.exec(pill)?.[1]).toBe(boardBorder);
    }
  });

  it("matches the board size: pill 20 px, hit area 24 px, caption type, pill radius, 4px gap, 8px padding", () => {
    const base = resolveVars(ruleBody(".kin-value-badge"));
    const pill = resolveVars(ruleBody(".kin-value-badge__pill"));
    expect(base).toContain("height: 24px");
    expect(base).toContain("font: 500 11px/16px");
    expect(pill).toContain("height: 20px");
    expect(pill).toContain("gap: 4px");
    expect(pill).toContain("padding: 0 8px");
    expect(pill).toContain("border-radius: 999px");
  });

  it("components.css has no colour literal outside rgba veils; it only reads tokens", () => {
    expect(componentsCss).not.toMatch(/#[0-9A-Fa-f]{3,8}\b/);
  });
});
