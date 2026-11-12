// B-02 epic evidence: the glb of every instance of the structural skeleton, placed by the instance's pose (Project frame,
// +Z up, metres) and drawn once, with a caption that lists each part's mass and the total. The masses are read from
// manifest.json, which the engine wrote (`assembly_mass`); this page adds them up again and reports both
// (window.__SKELETON_RESULT) so the capture can assert caption, page sum and manifest total agree.
import { ACESFilmicToneMapping, Color, PMREMGenerator, Scene, WebGLRenderer } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { fitCamera, placeInstances, projectFrame } from "/page/assembly.js";

const fail = (e) => { window.__SKELETON_ERROR = String((e && e.stack) || e); };
addEventListener("error", (e) => fail(e.error ?? e.message));
addEventListener("unhandledrejection", (e) => fail(e.reason));

const FIT = 0.92; // every corner of the bounding box stays inside this fraction of the half-frame
const kg = (v) => v.toFixed(7);

try {
  const manifest = await (await fetch("/skeleton/manifest.json")).json();
  const canvas = document.getElementById("c");
  const renderer = new WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(1);
  renderer.toneMapping = ACESFilmicToneMapping;
  const scene = new Scene();
  scene.background = new Color(0x14181f);
  scene.environment = new PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

  const world = projectFrame();
  scene.add(world);
  const placed = (await placeInstances(new GLTFLoader(), world, "/skeleton/", manifest.instances)).map((p, k) => ({ ...p, mass_kg: manifest.instances[k].mass_kg }));

  // Caption: per-part masses and the total.
  const rows = manifest.instances.map((i) => `<tr><td>${i.id}</td><td>${i.part}</td><td>${i.material ?? "재료 없음(선언 질량)"}</td><td class="n">${kg(i.mass_kg)} kg</td></tr>`).join("");
  const pageSum = manifest.instances.reduce((s, i) => s + i.mass_kg, 0);
  document.getElementById("caption").innerHTML =
    `<b>부품별 질량 (mass_properties)과 총질량 (assembly_mass)</b>` +
    `<table><tr><th>인스턴스</th><th>부품</th><th>재료</th><th>질량</th></tr>${rows}` +
    `<tr class="total"><td>총질량</td><td></td><td>부품 질량의 합</td><td class="n" id="total">${kg(manifest.total_kg)} kg</td></tr></table>` +
    `<div id="note">질량은 시뮬(계산값)이고 입력은 ${manifest.input_badges.join("·")}입니다. 탑재체 질량은 사용자 선언이며 치수는 예시 값입니다. 총질량 = 부품 질량의 합, 결합과 자세는 질량을 더하지 않습니다</div>`;

  const { cam, bounds, dist, reach } = fitCamera(scene, canvas.width / canvas.height, FIT);
  renderer.render(scene, cam);
  const gl = renderer.getContext();
  window.__SKELETON_RESULT = {
    instances: placed, manifest_total_kg: manifest.total_kg, page_sum_kg: pageSum,
    caption_total_text: document.getElementById("total").textContent,
    caption_rows: manifest.instances.length,
    scene_box_min_yup: bounds.min.toArray(), scene_box_max_yup: bounds.max.toArray(),
    max_ndc: reach(), camera_distance_m: dist, gl: gl.getParameter(gl.VERSION),
  };
} catch (e) { fail(e); }
