// Loads the committed part fixtures with three.js's GLTFLoader, lines them up along x and draws them once.
// Reports what the loader made of each material (window.__GLTF_RESULT) so the capture can assert it.
import { ACESFilmicToneMapping, Box3, Color, PerspectiveCamera, PMREMGenerator, Scene, Vector3, WebGLRenderer } from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

const fail = (e) => { window.__GLTF_ERROR = String((e && e.stack) || e); };
addEventListener("error", (e) => fail(e.error ?? e.message));
addEventListener("unhandledrejection", (e) => fail(e.reason));

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
    const box = new Box3().setFromObject(root);
    const size = box.getSize(new Vector3());
    root.position.x += cursor - box.min.x;
    cursor += size.x + 0.15;
    scene.add(root);
    const materials = new Set();
    root.traverse((o) => { if (o.isMesh) materials.add(o.material); });
    const [m] = [...materials];
    results.push({
      name, materials: materials.size, meshes: root.children[0]?.children?.length ?? 0,
      color_linear: [m.color.r, m.color.g, m.color.b], metalness: m.metalness, roughness: m.roughness, ior: m.ior ?? null,
      size_m: [size.x, size.y, size.z],
    });
  }
  const whole = new Box3().setFromObject(scene);
  const centre = whole.getCenter(new Vector3()), span = whole.getSize(new Vector3());
  const cam = new PerspectiveCamera(30, canvas.width / canvas.height, 0.01, 50);
  const dist = span.x * 0.9; // the row fills the 71 degree horizontal field of view with a margin
  cam.position.set(centre.x - dist * 0.1, centre.y + dist * 0.5, centre.z + dist * 0.86);
  cam.lookAt(centre);
  renderer.render(scene, cam);
  window.__GLTF_RESULT = { results, gl: renderer.getContext().getParameter(renderer.getContext().VERSION) };
} catch (e) { fail(e); }
