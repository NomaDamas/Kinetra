// Bundle src/app.js (three + @pmndrs/xr + @pmndrs/handle + iwer) into dist/ (gitignored). ES modules with code splitting:
// @pmndrs/xr dynamically imports its own emulator (and @iwer/devui + React) behind `emulate`; with emulate:false that chunk is never fetched.
import { build as esbuild } from "esbuild";
import { copyFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

export async function build({ outdir = join(HERE, "dist") } = {}) {
  mkdirSync(outdir, { recursive: true });
  await esbuild({
    entryPoints: [join(HERE, "src", "app.js")],
    outdir,
    bundle: true,
    splitting: true,
    format: "esm",
    platform: "browser",
    target: "chrome120",
    minify: true,
    legalComments: "none",
    logLevel: "warning",
  });
  copyFileSync(join(HERE, "src", "index.html"), join(outdir, "index.html"));
  return readdirSync(outdir).map((f) => ({ file: f, bytes: statSync(join(outdir, f)).size }));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  for (const f of await build()) console.log(`${f.bytes.toString().padStart(9)}  ${f.file}`);
}
