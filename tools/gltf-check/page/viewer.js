// Loads the committed part fixtures with three.js's GLTFLoader, lines them up along x and draws them once.
// Reports what the loader made of each material and how many voids each file lists but does not draw
// (window.__GLTF_RESULT), so the capture can assert it. A void is drawn as a wire outline (client-adapter.md A7).
import { ACESFilmicToneMapping, BoxGeometry, Box3, Color, CylinderGeometry, EdgesGeometry, LineBasicMaterial, LineSegments, PerspectiveCamera, PMREMGenerator, Quaternion, Scene, SphereGeometry, Vector3, WebGLRenderer } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const fail = (e) => { window.__GLTF_ERROR = String((e && e.stack) || e); };
addEventListener("error", (e) => fail(e.error ?? e.message));
addEventListener("unhandledrejection", (e) => fail(e.reason));

const FIT = 0.92; // every corner of the bounding box stays inside this fraction of the half-frame

/** Wire outline of a void in the part-local frame (+Z up, metres), as `extras.kinetra.voids[i]` states it. */
function voidOutline(v) {
  const d = v.dimensions;
  let geo;
  if (v.primitive === "box") geo = new BoxGeometry(d.size_x, d.size_y, d.size_z);
  else if (v.primitive === "cylinder") { geo = new CylinderGeometry(d.radius, d.radius, d.length, 32); geo.rotateX(Math.PI / 2); } // three stands cylinders along Y, the recipe along local Z
  else geo = new SphereGeometry(d.radius, 24, 12);
  const line = new LineSegments(new EdgesGeometry(geo, 20), new LineBasicMaterial({ color: 0xffb020 }));
  line.position.set(v.center.x, v.center.y, v.center.z);
  line.quaternion.set(v.orientation.x, v.orientation.y, v.orientation.z, v.orientation.w);
  return line;
}

try {
  const names = new URL(location.href).searchParams.get("files").split(",");
  const canvas = document.getElementById("c");
  const renderer = new WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(1);
  renderer.toneMapping = ACESFilmicToneMapping;
  const scene = new Scene();
  scene.background = new Color(0x14181f);
  scene.environment = new PMREMGenerator(renderer).fromScene(new RoomEnvironment(), 0.04).texture;

  const loader = new GLTFLoader();
  const results = [];
  let cursor = 0;
  for (const name of names) {
    const gltf = await loader.loadAsync(`/fixtures/${name}.glb`);
    const root = gltf.scene;
    const part = root.children[0]; // the part's root node: its userData is the file's extras
    const kinetra = part.userData.kinetra;
    const box = new Box3().setFromObject(root);
    const size = box.getSize(new Vector3());
    root.position.x += cursor - box.min.x;
    cursor += size.x + 0.15;
    scene.add(root);
    const materials = new Set();
    root.traverse((o) => { if (o.isMesh) materials.add(o.material); });
    const [m] = [...materials];
    for (const v of kinetra.voids) { part.add(voidOutline(v)); }
    results.push({
      name, materials: materials.size, meshes: part.children.filter((c) => c.isMesh || c.children.some((k) => k.isMesh)).length,
      color_linear: [m.color.r, m.color.g, m.color.b], metalness: m.metalness, roughness: m.roughness, ior: m.ior ?? null,
      size_m: [size.x, size.y, size.z], voids: kinetra.voids.length,
    });
  }
  const undrawn = results.reduce((n, r) => n + r.voids, 0);
  document.getElementById("label").textContent = `B-01c: 부품 정의에서 만든 glTF를 three.js가 읽은 것. 시각 메시이며 판정이 아닙니다. 빈 곳 ${undrawn}개는 파내지 않고 주황 외곽선으로만 표시했습니다`;

  // Camera: the vertical field of view (30 degrees) is the tight one; move back until all 8 corners of the scene's
  // bounding box (void outlines lie inside the material, so they do not enlarge it) are inside FIT of the half-frame.
  const bounds = new Box3().setFromObject(scene);
  const centre = bounds.getCenter(new Vector3());
  const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => new Vector3(i & 1 ? bounds.max.x : bounds.min.x, i & 2 ? bounds.max.y : bounds.min.y, i & 4 ? bounds.max.z : bounds.min.z));
  const cam = new PerspectiveCamera(30, canvas.width / canvas.height, 0.01, 50);
  const place = (d) => { cam.position.set(centre.x - d * 0.1, centre.y + d * 0.5, centre.z + d * 0.86); cam.lookAt(centre); cam.updateMatrixWorld(true); cam.updateProjectionMatrix(); };
  const reach = () => Math.max(...corners.map((c) => { const v = c.clone().project(cam); return Math.max(Math.abs(v.x), Math.abs(v.y)); }));
  let dist = bounds.getSize(new Vector3()).length() * 0.25;
  place(dist);
  while (reach() > FIT) { dist *= 1.02; place(dist); }
  renderer.render(scene, cam);
  const gl = renderer.getContext();
  window.__GLTF_RESULT = { results, undrawn_voids: undrawn, max_ndc: reach(), camera_distance_m: dist, gl: gl.getParameter(gl.VERSION) };
} catch (e) { fail(e); }
