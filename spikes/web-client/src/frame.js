// Spike pose-frame encoding "KPF-spike-1" (A0-02a). NOT the C-05b schema; it only fixes bytes for the measurement.
// Little-endian, one WebSocket binary message per tick, all bodies every frame (client-adapter.md 3.3, S1 scope).
//   offset 0  u32 tick            offset 16 u32 ctrl_state (channel 0 as applied by the core at this tick)
//   offset 4  u32 n_bodies        offset 20 u32 ctrl_seq   (last control message applied, for latency probes)
//   offset 8  f64 sim_time_s      offset 24 n_bodies x 7 x f32: x y z [m] (+Z up), qx qy qz qw (unit quaternion)
// Bytes per frame = 24 + 28 n.
export const HEADER = 24, BODY = 28;
export const frameBytes = (n) => HEADER + BODY * n;

export function writeHeader(buf, h) {
  const v = new DataView(buf);
  v.setUint32(0, h.tick, true); v.setUint32(4, h.n, true); v.setFloat64(8, h.simTime, true);
  v.setUint32(16, h.ctrlState, true); v.setUint32(20, h.ctrlSeq, true);
}

export function readHeader(buf) {
  const v = new DataView(buf);
  const h = { tick: v.getUint32(0, true), n: v.getUint32(4, true), simTime: v.getFloat64(8, true), ctrlState: v.getUint32(16, true), ctrlSeq: v.getUint32(20, true) };
  if (buf.byteLength !== frameBytes(h.n)) throw new Error(`frame length ${buf.byteLength} != ${frameBytes(h.n)} for n=${h.n}`);
  return h;
}

/** Float32 view of the pose block: 7 floats per body. Needs a 4-byte aligned offset (HEADER is). */
export const poseView = (buf, n) => new Float32Array(buf, HEADER, 7 * n);

// Client -> server messages (A0-02a-f). Little-endian, one WebSocket binary message each, the first u32 is the kind.
//   control  12 B: u32 kind=1, u32 seq, u32 state   (channel 0; A0-02a had the same two fields without the kind)
//   ack       8 B: u32 kind=2, u32 tick             (newest tick the client has drawn; cumulative: it also acks every older frame)
// Spike encoding like the frame above, NOT the C-05b schema.
export const MSG_CONTROL = 1, MSG_ACK = 2, CONTROL_BYTES = 12, ACK_BYTES = 8;
export function writeControl(seq, state) { const v = new DataView(new ArrayBuffer(CONTROL_BYTES)); v.setUint32(0, MSG_CONTROL, true); v.setUint32(4, seq, true); v.setUint32(8, state, true); return v.buffer; }
export function writeAck(tick) { const v = new DataView(new ArrayBuffer(ACK_BYTES)); v.setUint32(0, MSG_ACK, true); v.setUint32(4, tick, true); return v.buffer; }
/** `bytes`: a Uint8Array (a Buffer from ws). Returns { kind: "control", seq, state } | { kind: "ack", tick } | null for anything else. */
export function readClientMessage(bytes) {
  const v = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes.byteLength === CONTROL_BYTES && v.getUint32(0, true) === MSG_CONTROL) return { kind: "control", seq: v.getUint32(4, true), state: v.getUint32(8, true) };
  if (bytes.byteLength === ACK_BYTES && v.getUint32(0, true) === MSG_ACK) return { kind: "ack", tick: v.getUint32(4, true) };
  return null;
}
