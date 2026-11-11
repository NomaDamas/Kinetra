// A0-02c share page: loads a recorded bundle (bundle.json + poses.bin) and replays it with three.js. No physics, no core.
// Timeline marks (ms since navigation start, performance.now()) are exposed as window.__A0_02C_RESULT.
import { checkFirstFrame } from "./pixelcheck.js";
import { WebGLRenderer, Scene, PerspectiveCamera, Mesh, BoxGeometry, CylinderGeometry, PlaneGeometry, MeshLambertMaterial, HemisphereLight, DirectionalLight, Color, Quaternion, Vector3, Matrix4 } from "three";

const marks = { script_start: performance.now() };
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const fail = (e) => { window.__A0_02C_ERROR = String((e && e.stack) || e); };
addEventListener("error", (e) => fail(e.error ?? e.message));
addEventListener("unhandledrejection", (e) => fail(e.reason));

try {
  const [bundle, bin] = await Promise.all([
    fetch("/replay/bundle.json").then((r) => { if (!r.ok) throw new Error(`bundle.json ${r.status}`); return r.json(); }),
    fetch("/replay/poses.bin").then((r) => { if (!r.ok) throw new Error(`poses.bin ${r.status}`); return r.arrayBuffer(); }),
  ]);
  marks.fetched = performance.now();
  const BODIES = bundle.bodies.length, F = bundle.n_frames;
  if (bin.byteLength !== bundle.poses_bytes || bin.byteLength !== F * BODIES * 28) throw new Error("poses.bin has the wrong size");
  const digest = hex(await crypto.subtle.digest("SHA-256", bin)); // content-address check (client-adapter.md A2)
  if (digest !== bundle.poses_sha256) throw new Error("poses.bin sha256 mismatch");
  marks.verified = performance.now();
  const poses = new Float32Array(bin);

  const canvas = document.getElementById("c");
  const renderer = new WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(1); renderer.setSize(innerWidth, innerHeight, false);
  const scene = new Scene(); scene.background = new Color(0x14181f);
  scene.add(new HemisphereLight(0xffffff, 0x445566, 1.6));
  const sun = new DirectionalLight(0xffffff, 1.4); sun.position.set(0.4, -0.6, 1); scene.add(sun);
  const cam = new PerspectiveCamera(50, innerWidth / innerHeight, 0.5, 600);
  cam.up.set(0, 0, 1); cam.position.set(14, -26, 9); cam.lookAt(14, 0, 1.5); cam.updateMatrixWorld();

  const nodes = new Map(); // body name -> array of {mesh, local matrix}
  for (const g of bundle.geoms) {
    const color = new Color().setRGB(g.rgba[0], g.rgba[1], g.rgba[2]);
    const mat = new MeshLambertMaterial({ color });
    if (g.shape === "plane") { const m = new Mesh(new PlaneGeometry(400, 80), mat); m.position.set(100, 0, 0); scene.add(m); continue; }
    const geo = g.shape === "box" ? new BoxGeometry(2 * g.size_m[0], 2 * g.size_m[1], 2 * g.size_m[2]) : new CylinderGeometry(g.size_m[0], g.size_m[0], 2 * g.size_m[1], 20);
    if (g.shape === "cylinder") geo.rotateX(Math.PI / 2); // three cylinders stand along Y; MuJoCo's along its local Z
    const mesh = new Mesh(geo, mat); mesh.matrixAutoUpdate = false; scene.add(mesh);
    const local = new Matrix4().compose(new Vector3(...g.pos_m), new Quaternion(...g.quat_xyzw), new Vector3(1, 1, 1));
    (nodes.get(g.body) ?? nodes.set(g.body, []).get(g.body)).push({ mesh, local });
  }
  const bodyM = new Matrix4(), q = new Quaternion(), p = new Vector3(), one = new Vector3(1, 1, 1);
  function pose(frame) {
    bundle.bodies.forEach((name, b) => {
      const o = (frame * BODIES + b) * 7;
      bodyM.compose(p.set(poses[o], poses[o + 1], poses[o + 2]), q.set(poses[o + 3], poses[o + 4], poses[o + 5], poses[o + 6]), one);
      for (const n of nodes.get(name) ?? []) n.mesh.matrix.multiplyMatrices(bodyM, n.local);
    });
  }
  marks.scene_built = performance.now();

  const gl = renderer.getContext(), block = new Uint8Array(4 * 25), corner = new Uint8Array(4);
  const carScreen = new Vector3(poses[0], poses[1], poses[2]).project(cam);
  let first = true, t0 = 0, frame = 0;
  const loop = (t) => {
    if (first) t0 = t;
    const f = Math.floor(((t - t0) / 1000) / bundle.dt_s) % F; // 1x playback, loops
    pose(first ? 0 : f); renderer.render(scene, cam);
    if (first) {
      const cx = Math.round((carScreen.x + 1) / 2 * canvas.width), cy = Math.round((carScreen.y + 1) / 2 * canvas.height), R = 2;
      gl.readPixels(cx - R, cy - R, 2 * R + 1, 2 * R + 1, gl.RGBA, gl.UNSIGNED_BYTE, block); // forces the GPU work into the mark
      gl.readPixels(8, 8, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, corner);                           // ground, far from the car
      marks.first_frame = performance.now(); first = false;
      const check = checkFirstFrame(block, corner); // car-body red where frame 0 puts the car, and not red far from it
      const px = block.subarray(4 * (R * (2 * R + 1) + R), 4 * (R * (2 * R + 1) + R) + 4), pixelOk = check.ok;
      const nav = performance.getEntriesByType("navigation")[0];
      window.__A0_02C_RESULT = {
        marks, first_frame_pixel_ok: pixelOk, first_frame_pixel: [...px], first_frame_check: { ...check, corner_pixel: [...corner] }, webgl_renderer: (() => { const e = gl.getExtension("WEBGL_debug_renderer_info"); return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : null; })(),
        navigation: { response_start: nav.responseStart, dom_content_loaded: nav.domContentLoadedEventEnd, load_event_end: nav.loadEventEnd },
        resources: performance.getEntriesByType("resource").map((r) => ({ url: new URL(r.name).pathname, start: r.startTime, response_end: r.responseEnd, transfer_size: r.transferSize, encoded_body_size: r.encodedBodySize, decoded_body_size: r.decodedBodySize })),
        frames: F, bodies: BODIES,
      };
    }
    frame = f; window.__frame = frame;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
} catch (e) { fail(e); }
