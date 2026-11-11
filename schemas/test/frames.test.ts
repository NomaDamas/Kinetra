// C-05b: a TypeScript client reads the run stream with the generated types: the recorded run (JSON lines) and the
// binary frame. `pnpm lint` type-checks every access below against types.ts; the Python tests
// (packages/engine/tests/test_frames.py) are the judge of validity.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { BodyPose, ContactEvent, Frame, PlatformTag, RunCompleted, RunEnded, RunFailed, RunStarted, ServerMessage, TrajectoryEvidence } from "../types.ts";

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const fixtures = "../../packages/engine/tests/fixtures/frames/";

const messages: ServerMessage[] = readFileSync(here(`${fixtures}run.jsonl`), "utf8")
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line));

const startedOf = (): RunStarted => {
  const m = messages.find((x): x is RunStarted => x.type === "run_started");
  assert.ok(m);
  return m;
};

/** The binary layout of client-adapter.md 3.3.1, little-endian. A body's pose is x y z qx qy qz qw (float32). */
function readBinaryFrame(buf: ArrayBuffer, bodies: string[]): Frame {
  const v = new DataView(buf);
  assert.equal(v.getUint8(0), 1, "binary frame version");
  const tick = v.getUint32(4, true);
  const n = v.getUint32(8, true);
  const eventBytes = v.getUint32(12, true);
  const simTime = v.getFloat64(16, true);
  assert.equal(n, bodies.length);
  assert.equal(buf.byteLength, 24 + 28 * n + eventBytes);
  const floats = new Float32Array(buf, 24, 7 * n); // 24 is a multiple of 4: a view, not a copy
  const events = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 24 + 28 * n, eventBytes)));
  const at = (i: number, k: number): number => floats[7 * i + k] ?? NaN;
  return {
    type: "frame",
    run_id: "binary",
    tick,
    sim_time_s: simTime,
    poses: bodies.map((body, i) => ({
      body,
      position: { x: at(i, 0), y: at(i, 1), z: at(i, 2) },
      orientation: { x: at(i, 3), y: at(i, 4), z: at(i, 5), w: at(i, 6) },
    })),
    events,
  };
}

test("the recorded run is a run_started, frames and a run_ended, told apart by type", () => {
  assert.equal(messages[0]?.type, "run_started");
  assert.equal(messages[messages.length - 1]?.type, "run_ended");
  const frames = messages.filter((m): m is Frame => m.type === "frame");
  assert.ok(frames.length > 10);
  const ticks = frames.map((f) => f.tick);
  assert.deepEqual(ticks, [...ticks].sort((a, b) => a - b));
});

test("run_started carries all eight platform tag components, and run_ended pairs the hash with a tag", () => {
  const started = startedOf();
  const ended = messages.find((m): m is RunEnded => m.type === "run_ended");
  assert.ok(ended);
  const components: (keyof PlatformTag)[] = ["os", "cpu", "image_digest", "engine", "runtime", "core_build", "compute", "threads"];
  assert.deepEqual(Object.keys(started.platform), components);
  const end = ended.end;
  assert.ok(end.reason === "completed", "a completed run"); // narrows `end` to RunCompleted: the trajectory is there
  assert.deepEqual(end.trajectory.platform, started.platform);
  // @ts-expect-error a trajectory is the hash and its tag; the hash alone is not a TrajectoryEvidence
  const bare: TrajectoryEvidence = { hash: end.trajectory.hash };
  // @ts-expect-error a completed run requires its trajectory
  const noTrajectory: RunCompleted = { reason: "completed" };
  const failed: RunFailed = { reason: "failed" }; // only a failed run has none
  // @ts-expect-error a failed run has no trajectory to claim
  const claimed: RunFailed = { reason: "failed", trajectory: end.trajectory };
  void [bare, noTrajectory, failed, claimed];
});

test("events are told apart by kind and the three kinds of the DoD occur", () => {
  const kinds = new Set<string>();
  for (const m of messages) {
    if (m.type !== "frame") continue;
    for (const e of m.events ?? []) {
      kinds.add(e.kind);
      if (e.kind === "break") assert.equal(e.load.unit, "N"); // narrowed by the kind tag
    }
  }
  assert.deepEqual([...kinds].sort(), ["break", "condition_met", "contact"]);
});

test("a contact's other side is told apart by kind; a body or a prop has an id, the ground has none", () => {
  const ground: ContactEvent = { kind: "contact", tick: 1, phase: "begin", body: "wheel-fl", other: { kind: "ground" } };
  const prop: ContactEvent = { kind: "contact", tick: 1, phase: "begin", body: "wheel-fl", other: { kind: "prop", id: "prop-a" } };
  // @ts-expect-error a prop needs an id
  const noId: ContactEvent = { kind: "contact", tick: 1, phase: "begin", body: "wheel-fl", other: { kind: "prop" } };
  // @ts-expect-error the ground has no id
  const groundId: ContactEvent = { kind: "contact", tick: 1, phase: "begin", body: "wheel-fl", other: { kind: "ground", id: "g" } };
  void [noId, groundId];
  assert.equal(ground.other.kind, "ground");
  if (prop.other.kind !== "ground") assert.equal(prop.other.id, "prop-a"); // narrowed by `kind`
});

test("an engine tag requires what its distribution identifies it by", () => {
  const started = startedOf();
  const engine = started.platform.engine;
  if (engine.distribution === "custom_build") assert.equal(typeof engine.compiler, "string");
  else assert.match(engine.artifact_hash, /^sha256:/); // narrowed by `distribution`
  // @ts-expect-error a wheel is identified by the hash of its file
  const noHash: PlatformTag["engine"] = { name: "e", version: "1", distribution: "wheel" };
  void noHash;
});

test("the binary frame reads with the documented layout; the quaternion is x, y, z, w", () => {
  const started = startedOf();
  const file = readFileSync(here(`${fixtures}frame-0000.bin`));
  const buf = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);
  const frame = readBinaryFrame(buf, started.bodies.map((b) => b.id));
  assert.equal(frame.tick, 0);
  const wheel = frame.poses.find((p) => p.body === "wheel-rl");
  assert.ok(wheel);
  assert.ok(Math.abs(wheel.orientation.x - Math.SQRT1_2) < 1e-6 && Math.abs(wheel.orientation.w - Math.SQRT1_2) < 1e-6);
  const json = messages.find((m): m is Frame => m.type === "frame");
  assert.ok(json);
  for (const [i, p] of frame.poses.entries()) {
    const q: BodyPose | undefined = json.poses[i];
    assert.ok(q);
    assert.ok(Math.abs(p.position.z - q.position.z) < 1e-6);
  }
});
