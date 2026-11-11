// Synthetic core: one pose stream per WebSocket connection (A0-02a). Plays the part of the core's frame stream at 60 Hz.
// Stands in for the real stream (C-05); it has no physics. Deterministic content (poses.js), wall-clock pacing.
import { frameBytes, writeHeader, poseView } from "./frame.js";
import { makeWorld, fillPoses, HZ } from "./poses.js";

/** Pure: fill `buf` (ArrayBuffer of frameBytes(world.n)) with the frame for `tick`. */
export function buildFrame(world, tick, ctrl, buf) {
  writeHeader(buf, { tick, n: world.n, simTime: tick / HZ, ctrlState: ctrl.state, ctrlSeq: ctrl.seq });
  fillPoses(world, tick, ctrl.state, poseView(buf, world.n));
  return buf;
}

export class PoseStream {
  // maxBuffered: a frame is not sent while more than this many bytes wait in the socket (default 3 frames). Without a bound a slow
  // client builds seconds of backlog and every later frame is stale; the skipped ticks are counted (stats.backpressure_skipped).
  constructor(ws, { n, seed = 0, hz = HZ, maxBufferedFrames = 3 }) {
    this.ws = ws; this.world = makeWorld(n, seed); this.hz = hz; this.maxBuffered = maxBufferedFrames * frameBytes(n);
    this.ctrl = { state: 0, seq: 0 }; this.pending = null; this.tick = 0; this.timer = null;
    this.stats = { sent: 0, backpressure_skipped: 0, rebases: 0, socket_errors: 0, bytes: 0, lateness_ms: [], build_ms: [], ctrl_wait_ms: [] };
    ws.on("message", (data, isBinary) => {
      const b = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data);
      if (!isBinary || b.length !== 8) return; // control message: u32 seq, u32 state (little-endian)
      this.pending = { seq: b.readUInt32LE(0), state: b.readUInt32LE(4), recvAt: performance.now() };
    });
    // A bad frame (too big, bad opcode, bad UTF-8) makes ws emit "error" on this connection only. Without a listener that is an
    // unhandled EventEmitter error and kills the whole measurement server; here it ends this stream and nothing else.
    ws.on("error", () => { this.stats.socket_errors++; this.stop(); ws.terminate(); });
    ws.on("close", () => this.stop());
    this.t0 = performance.now();
    this.step();
  }
  step() {
    const due = this.t0 + (this.tick * 1000) / this.hz, now = performance.now();
    if (now < due - 0.3) { this.timer = setTimeout(() => this.step(), Math.max(0, due - now - 0.3)); return; }
    if (now - due > 250) { this.t0 = now - (this.tick * 1000) / this.hz; this.stats.rebases++; } // server stalled: do not burst-catch-up forever
    this.stats.lateness_ms.push(Math.max(0, now - due));
    if (this.pending) { this.ctrl = { state: this.pending.state, seq: this.pending.seq }; this.stats.ctrl_wait_ms.push(now - this.pending.recvAt); this.pending = null; }
    if (this.ws.readyState !== 1) return;
    if (this.ws.bufferedAmount > this.maxBuffered) this.stats.backpressure_skipped++;
    else {
      const b0 = performance.now(), buf = buildFrame(this.world, this.tick, this.ctrl, new ArrayBuffer(frameBytes(this.world.n)));
      this.stats.build_ms.push(performance.now() - b0);
      this.ws.send(buf, { binary: true, compress: false });
      this.stats.sent++; this.stats.bytes += buf.byteLength;
    }
    this.tick++;
    this.step();
  }
  stop() { clearTimeout(this.timer); this.timer = null; }
}
