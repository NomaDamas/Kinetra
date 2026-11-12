// Static server for the A0-01b measurement page. `pnpm --dir spikes/mujoco-wasm dev` -> http://127.0.0.1:5174/
// Serves only this directory's page files, the reference data, the model and the pinned @mujoco/mujoco package
// (read-only, no directory listing). Loopback only.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const MUJOCO_DIR = join(HERE, "node_modules", "@mujoco", "mujoco");
const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json", ".wasm": "application/wasm", ".xml": "application/xml", ".f64": "application/octet-stream",
};
// URL prefix -> directory. The wasm package is mounted under /vendor/mujoco/ so mujoco.js finds mujoco.wasm next to itself.
const MOUNTS = [
  ["/vendor/mujoco/", MUJOCO_DIR],
  ["/src/", join(HERE, "src")],
  ["/reference/", join(HERE, "reference")],
  ["/model/", join(HERE, "model")],
];

export function resolveUrl(pathname) {
  if (pathname === "/" || pathname === "/index.html") return join(HERE, "index.html");
  for (const [prefix, dir] of MOUNTS) {
    if (!pathname.startsWith(prefix)) continue;
    const rel = normalize(decodeURIComponent(pathname.slice(prefix.length)));
    const full = join(dir, rel);
    if (full !== dir && !full.startsWith(dir + sep)) return null; // path escape
    return full;
  }
  return null;
}

export function startServer(port = 5174, host = "127.0.0.1") {
  const server = createServer(async (req, res) => {
    try {
      const file = resolveUrl(new URL(req.url, "http://x").pathname);
      if (!file) { res.writeHead(404).end("not found"); return; }
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve(server));
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? 5174);
  const server = await startServer(port);
  console.log(`A0-01b measurement page: http://127.0.0.1:${server.address().port}/  (add ?manual=1 to not auto-run)`);
}
