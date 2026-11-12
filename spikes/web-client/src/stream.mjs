// Synthetic core: one pose stream per WebSocket connection (A0-02a). Plays the part of the core's frame stream at 60 Hz.
// Stands in for the real stream (C-05); it has no physics. Deterministic content (poses.js), wall-clock pacing.
import { frameBytes, writeHeader, poseView, readClientMessage } from "./frame.js";
import { AckWindow, FLOWS } from "./flow.js";
import { makeWorld, fillPoses, HZ } from "./poses.js";

/** Pure: fill `buf` (ArrayBuffer of frameBytes(world.n)) with the frame for `tick`. */
export function buildFrame(world, tick, ctrl, buf) {
  writeHeader(buf, { tick, n: world.n, simTime: tick / HZ, ctrlState: ctrl.state, ctrlSeq: ctrl.seq });
  fillPoses(world, tick, ctrl.state, poseView(buf, world.n));
  return buf;
}

export class PoseStream {
  // flow "none" (A0-02a): a frame is not sent while more than maxBufferedFrames frames wait in the socket (bufferedAmount). Without a
  //   bound a slow client builds seconds of backlog; the skipped ticks are counted (stats.backpressure_skipped). On loopback the OS
  //   socket buffers swallow the frames before bufferedAmount rises, so this does not bound the client's backlog (REPORT.md).
  // flow "ack" (A0-02a-f): at most `win` frames sent and not yet acked by the client (flow.js AckWindow). A tick with no free slot is
  //   skipped (stats.window_skipped), never queued, so the frame sent next is always the newest tick. bufferedAmount is not used.
  constructor(ws, { n, seed = 0, hz = HZ, maxBufferedFrames = 3, flow = "none", win = 2 }) {
    if (!FLOWS.includes(flow)) throw new RangeError(`flow must be one of ${FLOWS.join(", ")}, got ${flow}`);
    this.ws = ws; this.world = makeWorld(n, seed); this.hz = hz; this.maxBuffered = maxBufferedFrames * frameBytes(n);
    this.flow = flow; this.window = flow === "ack" ? new AckWindow(win) : null;
    this.ctrl = { state: 0, seq: 0 }; this.pending = null; this.tick = 0; this.timer = null;
    this.stats = { flow, win: this.window ? win : null, sent: 0, backpressure_skipped: 0, window_skipped: 0, acks: 0, acks_ignored: 0, bad_messages: 0, rebases: 0, socket_errors: 0, bytes: 0,
      lateness_ms: [], build_ms: [], ctrl_wait_ms: [], ack_lag_ms: [], inflight_at_tick: [] };
    ws.on("message", (data, isBinary) => {
      const b = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data);
      const m = isBinary ? readClientMessage(b) : null;
      if (!m) { this.stats.bad_messages++; return; }
      if (m.kind === "control") { this.pending = { seq: m.seq, state: m.state, recvAt: performance.now() }; return; }
      if (!this.window) { this.stats.acks_ignored++; return; } // flow "none" has no window; a client that acks anyway is not an error
      const lag = this.window.ack(m.tick, performance.now());
      if (lag == null) this.stats.acks_ignored++; else { this.stats.acks++; this.stats.ack_lag_ms.push(lag); }
    });
    // A bad frame (too big, bad opcode, bad UTF-8) makes ws emit "error" on this connection only. Without a listener that is an
    // unhandled EventEmitter error and kills the whole measurement server; here it ends this stream and nothing else.
    ws.on("error", () => { this.stats.socket_errors++; this.stop(); ws.terminate(); });
    ws.on("close", () => this.stop());
    this.t0 = performance.now();
    this.step();
  }
  /** True iff this tick's frame may be sent under the flow rule. */
  canSend() { return this.window ? this.window.open() : this.ws.bufferedAmount <= this.maxBuffered; }
  step() {
    const due = this.t0 + (this.tick * 1000) / this.hz, now = performance.now();
    if (now < due - 0.3) { this.timer = setTimeout(() => this.step(), Math.max(0, due - now - 0.3)); return; }
    if (now - due > 250) { this.t0 = now - (this.tick * 1000) / this.hz; this.stats.rebases++; } // server stalled: do not burst-catch-up forever
    this.stats.lateness_ms.push(Math.max(0, now - due));
    if (this.pending) { this.ctrl = { state: this.pending.state, seq: this.pending.seq }; this.stats.ctrl_wait_ms.push(now - this.pending.recvAt); this.pending = null; }
    if (this.ws.readyState !== 1) return;
    if (this.window) this.stats.inflight_at_tick.push(this.window.inflight);
    if (!this.canSend()) this.stats[this.window ? "window_skipped" : "backpressure_skipped"]++;
    else {
      const b0 = performance.now(), buf = buildFrame(this.world, this.tick, this.ctrl, new ArrayBuffer(frameBytes(this.world.n)));
      this.stats.build_ms.push(performance.now() - b0);
      this.ws.send(buf, { binary: true, compress: false });
      if (this.window) this.window.sent(this.tick, performance.now());
      this.stats.sent++; this.stats.bytes += buf.byteLength;
    }
    this.tick++;
    this.step();
  }
  stop() { clearTimeout(this.timer); this.timer = null; }
}
