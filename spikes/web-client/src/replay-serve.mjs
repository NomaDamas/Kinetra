// Static server for the A0-02c share page, shaped like a plain static host: exact files only, gzip and brotli chosen by
// Accept-Encoding (everything compressed once BEFORE listening, max level, so no request pays for compression), `cache-control: no-store` so every visit is cold. Loopback only.
//   pnpm --dir spikes/web-client dev:replay  -> http://127.0.0.1:5176/
import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { dirname, extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

const HERE = dirname(fileURLToPath(import.meta.url)), ROOT = dirname(HERE);
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".json": "application/json", ".bin": "application/octet-stream" };
const COMPRESSIBLE = new Set([".html", ".js", ".json", ".bin"]);
const MOUNTS = [["/out/", join(ROOT, "out")], ["/replay/", join(ROOT, "replay")]];

export function resolveUrl(pathname) {
  if (pathname === "/" || pathname === "/index.html" || pathname === "/replay.html") return join(ROOT, "replay.html");
  for (const [prefix, dir] of MOUNTS) {
    if (!pathname.startsWith(prefix)) continue;
    const full = join(dir, normalize(decodeURIComponent(pathname.slice(prefix.length))));
    if (full !== dir && !full.startsWith(dir + sep)) return null;
    return full;
  }
  return null;
}
/** Picks br, then gzip, else identity from an Accept-Encoding header (q=0 means refused). */
export function pickEncoding(header = "") {
  const ok = new Set(header.split(",").map((s) => s.trim().split(";")).filter(([, q]) => !q || Number(q.trim().replace("q=", "")) > 0).map(([n]) => n.trim()));
  return ok.has("br") ? "br" : ok.has("gzip") ? "gzip" : "identity";
}
export const compress = {
  identity: (b) => b,
  gzip: (b) => zlib.gzipSync(b, { level: 9 }),
  br: (b) => zlib.brotliCompressSync(b, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: b.length } }),
};

/** `force` ("identity" | "gzip" | "br") ignores Accept-Encoding: the runner uses it to measure each encoding on the same page.
 *  `log` gets one entry per request: { path, encoding, bytes, status }. */
export async function startReplayServer(port = 5176, host = "127.0.0.1", { force = null } = {}) {
  // Every file in every encoding is compressed BEFORE the server listens, so no request pays for compression (the first
  // measurement run compressed lazily on the first request of each file/encoding).
  const cache = new Map(), log = [];
  for (const [prefix, dir] of MOUNTS) for (const name of await readdir(dir, { recursive: true }).catch(() => [])) {
    const file = join(dir, name);
    if (!(await stat(file)).isFile()) continue;
    for (const enc of force ? [force] : ["identity", "gzip", "br"]) cache.set(`${file}|${COMPRESSIBLE.has(extname(file)) ? enc : "identity"}`, compress[COMPRESSIBLE.has(extname(file)) ? enc : "identity"](await readFile(file)));
  }
  for (const enc of force ? [force] : ["identity", "gzip", "br"]) cache.set(`${join(ROOT, "replay.html")}|${enc}`, compress[enc](await readFile(join(ROOT, "replay.html"))));
  const server = createServer(async (req, res) => {
    let path = "?";
    try {
      path = new URL(req.url, "http://x").pathname; // throws on a malformed request target such as "//": inside the try, answered 400
      const file = resolveUrl(path);
      if (!file) { res.writeHead(404).end("not found"); log.push({ path, status: 404, bytes: 0, encoding: "identity" }); return; }
      const ext = extname(file), enc = COMPRESSIBLE.has(ext) ? (force ?? pickEncoding(req.headers["accept-encoding"])) : "identity", key = `${file}|${enc}`;
      if (!cache.has(key)) { res.writeHead(404).end("not found"); log.push({ path, status: 404, bytes: 0, encoding: "identity" }); return; }
      const body = cache.get(key);
      res.writeHead(200, { "content-type": MIME[ext] ?? "application/octet-stream", "content-length": body.length, "cache-control": "no-store", vary: "Accept-Encoding", ...(enc !== "identity" && { "content-encoding": enc }) });
      res.end(body); log.push({ path, status: 200, bytes: body.length, encoding: enc, accept_encoding: req.headers["accept-encoding"] ?? null });
    } catch (e) {
      const bad = e instanceof TypeError; // URL parse failure (the only TypeError on this path)
      res.writeHead(bad ? 400 : 404).end(bad ? "bad request" : "not found"); log.push({ path, status: bad ? 400 : 404, bytes: 0, encoding: "identity" });
    }
  });
  return new Promise((resolve, reject) => { server.once("error", reject); server.listen(port, host, () => resolve({ server, log, close: () => server.close() })); });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const s = await startReplayServer(Number(process.env.PORT ?? 5176));
  console.log(`A0-02c share page: http://127.0.0.1:${s.server.address().port}/  (run \`pnpm build:replay\` first)`);
}
