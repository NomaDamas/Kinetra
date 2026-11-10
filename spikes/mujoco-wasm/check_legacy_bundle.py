# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy==2.5.4"]
# ///
"""A0-01b sanity check: is reference/native_qpos.f64 (scenario `nominal`) the same run as the legacy-v0 hero bundle?

    uv run spikes/mujoco-wasm/check_legacy_bundle.py        # reads the bundle with `git show legacy-v0:...`

legacy-v0 apps/web/public/demo/roadster/traj_8000.json stores the chassis pose every 5th step with 4 (position) and
5 (quaternion) decimals, taken from `d.xpos` / `d.xquat` BEFORE `mj_step` k, i.e. computed at the end of step k-1, so it is
compared with qpos row k-1 (row 0 for k=0). Expect a max position difference near the 5e-5 rounding step.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BUNDLE = "legacy-v0:apps/web/public/demo/roadster/traj_8000.json"
NQ, ROWS = 11, 1126


def main() -> int:
    d = json.loads(subprocess.check_output(["git", "show", BUNDLE], cwd=HERE))
    ref = np.fromfile(HERE / "reference" / "native_qpos.f64", "<f8").reshape(-1, ROWS, NQ)[0]  # scenario 0 = nominal
    pos = np.array([f[0] for f in d["pos"]])
    quat = np.array([f[0] for f in d["quat"]])
    idx = np.maximum(np.arange(len(pos)) * 5 - 1, 0)
    ep = np.abs(pos - ref[idx, :3]).max()
    mq = ref[idx, 3:7]
    q = np.where((quat * mq).sum(1, keepdims=True) < 0, -quat, quat)
    eq = np.abs(q - mq).max()
    print(f"frames={len(pos)} max |pos diff|={ep:.3e} m  max |quat diff|={eq:.3e}  legacy model_hash={d['model_hash'][:12]}")
    return 0 if ep < 1e-4 and eq < 1e-5 else 1


if __name__ == "__main__":
    sys.exit(main())
