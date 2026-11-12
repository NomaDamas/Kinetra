// Minimal canvas-2D side view (x-z plane) of the car so the frame-rate loop includes a real draw call per frame.
// Not a renderer benchmark: no WebGL, no Three.js (that is A0-02a's scope).
const L = 4.2, W = 1.9, H = 1.2; // chassis box of model/rocket_car.xml (side-view sketch; the 0.08 m box offset is ignored)
const CORNERS = [];
for (const x of [-L / 2, L / 2]) for (const y of [-W / 2, W / 2]) for (const z of [-H / 2, H / 2]) CORNERS.push([x, y, z]);
const EDGES = [[0, 1], [2, 3], [4, 5], [6, 7], [0, 2], [1, 3], [4, 6], [5, 7], [0, 4], [1, 5], [2, 6], [3, 7]];

export function drawCar(ctx, w, h, qpos, ctrl) {
  const px = qpos[0], pz = qpos[2], qw = qpos[3], qx = qpos[4], qy = qpos[5], qz = qpos[6];
  const R = [
    [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qw * qz), 2 * (qx * qz + qw * qy)],
    [2 * (qx * qy + qw * qz), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qw * qx)],
    [2 * (qx * qz - qw * qy), 2 * (qy * qz + qw * qx), 1 - 2 * (qx * qx + qy * qy)],
  ];
  const s = 38; // px per metre
  const gx = (x) => w / 2 + (x - px) * s;
  const gz = (z) => h - 30 - z * s;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#888"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(0, gz(0)); ctx.lineTo(w, gz(0)); ctx.stroke();
  const P = CORNERS.map(([x, y, z]) => [px + R[0][0] * x + R[0][1] * y + R[0][2] * z, pz + R[2][0] * x + R[2][1] * y + R[2][2] * z]);
  ctx.strokeStyle = "#c33"; ctx.lineWidth = 1.5; ctx.beginPath();
  for (const [a, b] of EDGES) { ctx.moveTo(gx(P[a][0]), gz(P[a][1])); ctx.lineTo(gx(P[b][0]), gz(P[b][1])); }
  ctx.stroke();
  let burn = 0; for (let i = 0; i < ctrl.length; i++) burn += ctrl[i];
  ctx.fillStyle = "#222"; ctx.font = "12px monospace";
  ctx.fillText(`x=${px.toFixed(1)} m  z=${pz.toFixed(2)} m  burn=${burn.toFixed(2)}`, 8, 16);
}
