import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { tokens } from "../tokens/tokens.ts";
// @ts-expect-error plain .mjs script without types
import { BASE_RULES, cssVarName, generate } from "../scripts/build-tokens.mjs";

const pkg = join(dirname(fileURLToPath(import.meta.url)), "..");
const exportDir = join(pkg, "../../design/exports/design-system");
const sourceJson = JSON.parse(readFileSync(join(exportDir, "tokens.json"), "utf8")) as Record<string, string>;
const exportCss = readFileSync(join(exportDir, "tokens.css"), "utf8");

function declarations(css: string): Map<string, string> {
  const root = /:root\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
  const out = new Map<string, string>();
  for (const m of root.matchAll(/(--kin-[a-z0-9-]+):\s*([^;]+);/g)) out.set(m[1]!, m[2]!.trim());
  return out;
}

describe("tokens generated from the approved export", () => {
  const { $meta, ...expected } = sourceJson;
  void $meta;

  it("tokens.ts carries every tokens.json entry with the same value", () => {
    expect({ ...tokens }).toEqual(expected);
    expect(Object.keys(tokens)).toEqual(Object.keys(expected));
  });

  it("tokens/tokens.css declares exactly the variables of the export's tokens.css", () => {
    const mine = declarations(readFileSync(join(pkg, "tokens/tokens.css"), "utf8"));
    expect(mine).toEqual(declarations(exportCss));
    for (const [name, value] of Object.entries(expected)) expect(mine.get(cssVarName(name))).toBe(value);
  });

  it("keeps the export's focus ring and reduced-motion rules byte for byte", () => {
    expect(exportCss.endsWith(`}\n\n${BASE_RULES}`)).toBe(true);
    expect(readFileSync(join(pkg, "tokens/tokens.css"), "utf8").endsWith(`}\n\n${BASE_RULES}`)).toBe(true);
  });

  it("the checked-in files are what the generator produces (deterministic)", () => {
    const a = generate();
    const b = generate();
    expect(a).toEqual(b);
    expect(readFileSync(join(pkg, "tokens/tokens.css"), "utf8")).toBe(a["tokens.css"]);
    expect(readFileSync(join(pkg, "tokens/tokens.ts"), "utf8")).toBe(a["tokens.ts"]);
  });

  it("--check passes on a clean tree", () => {
    const out = execFileSync("node", [join(pkg, "scripts/build-tokens.mjs"), "--check"], { encoding: "utf8" });
    expect(out).toContain("up to date");
  });

  it("rejects a malformed token file instead of emitting it", () => {
    expect(() => generate(JSON.stringify({ "color.bg.app": 1 }))).toThrow(/non-empty string/);
    expect(() => generate(JSON.stringify({ "Bad Name": "x" }))).toThrow(/not allowed/);
    expect(() => generate(JSON.stringify({ "unknown.group": "x" }))).toThrow(/no group/);
  });
});
