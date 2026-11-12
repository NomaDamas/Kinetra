/** rAF frame intervals. `start()` begins a measurement window: the first frame inside it only sets the reference, so the
 *  time since the last warm-up frame is never an interval of the window. */
export class IntervalRecorder {
  constructor() { this.last = null; this.dt = []; this.recording = false; }
  start() { this.recording = true; this.last = null; }
  stop() { this.recording = false; }
  frame(t) { if (this.recording) { if (this.last !== null) this.dt.push(t - this.last); this.last = t; } }
}
