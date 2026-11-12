import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// Helpers that read the approved boards (design/exports/design-system/source/*.dc.html) and the component CSS,
// so the tests compare the code with the approved boards rather than with numbers retyped by hand.
const pkg = join(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDir = join(pkg, "../../design/exports/design-system/source");

export const boardText = (file: string): string => readFileSync(join(sourceDir, file), "utf8");
export const componentsCss = readFileSync(join(pkg, "src/components.css"), "utf8");
export const tokenCss = readFileSync(join(pkg, "tokens/tokens.css"), "utf8");

/** `--kin-color-x: #ABC;` -> lower-case hex, resolving one level of var() in component rules. */
export function tokenValue(variable: string): string {
  const m = new RegExp(`${variable}:\\s*([^;]+);`).exec(tokenCss);
  if (!m) throw new Error(`${variable} not in tokens.css`);
  return m[1]!.trim().toLowerCase();
}

/** Declarations of the first rule whose selector is exactly `selector` in components.css. */
export function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.[\]"=():]/g, "\\$&");
  const m = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(componentsCss);
  if (!m) throw new Error(`rule ${selector} not in components.css`);
  return m[1]!;
}

/** Resolve every var(--kin-…) in a declaration block to its token value. */
export function resolveVars(text: string): string {
  return text.replace(/var\((--kin-[a-z0-9-]+)\)/g, (_, name: string) => tokenValue(name));
}

/** Board markup is hand-written HTML (`<path …/>`); React serialises `<path …></path>`. Compare in React's form. */
export function asReactSvg(markup: string): string {
  return (
    markup
      .replace(/<(path|circle)([^>]*?)\s*\/>/g, "<$1$2></$1>")
      // The board closes some filled bars with an absolute `H<x>z`, one with `h-6z`: same geometry, one spelling.
      .replace(/v12H\d+z/g, "v12h-6z")
  );
}
