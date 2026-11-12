// Fixed-step accumulator of the requestAnimationFrame loop, as a pure function so the "dropped sim time" accounting is tested.
//
// acc          sim seconds owed from earlier frames
// frameMs      real time since the previous frame
// dt           sim step [s]
// maxSteps     most steps run in one frame; also bounds how much real time one frame may add (maxSteps*dt)
// Returns { steps, acc, droppedS, capped }:
//   droppedS  sim time that real time called for but this frame did not simulate, i.e.
//             (a) real time beyond maxSteps*dt in the frame interval (clipped) and
//             (b) the remainder still owed after maxSteps steps (discarded: acc is reset to 0).
//   capped    true when droppedS > 0, i.e. the loop fell behind real time on this frame.
export function planFrame(acc, frameMs, dt, maxSteps) {
  const addable = Math.min(frameMs, maxSteps * dt * 1000);
  let dropped = (frameMs - addable) / 1000;
  acc += addable / 1000;
  let steps = 0;
  while (acc >= dt && steps < maxSteps) { acc -= dt; steps++; }
  if (steps === maxSteps && acc >= dt) { dropped += acc; acc = 0; }
  return { steps, acc, droppedS: dropped, capped: dropped > 0 };
}
