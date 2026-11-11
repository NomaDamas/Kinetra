// Static server + pose WebSocket for the A0-02a/A0-02c measurement pages. `pnpm --dir spikes/web-client dev` -> http://127.0.0.1:5175/
// Serves only fixed mounts (no directory listing). Loopback only. /pose?n=1000&seed=0 is the synthetic 60 Hz pose stream.
// COOP/COEP headers are on so performance.now() has 5 us resolution (crossOriginIsolated) instead of the coarse 100 us.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { dirname, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";
import { PoseStream } from "./stream.mjs";
import { FLOWS, MAX_WINDOW } from "./flow.js";

const HERE = dirname(fileURLToPath(import.meta.url)), ROOT = dirname(HERE);
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".json": "application/json", ".bin": "application/octet-stream" };
const MOUNTS = [["/three/", join(ROOT, "node_modules", "three", "build")], ["/src/", HERE], ["/replay/", join(ROOT, "replay")]];
const PAGES = { "/": "pose.html", "/index.html": "pose.html", "/pose.html": "pose.html", "/replay.html": "replay.html" };

export function resolveUrl(pathname) {
  if (PAGES[pathname]) return join(ROOT, PAGES[pathname]);
  for (const [prefix, dir] of MOUNTS) {
    if (!pathname.startsWith(prefix)) continue;
    const full = join(dir, normalize(decodeURIComponent(pathname.slice(prefix.length))));
    if (full !== dir && !full.startsWith(dir + sep)) return null; // path escape
    return full;
  }
  return null;
}

/** Returns { server, streams } where streams is the live list of PoseStream objects (their stats are read by the runner). */
export const HEAVY_BODIES = 1000; // streams of this many bodies or more are heavy runs (docs/process/dev-resources.md)
/** Same rule as tools/screenshots: outside CI a heavy browser run must come through the P0-09 resource guard. */
export const guardPassedFromEnv = (env = process.env) => env.CI === "true" || env.KINETRA_GUARD_PASSED === "1";

/** The page's own origin(s): this server's loopback address and port, by IP or by the name `localhost`. */
export const allowedOrigins = (addr) => addr && typeof addr === "object" ? [`http://${addr.address}:${addr.port}`, `http://localhost:${addr.port}`] : [];

/** `guardPassed` false: /pose refuses n >= HEAVY_BODIES (the page's auto-running measurement is the heavy part). */
export function startServer(port = 5175, host = "127.0.0.1", { guardPassed = guardPassedFromEnv() } = {}) {
  const streams = [];
  const server = createServer(async (req, res) => {
    try {
      const file = resolveUrl(new URL(req.url, "http://x").pathname); // throws on a malformed request target
      if (!file) { res.writeHead(404).end("not found"); return; }
      const body = await readFile(file);
      res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream", "cache-control": "no-store",
        "cross-origin-opener-policy": "same-origin", "cross-origin-embedder-policy": "require-corp" });
      res.end(body);
    } catch (e) { if (e instanceof TypeError && /Invalid URL/.test(e.message)) res.writeHead(400).end("bad request"); else res.writeHead(404).end("not found"); }
  });
  const wss = new WebSocketServer({ noServer: true, perMessageDeflate: false, maxPayload: 64 });
  server.on("upgrade", (req, socket, head) => {
    // A web page on another origin must not be able to open this stream (cross-site WebSocket hijacking): only this server's own
    // origin passes, on its real port. A missing Origin (non-browser client) is refused too.
    if (!allowedOrigins(server.address()).includes(req.headers.origin)) { socket.end("HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"); return; }
    let u; try { u = new URL(req.url, "http://x"); } catch { socket.end("HTTP/1.1 400 Bad Request\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"); return; }
    const n = Number(u.searchParams.get("n")), seed = Number(u.searchParams.get("seed") ?? 0);
    const flow = u.searchParams.get("flow") ?? "none", win = Number(u.searchParams.get("win") ?? 2); // flow=none|ack, win = max unacked frames (flow=ack only)
    if (u.pathname === "/pose" && n >= HEAVY_BODIES && !guardPassed) {
      socket.end("HTTP/1.1 403 Forbidden\r\ncontent-length: 0\r\nconnection: close\r\n\r\n"); // 1,000+ bodies only through the resource guard
      return;
    }
    if (u.pathname !== "/pose" || !Number.isInteger(n) || n < 2 || n > 20000 || !Number.isInteger(seed) || !FLOWS.includes(flow) || !Number.isInteger(win) || win < 1 || win > MAX_WINDOW) { socket.destroy(); return; }
    wss.handleUpgrade(req, socket, head, (ws) => streams.push(new PoseStream(ws, { n, seed, flow, win })));
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => resolve({ server, streams, close: () => { for (const s of streams) s.stop(); wss.clients.forEach((c) => c.terminate()); server.close(); } }));
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const s = await startServer(Number(process.env.PORT ?? 5175));
  console.log(`A0-02a pose-stream page: http://127.0.0.1:${s.server.address().port}/?n=200`);
  if (!guardPassedFromEnv()) console.log(`n >= ${HEAVY_BODIES} is refused outside the resource guard. For it start this server as:\n  uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/web-client dev`);
}
