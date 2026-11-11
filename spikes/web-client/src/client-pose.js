// A0-02a measurement page: receives the synthetic 60 Hz pose stream (frame.js) and draws it with one three.js InstancedMesh.
// Phases: warmup -> A (natural rAF loop, frame rate + bandwidth) -> bench (back-to-back draws with gl.finish) -> latency
// (the runner presses Space; marker pixel read back) -> window.__A0_02A_RESULT. Any failure sets window.__A0_02A_ERROR.
// A0-02a-f: ?flow=ack&win=2 makes the client ack every newly drawn tick (flow.js) so the core keeps at most `win` frames unacked;
// ?flow=none (default) is the A0-02a behaviour: no acks, the core only watches bufferedAmount.
import * as THREE from "three";
import { readHeader, poseView, frameBytes, writeControl, writeAck } from "/src/frame.js";
import { makeWorld, bodyScale, bodyHue } from "/src/poses.js";
import { summarize } from "/src/stats.js";
import { LatencyTracker } from "/src/latency.js";
import { IntervalRecorder } from "/src/intervals.js";
import { AckSender, FLOWS } from "/src/flow.js";

const q = new URLSearchParams(location.search);
const cfg = { n: +(q.get("n") ?? 1000), seed: +(q.get("seed") ?? 0), warmup_ms: +(q.get("warmup") ?? 1500), measure_ms: +(q.get("measure") ?? 8000),
  bench_frames: +(q.get("bench") ?? 60), presses: +(q.get("presses") ?? 40), w: +(q.get("w") ?? 960), h: +(q.get("h") ?? 540),
  flow: q.get("flow") ?? "none", win: +(q.get("win") ?? 2) };
const now = () => performance.now();
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (e) => { window.__A0_02A_ERROR = String(e && e.stack || e); };
window.addEventListener("error", (e) => fail(e.error ?? e.message));
window.addEventListener("unhandledrejection", (e) => fail(e.reason));

try {
  if (!FLOWS.includes(cfg.flow)) throw new Error(`flow must be one of ${FLOWS.join(", ")}, got ${cfg.flow}`); // inside try, after the listeners: a bad URL sets __A0_02A_ERROR
  const world = makeWorld(cfg.n, cfg.seed);
  const canvas = document.getElementById("c");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: "high-performance" });
  renderer.setPixelRatio(1); renderer.setSize(cfg.w, cfg.h, false); canvas.style.width = cfg.w + "px"; canvas.style.height = cfg.h + "px";
  const gl = renderer.getContext(), dbg = gl.getExtension("WEBGL_debug_renderer_info");
  const scene = new THREE.Scene(); scene.background = new THREE.Color(0x14181f);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4); sun.position.set(0.4, -0.6, 1); scene.add(sun);
  const cam = new THREE.PerspectiveCamera(50, cfg.w / cfg.h, 0.5, world.extent * 6);
  cam.up.set(0, 0, 1); cam.position.set(0, -world.extent * 0.95, world.extent * 0.75); cam.lookAt(0, 0, 1); cam.updateMatrixWorld(); cam.updateProjectionMatrix();

  // One instanced mesh for all bodies. Body 0 is the latency marker (magenta, scaled up by the world, see below).
  const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshLambertMaterial(), cfg.n);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage); mesh.frustumCulled = false;
  const col = new THREE.Color(), me = mesh.instanceMatrix.array;
  const scl = new Float32Array(cfg.n * 3);
  for (let i = 0; i < cfg.n; i++) {
    const s = i === 0 ? [world.marker.size, world.marker.size, world.marker.size] : bodyScale(world, i);
    scl.set(s, i * 3);
    if (i === 0) col.setRGB(1, 0, 1); else col.setHSL(0.08 + 0.47 * bodyHue(world, i), 0.7, 0.55); // no magenta in the palette
    mesh.setColorAt(i, col);
  }
  scene.add(mesh);

  // Pose block -> instance matrices (column-major 4x4). This is the per-frame JS work of a client replaying a pose stream.
  function applyPoses(pose) {
    for (let i = 0, o = 0, m = 0; i < cfg.n; i++, o += 7, m += 16) {
      const x = pose[o], y = pose[o + 1], z = pose[o + 2], qx = pose[o + 3], qy = pose[o + 4], qz = pose[o + 5], qw = pose[o + 6];
      const sx = scl[i * 3], sy = scl[i * 3 + 1], sz = scl[i * 3 + 2];
      const xx = qx * qx, yy = qy * qy, zz = qz * qz, xy = qx * qy, xz = qx * qz, yz = qy * qz, wx = qw * qx, wy = qw * qy, wz = qw * qz;
      me[m] = (1 - 2 * (yy + zz)) * sx; me[m + 1] = 2 * (xy + wz) * sx; me[m + 2] = 2 * (xz - wy) * sx; me[m + 3] = 0;
      me[m + 4] = 2 * (xy - wz) * sy; me[m + 5] = (1 - 2 * (xx + zz)) * sy; me[m + 6] = 2 * (yz + wx) * sy; me[m + 7] = 0;
      me[m + 8] = 2 * (xz + wy) * sz; me[m + 9] = 2 * (yz - wx) * sz; me[m + 10] = (1 - 2 * (xx + yy)) * sz; me[m + 11] = 0;
      me[m + 12] = x; me[m + 13] = y; me[m + 14] = z; me[m + 15] = 1;
    }
    mesh.instanceMatrix.needsUpdate = true;
  }
  const markerPx = [world.marker.x0, world.marker.x1].map((x) => {
    const v = new THREE.Vector3(x, world.marker.y, world.marker.z).project(cam);
    return [Math.round((v.x + 1) / 2 * cfg.w), Math.round((v.y + 1) / 2 * cfg.h)]; // GL origin is bottom-left
  });
  const px = new Uint8Array(4);
  const isMagenta = ([r, g, b]) => r > g + 70 && b > g + 70;
  const probe = (state) => { // true iff the marker is drawn at `state`'s spot and NOT at the other one
    const read = (p) => { gl.readPixels(p[0], p[1], 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return isMagenta(px); };
    const here = read(markerPx[state]), other = read(markerPx[1 - state]);
    return here && !other;
  };
  // Which spot the marker is drawn at right now (0, 1) or null; read from the pixels after a render, so only called when no input is pending.
  const seenAt = () => { const at = (p) => { gl.readPixels(p[0], p[1], 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); return isMagenta(px); }; const a = at(markerPx[0]), b = at(markerPx[1]); return a && !b ? 0 : b && !a ? 1 : null; };

  // --- network ---
  const ws = new WebSocket(`ws://${location.host}/pose?n=${cfg.n}&seed=${cfg.seed}&flow=${cfg.flow}&win=${cfg.win}`); ws.binaryType = "arraybuffer";
  const net = { frames: 0, bytes: 0, arrive_dt: [], last_arrive: 0, bad: 0, recv_tick_gap: [], last_tick: -1, acks_sent: 0 };
  const acker = new AckSender();
  let latest = null, latestAt = 0, latestHeader = null, latestDrawn = true, overwritten = 0, recording = false;
  const firstRecvOfSeq = new Map(); // ctrl_seq -> performance.now() of the first frame carrying it
  ws.onmessage = (ev) => {
    const t = now(), buf = ev.data;
    let h; try { h = readHeader(buf); } catch { net.bad++; return; }
    if (h.n !== cfg.n) { net.bad++; return; }
    if (recording) { net.frames++; net.bytes += buf.byteLength; if (net.last_arrive) net.arrive_dt.push(t - net.last_arrive); if (net.last_tick >= 0) net.recv_tick_gap.push(h.tick - net.last_tick); }
    net.last_arrive = t; net.last_tick = h.tick;
    if (latest && !latestDrawn && recording) overwritten++; // a received frame replaced before any draw used it
    if (!firstRecvOfSeq.has(h.ctrlSeq)) firstRecvOfSeq.set(h.ctrlSeq, t);
    latest = buf; latestAt = t; latestHeader = h; latestDrawn = false;
  };
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("websocket error")); });
  await new Promise((res) => { const t0 = now(); (function w() { if (latest || now() - t0 > 10000) res(); else setTimeout(w, 5); })(); });
  if (!latest) throw new Error("no frame received in 10 s");

  // --- rAF loop (natural pacing) ---
  const rafIntervals = new IntervalRecorder();
  const S = { update_ms: [], render_ms: [], cpu_ms: [], age_ms: [], ticks_drawn: 0, tick_gaps: [], draws: 0, lastTick: -1 };
  const tracker = new LatencyTracker(null); // overlapping-input rules in src/latency.js
  let phase = "warmup", nextSeq = 1, ctrlState = 0;
  function draw(t) {
    const buf = latest, h = latestHeader, a0 = now(); latestDrawn = true;
    applyPoses(poseView(buf, cfg.n));
    const a1 = now(); renderer.render(scene, cam); const a2 = now();
    if (cfg.flow === "ack" && ws.readyState === 1) { const tk = acker.onDraw(h.tick); if (tk !== null) { ws.send(writeAck(tk)); net.acks_sent++; } } // ack = "drawn", sent right after render() returns
    if (phase === "A") {
      S.update_ms.push(a1 - a0); S.render_ms.push(a2 - a1); S.cpu_ms.push(a2 - a0); S.age_ms.push(a0 - latestAt + 0); S.draws++;
      if (h.tick !== S.lastTick) { S.ticks_drawn++; if (S.lastTick >= 0) S.tick_gaps.push(h.tick - S.lastTick); S.lastTick = h.tick; }
    }
    rafIntervals.frame(t);
    if (phase === "latency") {
      tracker.refresh(seenAt()); // idle: what the screen shows now, read from pixels
      const sm = tracker.onDraw(h, probe, { screen: now(), draw_start: a0, frame_tick: h.tick });
      if (sm) sm.recv = firstRecvOfSeq.get(sm.seq) ?? null; // first frame that carried this input's seq
    }
  }
  const loop = (t) => { if (phase !== "done") { draw(t); requestAnimationFrame(loop); } };
  requestAnimationFrame(loop);

  addEventListener("keydown", (e) => {
    if (e.code !== "Space" || e.repeat || phase !== "latency" || ws.readyState !== 1) return;
    const hs = now(); ctrlState ^= 1;
    const seq = nextSeq++;
    ws.send(writeControl(seq, ctrlState));
    tracker.input({ seq, state: ctrlState, input: e.timeStamp, handler: hs, sent: now() });
  });

  await sleep(cfg.warmup_ms);
  recording = true; phase = "A"; rafIntervals.start(); const tA0 = now();
  await sleep(cfg.measure_ms);
  phase = "bench"; recording = false; rafIntervals.stop(); const tA1 = now();

  // --- bench: same update + render, back to back, with a 1-pixel readPixels after each (gl.finish() did not block in this build: it returned in microseconds) so the rasterizer's work is inside the timing ---
  await sleep(100);
  const bench = { update_ms: [], render_ms: [], sync_ms: [], total_ms: [] };
  const pose = poseView(latest, cfg.n);
  for (let f = 0; f < cfg.bench_frames; f++) {
    const b0 = now(); applyPoses(pose); const b1 = now(); renderer.render(scene, cam); const b2 = now(); gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); const b3 = now();
    bench.update_ms.push(b1 - b0); bench.render_ms.push(b2 - b1); bench.sync_ms.push(b3 - b2); bench.total_ms.push(b3 - b0);
    if (f % 10 === 9) await sleep(0);
  }
  const benchWall = bench.total_ms.reduce((x, y) => x + y, 0);

  // --- latency phase: the runner presses Space cfg.presses times ---
  phase = "latency"; window.__A0_02A_LATENCY_READY = true;
  const geom = renderer.info.render;
  window.__finish = async () => {
    for (const t0 = now(); tracker.pending.size && now() - t0 < 4000;) await sleep(20); // let late probes resolve (loaded machine)
    phase = "done"; await sleep(50);
    const frames = S.draws, wallA = (tA1 - tA0) / 1000;
    const dts = rafIntervals.dt;
    const result = {
      config: cfg, bytes_per_frame: frameBytes(cfg.n), marker_px: markerPx,
      env: { user_agent: navigator.userAgent, webgl_renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null, webgl_vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
        cross_origin_isolated: crossOriginIsolated, device_pixel_ratio: devicePixelRatio, three_revision: THREE.REVISION, used_js_heap_mb: performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null },
      render_info: { calls: geom.calls, triangles: geom.triangles },
      phase_a: { wall_s: +wallA.toFixed(3), raf_frames: frames, raf_fps: +(frames / wallA).toFixed(2), raf_dt_ms: summarize(dts), raf_dt_over_20ms: dts.filter((d) => d > 20).length, raf_dt_over_33ms: dts.filter((d) => d > 33.0).length, raf_dt_samples_ms: dts.map((d) => Math.round(d * 100) / 100),
        update_ms: summarize(S.update_ms), render_call_ms: summarize(S.render_ms), cpu_ms: summarize(S.cpu_ms),
        distinct_ticks_drawn: S.ticks_drawn, distinct_ticks_per_s: +(S.ticks_drawn / wallA).toFixed(2), tick_gap: summarize(S.tick_gaps), tick_gap_over_1: S.tick_gaps.filter((g) => g > 1).length,
        frames_received: net.frames, frames_overwritten_before_draw: overwritten, frames_unaccounted: net.frames - S.ticks_drawn - overwritten, frame_age_at_draw_ms: summarize(S.age_ms) },
      net: { frames: net.frames, bytes: net.bytes, bad_frames: net.bad, frames_per_s: +(net.frames / wallA).toFixed(2), payload_bytes_per_s: Math.round(net.bytes / wallA), payload_mbit_per_s: +(net.bytes * 8 / wallA / 1e6).toFixed(3), arrive_dt_ms: summarize(net.arrive_dt),
        recv_tick_gap: summarize(net.recv_tick_gap), recv_tick_gap_over_1: net.recv_tick_gap.filter((g) => g > 1).length, acks_sent: net.acks_sent },
      bench: { frames: cfg.bench_frames, update_ms: summarize(bench.update_ms), render_call_ms: summarize(bench.render_ms), sync_ms: summarize(bench.sync_ms), total_ms: summarize(bench.total_ms), frames_per_s_sync: +(1000 * cfg.bench_frames / benchWall).toFixed(2) },
      latency: { requested: cfg.presses, ...tracker.counts(), samples: tracker.samples.map((r) => ({ seq: r.seq, input_to_handler: r.handler - r.input, handler_to_sent: r.sent - r.handler, sent_to_first_frame_recv: r.recv == null ? null : r.recv - r.sent, recv_to_draw_start: r.recv == null ? null : r.draw_start - r.recv, draw_start_to_pixels: r.screen - r.draw_start, total: r.screen - r.input, frame_tick: r.frame_tick })) },
    };
    const part = (k) => summarize(result.latency.samples.map((s) => s[k]));
    result.latency.summary = Object.fromEntries(["input_to_handler", "handler_to_sent", "sent_to_first_frame_recv", "recv_to_draw_start", "draw_start_to_pixels", "total"].map((k) => [k, part(k)]));
    window.__A0_02A_RESULT = result; return result;
  };
  window.__A0_02A_SCREENSHOT_READY = true;
} catch (e) { fail(e); }
