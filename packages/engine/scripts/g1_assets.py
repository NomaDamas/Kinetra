"""Convert the Menagerie G1 visual meshes to simplified GLBs (vertices RAW in the MuJoCo mesh frame, Z-up, metres)."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import mujoco
import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kinetra_engine.templates.humanoid_jump import g1_dir  # noqa: E402

FACES_PER_MESH = 2500
MAX_TOTAL_BYTES = 15 * 1024 * 1024

LICENSE_NOTE = """Unitree G1 meshes (simplified, converted to GLB)
=================================================
Source model : MuJoCo Menagerie, unitree_g1  https://github.com/google-deepmind/mujoco_menagerie/tree/main/unitree_g1
Copyright    : (c) 2016-2023 HangZhou YuShu TECHNOLOGY CO.,LTD. ("Unitree Robotics"). All rights reserved.
License      : BSD-3-Clause (see unitree_g1/LICENSE in the Menagerie repository; text reproduced below).
Modification : meshes decimated (quadric edge collapse, <= {faces} faces each) and re-encoded as binary glTF; vertices are
               stored in the MuJoCo mesh frame (Z-up, metres). No other change.

{license}
"""


def convert(out_dir: Path) -> dict:
    src = g1_dir()
    m = mujoco.MjModel.from_xml_path(str(src / "scene.xml"))
    out_dir.mkdir(parents=True, exist_ok=True)
    used = sorted({int(m.geom_dataid[g]) for g in range(m.ngeom)
                   if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and m.geom_group[g] <= 2})
    total, info = 0, {}
    for mid in used:
        name = m.mesh(mid).name
        v = m.mesh_vert[m.mesh_vertadr[mid]: m.mesh_vertadr[mid] + m.mesh_vertnum[mid]].astype(np.float64)
        f = m.mesh_face[m.mesh_faceadr[mid]: m.mesh_faceadr[mid] + m.mesh_facenum[mid]]
        tm = trimesh.Trimesh(v, f, process=True)
        n0 = len(tm.faces)
        if n0 > FACES_PER_MESH:
            tm = tm.simplify_quadric_decimation(face_count=FACES_PER_MESH)
        tm.vertices = tm.vertices.astype(np.float32).astype(np.float64)
        data = tm.export(file_type="glb")
        (out_dir / f"{name}.glb").write_bytes(data)
        total += len(data)
        info[name] = (n0, len(tm.faces), len(data))
    lic = (src / "LICENSE").read_text()
    (out_dir / "LICENSE.txt").write_text(LICENSE_NOTE.format(faces=FACES_PER_MESH, license=lic))
    assert total <= MAX_TOTAL_BYTES, total
    return dict(n_meshes=len(used), total_bytes=total, per_mesh=info)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "apps/web/public/assets/g1"
    r = convert(out)
    print(r["n_meshes"], "meshes", r["total_bytes"] / 1e6, "MB")
