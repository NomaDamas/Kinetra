// Bundles + minifies the share page script (three.js tree-shaken to what replay-client.js imports) into out/replay.js.
//   node build-replay.mjs      (also imported by measure-replay.mjs)
import { build } from "esbuild";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export async function buildReplay({ minify = true, outfile = join(HERE, "out", "replay.js") } = {}) {
  mkdirSync(dirname(outfile), { recursive: true });
  const r = await build({ entryPoints: [join(HERE, "src", "replay-client.js")], bundle: true, format: "esm", target: "es2022", minify, legalComments: "none",
    outfile, absWorkingDir: HERE, metafile: true, logLevel: "silent" });
  return { outfile, inputs: Object.keys(r.metafile.inputs).length };
}
if (process.argv[1] === fileURLToPath(import.meta.url)) console.log(await buildReplay());
