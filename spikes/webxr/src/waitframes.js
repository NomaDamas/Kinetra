// Wait for `n` more XR frames in the page. Self-contained on purpose: driver.mjs sends `waitForFrames.toString()` into the
// page, so it must not reference anything outside its own body. It takes the page's `win` and timer functions so the offline
// tests can run the same function against a fake window.
//   resolves with the frame count once `win.__xr.frames` has advanced by n
//   rejects with a clear message when `win.__xr.error` is set (a page error) or after `timeoutMs` without enough frames
export function waitForFrames(win, n, timeoutMs, raf, setTimer, clearTimer) {
  return new Promise((resolve, reject) => {
    const target = win.__xr.frames + n;
    let done = false;
    const finish = (fn, v) => { if (done) return; done = true; clearTimer(timer); fn(v); };
    const timer = setTimer(() => finish(reject, new Error(`timed out after ${timeoutMs} ms waiting for ${n} XR frame(s): got ${win.__xr.frames - (target - n)}, page error: ${win.__xr.error ?? "none"}`)), timeoutMs);
    const tick = () => {
      if (done) return;
      if (win.__xr.error) return finish(reject, new Error(`page error while waiting for ${n} XR frame(s): ${win.__xr.error}`));
      if (win.__xr.frames >= target) return finish(resolve, win.__xr.frames);
      raf(tick);
    };
    tick();
  });
}
