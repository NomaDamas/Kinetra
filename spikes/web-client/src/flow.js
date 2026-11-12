// Ack-based send window (A0-02a-f / #420). Shared by the synthetic core (stream.mjs) and the measurement page (client-pose.js).
// Spike mechanism, NOT the C-05b schema: it exists to measure what an `ack` field in the frame protocol would buy.
//
// Rule: the core keeps at most `win` frames that the client has not acked. A tick with no free slot is SKIPPED, not queued, so the
// frame sent when a slot frees up is always the newest tick ("latest frame first"; nothing stale waits behind it).
// The client acks the tick it just drew. An ack is cumulative: tick T acks every sent frame with tick <= T.

export const MAX_WINDOW = 16;
export const FLOWS = ["none", "ack"];

/** Server side. Frames sent and not yet acked, oldest first. */
export class AckWindow {
  constructor(win) {
    if (!Number.isInteger(win) || win < 1 || win > MAX_WINDOW) throw new RangeError(`ack window must be an integer in 1..${MAX_WINDOW}, got ${win}`);
    this.win = win; this.queue = []; this.acked = -1; this.max_inflight = 0;
  }
  get inflight() { return this.queue.length; }
  /** True iff a frame may be sent now. */
  open() { return this.queue.length < this.win; }
  /** Record that the frame for `tick` was sent at `t` (ms). Ticks must increase. */
  sent(tick, t) {
    const last = this.queue.at(-1);
    if (last && tick <= last.tick) throw new RangeError(`tick ${tick} is not after the last sent tick ${last.tick}`);
    this.queue.push({ tick, t });
    if (this.queue.length > this.max_inflight) this.max_inflight = this.queue.length;
  }
  /** Apply a cumulative ack at `t`. Returns the ack lag in ms (`t` minus the send time of the frame with tick `tick`), or null when
   *  the ack is not valid: not an integer, not after the last acked tick, or for a tick that was never sent (above the newest sent tick, or below the oldest unacked one). Invalid acks change nothing,
 *  not even `acked`. */
  ack(tick, t) {
    if (!Number.isInteger(tick) || tick <= this.acked) return null;
    const last = this.queue.at(-1);
    if (!last || tick > last.tick) return null;
    if (this.queue[0].tick > tick) return null; // no sent, unacked frame at or below this tick: it was never sent (the core skipped it) or is already acked, nothing to free
    let hit = null;
    while (this.queue.length && this.queue[0].tick <= tick) hit = this.queue.shift();
    this.acked = tick;
    return t - hit.t;
  }
}

/** Client side. Decides which drawn tick to ack: each newly drawn tick once, never an older or repeated one. */
export class AckSender {
  constructor() { this.last = -1; this.count = 0; }
  /** `tick` is the tick of the frame the draw just used. Returns the tick to send in an ack, or null (same frame drawn again). */
  onDraw(tick) {
    if (tick <= this.last) return null;
    this.last = tick; this.count++;
    return tick;
  }
}
