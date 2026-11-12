// Shared by the assembly evidence captures (skeleton.ts, B-02; drive-car.ts, B-03): the placement check of page/assembly.js.

export interface PlacedInstance {
  id: string;
  pose_project: number[];
  world_position_yup: number[];
  box_min_yup: number[];
  box_max_yup: number[];
}

export interface ManifestPose {
  id: string;
  pose: { position: { x: number; y: number; z: number } };
}

/**
 * Every instance of the manifest (the engine's poses) is drawn exactly once and where the manifest puts it: the set of
 * drawn ids equals the manifest's (no missing, extra or repeated instance), and each drawn instance's world position is
 * the manifest pose of the same id turned into three.js's Y up, (x, y, z) -> (x, z, -y). The page's own `pose_project`
 * is not trusted: it must equal the manifest's too. Each drawn instance has a non-empty bounding box.
 */
export function placementProblems(placed: PlacedInstance[], manifest: ManifestPose[]): string[] {
  const out: string[] = [];
  const want = new Map(manifest.map((i) => [i.id, i.pose.position]));
  const drawn = placed.map((i) => i.id);
  const repeated = drawn.filter((id, k) => drawn.indexOf(id) !== k);
  if (repeated.length) out.push(`instances drawn more than once: ${[...new Set(repeated)].join(", ")}`);
  const missing = manifest.map((i) => i.id).filter((id) => !drawn.includes(id));
  if (missing.length) out.push(`instances of the manifest not drawn: ${missing.join(", ")}`);
  const extra = drawn.filter((id) => !want.has(id));
  if (extra.length) out.push(`instances drawn that the manifest does not have: ${[...new Set(extra)].join(", ")}`);
  for (const i of placed) {
    const p = want.get(i.id);
    if (!p) continue;
    const pose = [p.x, p.y, p.z];
    if (i.pose_project.length !== 3 || pose.some((v, k) => i.pose_project[k] !== v)) out.push(`${i.id}: the page read pose ${i.pose_project}, the manifest has ${pose}`);
    const yup = [p.x, p.z, -p.y];
    if (yup.some((w, k) => !(Math.abs(i.world_position_yup[k]! - w) <= 1e-5))) out.push(`${i.id}: placed at ${i.world_position_yup} not at the manifest pose ${yup}`);
    if (!(i.box_max_yup[0]! > i.box_min_yup[0]! && i.box_max_yup[1]! > i.box_min_yup[1]! && i.box_max_yup[2]! > i.box_min_yup[2]!)) out.push(`${i.id}: empty bounding box`);
  }
  return out;
}
