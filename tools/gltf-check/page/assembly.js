// Shared by the assembly evidence pages (skeleton.js, B-02; drive-car.js, B-03): place one glb per instance by its pose
// and fit a camera around the result.
import { Box3, Group, PerspectiveCamera, Vector3 } from "three";

/** A group that turns the Project frame (+Z up) into three.js's (+Y up): (x, y, z) -> (x, z, -y). Add it to the scene. */
export function projectFrame() {
  const world = new Group();
  world.rotation.x = -Math.PI / 2;
  return world;
}

/**
 * Load `${base}${inst.glb}` for every instance and place it inside `world` by `inst.pose` (Project frame). Returns per
 * instance where it ended up in the three.js frame (Y up), for the capture to compare with the pose.
 */
export async function placeInstances(loader, world, base, instances) {
  const placed = [];
  for (const inst of instances) {
    const gltf = await loader.loadAsync(`${base}${inst.glb}`);
    const part = gltf.scene.children[0]; // the part's root node; it carries the file's own Z-up to Y-up rotation
    part.quaternion.identity(); // inside `world` the part is in the Project frame already: drop the file's rotation
    const { position: p, orientation: q } = inst.pose;
    part.position.set(p.x, p.y, p.z);
    part.quaternion.set(q.x, q.y, q.z, q.w);
    world.add(gltf.scene);
    world.updateMatrixWorld(true);
    const at = part.getWorldPosition(new Vector3()); // three frame (Y up)
    const box = new Box3().setFromObject(part);
    placed.push({
      id: inst.id,
      pose_project: [p.x, p.y, p.z],
      world_position_yup: [at.x, at.y, at.z], // expected (x, z, -y)
      box_min_yup: box.min.toArray(),
      box_max_yup: box.max.toArray(),
    });
  }
  return placed;
}

/**
 * A camera looking at the scene from `dir` (three frame) that backs off until all 8 corners of the scene's bounding box
 * are inside `fit` of the half-frame (the rule of viewer.js). `reach()` is the largest |NDC| of those corners.
 */
export function fitCamera(scene, aspect, fit, dir = [-0.35, 0.45, 0.82]) {
  const bounds = new Box3().setFromObject(scene);
  const centre = bounds.getCenter(new Vector3());
  const corners = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => new Vector3(i & 1 ? bounds.max.x : bounds.min.x, i & 2 ? bounds.max.y : bounds.min.y, i & 4 ? bounds.max.z : bounds.min.z));
  const cam = new PerspectiveCamera(30, aspect, 0.01, 50);
  const place = (d) => { cam.position.set(centre.x + d * dir[0], centre.y + d * dir[1], centre.z + d * dir[2]); cam.lookAt(centre); cam.updateMatrixWorld(true); cam.updateProjectionMatrix(); };
  const reach = () => Math.max(...corners.map((c) => { const v = c.clone().project(cam); return Math.max(Math.abs(v.x), Math.abs(v.y)); }));
  let dist = bounds.getSize(new Vector3()).length() * 0.25;
  place(dist);
  while (reach() > fit) { dist *= 1.02; place(dist); }
  return { cam, bounds, dist, reach };
}
