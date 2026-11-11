// B-03 epic evidence: the drive car, one glb per instance placed by its pose (assembly.js, as the B-02 skeleton), with a
// side table: the parts list (instance, part, role) and the key specs of each drive part as the part definitions state
// them (value, unit, badge, source). Every number and source comes from manifest.json, which the generator wrote from
// the project's part definitions; this page reports what it shows (window.__DRIVE_CAR_RESULT) so the capture can assert
// the table says what the manifest says.
import { ACESFilmicToneMapping, Color, PMREMGenerator, Scene, WebGLRenderer } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { fitCamera, placeInstances, projectFrame } from "/page/assembly.js";

const fail = (e) => { window.__DRIVE_CAR_ERROR = String((e && e.stack) || e); };
addEventListener("error", (e) => fail(e.error ?? e.message));
addEventListener("unhandledrejection", (e) => fail(e.reason));

const FIT = 0.9;
const SOURCE_CHARS = 110; // the table shows the start of each source; the cell's title holds all of it
/** Six significant digits, no trailing zeros (drive-car.ts `fmt` is the same rule). */
const fmt = (v) => String(Number(v.toPrecision(6)));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const ROLE_KO = { wheel: "휠", motor: "모터", thruster: "추력기", battery: "배터리", tank: "탱크", spring_damper: "스프링-댐퍼" };

try {
  const manifest = await (await fetch("/drive-car/manifest.json")).json();
  const canvas = document.getElementById("c");
  const renderer = new WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(1);
  renderer.toneMapping = ACESFilmicToneMapping;
  const scene = new Scene();
  scene.background = new Color(0x14181f);
  scene.environment = new PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

  const world = projectFrame();
  scene.add(world);
  const placed = await placeInstances(new GLTFLoader(), world, "/drive-car/", manifest.instances);

  // Parts list: one row per part, with the instances that use it.
  const byPart = new Map();
  for (const i of manifest.instances) {
    if (!byPart.has(i.part)) byPart.set(i.part, { name: i.part_name, role: i.role, ids: [] });
    byPart.get(i.part).ids.push(i.id);
  }
  const partRows = [...byPart.entries()].map(([pid, p]) =>
    `<tr class="part"><td>${esc(p.name)}<br><span class="src">${esc(pid)}</span></td><td>${p.role ? ROLE_KO[p.role] ?? p.role : "몸체"}</td><td class="n">${p.ids.length}</td><td class="src">${p.ids.map(esc).join(", ")}</td></tr>`).join("");

  // Key specs: value, unit, badge and source as the part definitions state them.
  const specRows = manifest.specs.map((s, k) => {
    const shown = s.source_ref.length > SOURCE_CHARS ? `${s.source_ref.slice(0, SOURCE_CHARS)}…` : s.source_ref;
    const where = s.source_locator ? ` [${s.source_locator}]` : "";
    return `<tr class="spec" data-k="${k}"><td>${esc(s.part_name)}</td><td>${esc(s.name)}</td>` +
      `<td class="n value" data-value="${s.value}">${fmt(s.value)} ${esc(s.unit)}</td>` +
      `<td><span class="badge ${s.badge}" data-badge="${s.badge}">${esc(s.badge_label)}</span></td>` +
      `<td class="src source" title="${esc(s.source_ref)}">${esc(shown)}${esc(where)}</td></tr>`;
  }).join("");
  const supplies = manifest.actuators.filter((a) => a.supply).map((a) => `${esc(a.instance)} ← ${esc(a.supply)}`).join(", ");
  document.getElementById("side").innerHTML =
    `<b>부품 목록</b><table><tr><th>부품</th><th>역할</th><th>수</th><th>인스턴스</th></tr>${partRows}</table>` +
    `<b>구동 부품의 주요 사양 (부품 정의의 값·배지·출처)</b>` +
    `<table><tr><th>부품</th><th>사양</th><th>값</th><th>배지</th><th>출처</th></tr>${specRows}</table>` +
    `<div id="note">공급: ${supplies}. 결합: ${manifest.joints.filter((j) => j.kind === "hinge").length}개 힌지, ${manifest.joints.filter((j) => j.kind === "fixed").length}개 고정. ` +
    `배지: 인용 = 출처 문서의 값, 추정 = 방법을 적은 계산, 기본값 = Kinetra가 고른 값, 시뮬 = 엔진이 계산한 값. 차대와 축 토막은 이 예시의 사용자 선언 부품이고 치수는 실제 차량의 값이 아닙니다</div>`;

  const { cam, bounds, dist, reach } = fitCamera(scene, canvas.width / canvas.height, FIT, [0.62, 0.5, 0.72]);
  renderer.render(scene, cam);
  const gl = renderer.getContext();
  window.__DRIVE_CAR_RESULT = {
    instances: placed,
    part_rows: document.querySelectorAll("#side tr.part").length,
    part_instances: [...byPart.values()].reduce((n, p) => n + p.ids.length, 0),
    specs: [...document.querySelectorAll("#side tr.spec")].map((tr) => ({
      part_name: tr.children[0].textContent,
      name: tr.children[1].textContent,
      value: Number(tr.querySelector(".value").dataset.value),
      value_text: tr.querySelector(".value").textContent,
      badge: tr.querySelector(".badge").dataset.badge,
      badge_text: tr.querySelector(".badge").textContent,
      source_title: tr.querySelector(".source").title,
      source_text: tr.querySelector(".source").textContent,
    })),
    scene_box_min_yup: bounds.min.toArray(), scene_box_max_yup: bounds.max.toArray(),
    max_ndc: reach(), camera_distance_m: dist, gl: gl.getParameter(gl.VERSION),
  };
} catch (e) { fail(e); }
