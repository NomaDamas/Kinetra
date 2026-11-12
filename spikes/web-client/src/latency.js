/** Latency bookkeeping for overlapping control inputs (pure, no DOM). A drawn frame echoes the last input the core applied
 *  (`ctrlSeq`, `ctrlState`). Rules:
 *   - only the input whose seq the drawn frame echoes can become a sample, and only if the marker was verified at the new spot
 *     (`visible(state)`) AND it actually moved: the state verified on screen before this draw (`shown`) differs from the input's state;
 *   - same state as already on screen -> `no_visible_change` (e.g. input 2 undid input 1 before input 1 was ever drawn);
 *   - every older pending input (seq < echoed seq) is `superseded`: the core replaced it before it was shown;
 *   - anything still pending when measurement ends is `unresolved`.
 *  `shown` is the state last verified on screen (null = unknown: such an input is counted `unverified_start`, never a sample). */
export class LatencyTracker {
  constructor(shown = null) { this.shown = shown; this.pending = new Map(); this.samples = []; this.superseded = 0; this.noVisibleChange = 0; this.unverifiedStart = 0; this.inputs = 0; }
  input(rec) { this.inputs++; this.pending.set(rec.seq, rec); }
  /** `visible(state)`: true iff the marker is drawn at `state`'s spot and not at the other one (read from pixels). Returns the sample or null. */
  onDraw(frame, visible, stamp) {
    let sample = null;
    const rec = this.pending.get(frame.ctrlSeq);
    if (rec && frame.ctrlState === rec.state && visible(rec.state)) {
      this.pending.delete(rec.seq);
      if (this.shown === null) this.unverifiedStart++;
      else if (this.shown !== rec.state) { sample = { ...rec, ...stamp }; this.samples.push(sample); }
      else this.noVisibleChange++;
      this.shown = rec.state;
    }
    for (const seq of [...this.pending.keys()]) if (seq < frame.ctrlSeq) { this.pending.delete(seq); this.superseded++; }
    return sample;
  }
  /** Idle refresh: with nothing pending the screen state is read from pixels. */
  refresh(seen) { if (!this.pending.size) this.shown = seen; }
  counts() { return { inputs: this.inputs, measured: this.samples.length, superseded: this.superseded, no_visible_change: this.noVisibleChange, unverified_start: this.unverifiedStart, unresolved: this.pending.size }; }
}
