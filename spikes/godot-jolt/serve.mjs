// Static server for a Godot Web export directory. Loopback only, read-only, no directory listing.
// `crossOriginIsolated: true` adds the COOP/COEP headers a threaded Godot export needs (SharedArrayBuffer).
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize, sep } from "node:path";

const MIME = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".wasm": "application/wasm",
  ".pck": "application/octet-stream", ".png": "image/png",
};

export function resolveUrl(root, pathname) {
  const rel = normalize(decodeURIComponent(pathname === "/" ? "index.html" : pathname.replace(/^[/\\]+/, "")));
  const full = join(root, rel);
  if (!full.startsWith(root + sep)) return null; // path escape
  return full;
}

export function startServer(root, { port = 0, crossOriginIsolated = true, host = "127.0.0.1" } = {}) {
  const server = createServer(async (req, res) => {
    try {
      const file = resolveUrl(root, new URL(req.url, "http://x").pathname);
      if (!file) { res.writeHead(404).end("not found"); return; }
      const body = await readFile(file);
      const headers = { "content-type": MIME[extname(file)] ?? "application/octet-stream", "cache-control": "no-store" };
      if (crossOriginIsolated) {
        headers["cross-origin-opener-policy"] = "same-origin";
        headers["cross-origin-embedder-policy"] = "require-corp";
      }
      res.writeHead(200, headers);
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
