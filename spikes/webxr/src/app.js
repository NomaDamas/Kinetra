// Spike page (A0-02b): one three.js scene, @pmndrs/xr for input, IWER (Meta's WebXR emulator) as the headset.
// Not product UI. window.__xr is plain data (page.evaluate can return it); the live objects are on window.__xrObjects.
import { AmbientLight, Mesh, MeshBasicMaterial, PerspectiveCamera, PlaneGeometry, Scene, WebGLRenderer } from "three";
import { XROrigin, createXRStore } from "@pmndrs/xr";
import { XRDevice, metaQuest3 } from "iwer";
import { createPart, makeGrabbable } from "./scene.js";

const state = {
  ready: false,
  error: null,
  frames: 0, // animation-loop calls that carried an XRFrame
  frameTimesMs: [], // `time` argument of those calls (DOMHighResTimeStamp), first 2000
  grabStarts: 0, // handle interactions that started (state.first)
  grabEnds: 0,
  gripWorld: null, // right-grip position in the reference space [x, y, z], read from the current XRFrame
  gripAtGrab: null, // gripWorld on the frame the grab started
  nativeXrBeforeInstall: typeof navigator.xr !== "undefined", // Chromium ships its own navigator.xr; IWER must override it
  sessionActive: false,
};
window.__xr = state;
window.addEventListener("error", (e) => { state.error ??= String(e.message); });
window.addEventListener("unhandledrejection", (e) => { state.error ??= String(e.reason?.message ?? e.reason); });

// The emulated headset. forceInstall: Chromium (even the headless shell) ships its own navigator.xr, which IWER would
// otherwise leave in place. Mono rendering (stereoEnabled false is the default) keeps the software-rendered frame cheap.
const device = new XRDevice(metaQuest3);
device.installRuntime({ forceInstall: true });

const canvas = document.getElementById("c");
const renderer = new WebGLRenderer({ canvas, antialias: false });
renderer.xr.enabled = true;

const scene = new Scene();
scene.add(new AmbientLight(0xffffff, 1));
const floor = new Mesh(new PlaneGeometry(4, 4), new MeshBasicMaterial({ color: 0x222a33 }));
floor.rotation.x = -Math.PI / 2; // no pointer listeners: never a grab target
scene.add(floor);

const camera = new PerspectiveCamera(70, 1, 0.01, 100);
const origin = new XROrigin(camera);
scene.add(origin);

const part = createPart();
scene.add(part);
const { handle } = makeGrabbable(part, (s) => {
  if (s.first) { state.grabStarts++; state.gripAtGrab = state.gripWorld; }
  if (s.last) state.grabEnds++;
});

// emulate:false because we installed IWER ourselves (otherwise pmndrs injects its own on localhost and shows a dev UI).
// baseAssetPath: controller layouts come from the local server, not the jsdelivr default (the test has no network).
// model:false: no controller .glb is fetched; the layout JSON is still needed for the gamepad mapping.
const store = createXRStore(canvas, scene, () => camera, renderer.xr, {
  emulate: false,
  offerSession: false,
  htmlInput: false,
  hand: false,
  controller: { model: false, rayPointer: false, teleportPointer: false },
  baseAssetPath: `${location.origin}/profiles/`,
  frameBufferScaling: "low",
  anchors: false, handTracking: false, layers: false, meshDetection: false, planeDetection: false, hitTest: false, domOverlay: false,
});
store.onSessionEnd(() => { state.sessionActive = false; });
window.__xrObjects = { device, store, part, handle };

let prev;
renderer.setAnimationLoop((time, frame) => {
  const delta = prev == null ? 0 : time - prev;
  prev = time;
  if (frame) {
    // The grip pose of this frame, read before store.update so the grab callback sees the pose the pointer used.
    const right = store.getState().inputSourceStates.find((s) => s.type === "controller" && s.inputSource.handedness === "right");
    const refSpace = store.getState().originReferenceSpace;
    const grip = right?.inputSource.gripSpace;
    const pose = grip && refSpace ? frame.getPose(grip, refSpace) : null;
    state.gripWorld = pose ? [pose.transform.position.x, pose.transform.position.y, pose.transform.position.z] : null;
    state.frames++;
    if (state.frameTimesMs.length < 2000) state.frameTimesMs.push(time);
  }
  store.update(frame, delta); // turns controller input into pointer events
  handle.update(time); // applies them to the part
  renderer.render(scene, camera);
});

document.getElementById("enter").addEventListener("click", async () => {
  try {
    await store.enterVR();
    state.sessionActive = true;
  } catch (e) {
    state.error = String(e?.message ?? e);
  }
});
state.ready = true;
