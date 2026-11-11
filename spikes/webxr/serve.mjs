// Static server for the spike page. Loopback only, read-only, no directory listing. `/profiles/*` is served from
// fixtures/profiles (the WebXR input-profiles registry JSON, offline); everything else from the built `dist/`.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DIST = join(HERE, "dist");
export const PROFILES = join(HERE, "fixtures", "profiles");
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".css": "text/css" };

/** Map a URL path to a file under `root`, or null if it would leave `root`. */
export function resolveUrl(root, pathname) {
  const base = resolve(root);
  const rel = normalize(decodeURIComponent(pathname === "/" ? "index.html" : pathname.replace(/^[/\\]+/, "")));
  const full = join(base, rel);
  if (!full.startsWith(base + sep)) return null;
  return full;
}

export function startServer({ port = 0, host = "127.0.0.1", dist = DIST, profiles = PROFILES } = {}) {
  const server = createServer(async (req, res) => {
    try {
      const { pathname } = new URL(req.url, "http://x");
      const isProfile = pathname.startsWith("/profiles/");
      const file = isProfile ? resolveUrl(profiles, pathname.slice("/profiles".length)) : resolveUrl(dist, pathname);
      if (!file) { res.writeHead(404).end("not found"); return; }
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  return new Promise((ok, fail) => {
    server.once("error", fail);
    server.listen(port, host, () => ok(server));
  });
}
