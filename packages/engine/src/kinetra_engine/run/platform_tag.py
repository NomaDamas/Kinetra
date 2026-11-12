"""The platform tag of a run (`docs/decisions/engine.md` 5.4, H1; fields in `kinetra_core.frames.PlatformTag`, C-05b).

    platform_tag(model) -> PlatformTag

Every component is read from the running process, never typed in:

| # | field | read from |
|---|---|---|
| ① | `os` | `platform.system()` (`Darwin` is written `macos`), `platform.release()` |
| ② | `cpu` | `platform.machine()`; the model string from `sysctl machdep.cpu.brand_string` (macOS) or `model name` of `/proc/cpuinfo` (Linux), else `platform.processor()`; `unknown` when none of them names it |
| ③ | `image_digest` | the environment variable `KINETRA_IMAGE_DIGEST` (`sha256:...`, set by the container that runs the core); `null` outside a container |
| ④ | `engine` | `mujoco.__version__`, distribution `wheel`, `artifact_hash` the SHA-256 that `uv.lock` records for the wheel file whose tag the installed `mujoco-core` carries (its `WHEEL` metadata) |
| ⑤ | `runtime` | `platform.python_version()`, `numpy.__version__` |
| ⑥ | `core_build` | `KINETRA_CORE_COMMIT`, else `git rev-parse HEAD` of the checkout this package runs from |
| ⑦ | `compute` | the compiled model's own options: integrator, `timestep_s`, and the solver settings by name |
| ⑧ | `threads` | 1 and 1: the run steps with `mj_step` on one thread and sets no thread pool |

A component that cannot be read is an error (`PlatformUnknown`), not a guess: a hash under a made-up tag is not
evidence (H1). ⑥ names a commit, not uncommitted changes in a working tree: a run from a dirty checkout carries the tag
of its commit [확인 필요: #432 decides whether the tag must also say "dirty"].
"""

from __future__ import annotations

import functools
import os
import platform
import subprocess
import tomllib
from importlib import metadata
from pathlib import Path

import mujoco
import numpy

from kinetra_core import PlatformTag

ENGINE_DISTRIBUTION = "mujoco-core"
"""The installed distribution that carries the engine (`packages/engine/pyproject.toml`)."""

_PACKAGE_DIR = Path(__file__).resolve().parent


class PlatformUnknown(RuntimeError):
    """A component of the platform tag could not be read, so no run can be tagged."""


def _os_kind() -> str:
    system = platform.system()
    return {"Darwin": "macos"}.get(system, system.lower())


def _cpu_model() -> str:
    if platform.system() == "Darwin":
        try:
            text = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            text = ""
        if text:
            return text
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "model name" and value.strip():
                return value.strip()
    return platform.processor() or "unknown"


def _image_digest() -> str | None:
    return os.environ.get("KINETRA_IMAGE_DIGEST") or None


def _find_upwards(name: str) -> Path | None:
    for directory in (_PACKAGE_DIR, *_PACKAGE_DIR.parents):
        if (directory / name).exists():
            return directory / name
    return None


def _wheel_tags(filename: str) -> set[str]:
    """The tags of a wheel file name `name-version-python-abi-platform.whl`; each part may be a compressed, dot-separated
    set (`manylinux_2_27_x86_64.manylinux_2_28_x86_64`)."""
    python, abi, plat = filename.removesuffix(".whl").split("-")[-3:]
    return {f"{p}-{a}-{f}" for p in python.split(".") for a in abi.split(".") for f in plat.split(".")}


def _engine_artifact_hash() -> str:
    """The `uv.lock` hash of the engine wheel file that is installed: the wheel of the installed version whose file name
    carries a tag of the installed distribution's `WHEEL` metadata."""
    try:
        dist = metadata.distribution(ENGINE_DISTRIBUTION)
    except metadata.PackageNotFoundError:
        raise PlatformUnknown(f"{ENGINE_DISTRIBUTION} is not installed") from None
    tags = {line.split(":", 1)[1].strip() for line in (dist.read_text("WHEEL") or "").splitlines() if line.startswith("Tag:")}
    lock = _find_upwards("uv.lock")
    if lock is None:
        raise PlatformUnknown("no uv.lock above the engine package: the engine wheel's hash cannot be read")
    stem = ENGINE_DISTRIBUTION.replace("-", "_") + "-" + dist.version + "-"
    for package in tomllib.loads(lock.read_text(encoding="utf-8")).get("package", []):
        if package.get("name") != ENGINE_DISTRIBUTION or package.get("version") != dist.version:
            continue
        for wheel in package.get("wheels", []):
            filename = wheel["url"].rsplit("/", 1)[-1]
            if filename.startswith(stem) and _wheel_tags(filename) & tags:
                return wheel["hash"]
    raise PlatformUnknown(f"uv.lock has no {ENGINE_DISTRIBUTION} {dist.version} wheel for the installed tags {sorted(tags)}")


def _core_commit() -> str:
    commit = os.environ.get("KINETRA_CORE_COMMIT")
    if commit:
        return commit
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_PACKAGE_DIR, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise PlatformUnknown("the core build's commit is unknown: set KINETRA_CORE_COMMIT or run from a git checkout") from None


@functools.cache
def _fixed() -> dict:
    """The components that do not change while the process lives (① ~ ⑥, ⑧)."""
    return {
        "os": {"kind": _os_kind(), "kernel_release": platform.release()},
        "cpu": {"architecture": platform.machine(), "model": _cpu_model()},
        "image_digest": _image_digest(),
        "engine": {
            "name": "mujoco",
            "version": mujoco.__version__,
            "distribution": "wheel",
            "artifact_hash": _engine_artifact_hash(),
        },
        "runtime": {"python": platform.python_version(), "numpy": numpy.__version__},
        "core_build": {"commit": _core_commit()},
        "threads": {"physics": 1, "solver": 1},
    }


def _enum(kind, value: int, prefix: str) -> str:
    return kind(value).name.removeprefix(prefix).lower()


def compute_settings(model: mujoco.MjModel, *, substeps_per_tick: int = 1) -> dict:
    """⑦ of `model`: what the run actually uses, read from the compiled model (not from the MJCF text, whose missing
    `<option>` means the engine's defaults). `model.opt.timestep` is the actual internal integrator step."""
    o = model.opt
    return {
        "integrator": _enum(mujoco.mjtIntegrator, o.integrator, "mjINT_"),
        "timestep_s": float(o.timestep),
        "substeps_per_tick": substeps_per_tick,
        "solver": {
            "solver": _enum(mujoco.mjtSolver, o.solver, "mjSOL_"),
            "cone": _enum(mujoco.mjtCone, o.cone, "mjCONE_"),
            "jacobian": _enum(mujoco.mjtJacobian, o.jacobian, "mjJAC_"),
            "iterations": float(o.iterations),
            "tolerance": float(o.tolerance),
            "ls_iterations": float(o.ls_iterations),
            "ls_tolerance": float(o.ls_tolerance),
            "noslip_iterations": float(o.noslip_iterations),
            "noslip_tolerance": float(o.noslip_tolerance),
            "ccd_iterations": float(o.ccd_iterations),
            "ccd_tolerance": float(o.ccd_tolerance),
            "impratio": float(o.impratio),
            "disableflags": float(o.disableflags),
            "enableflags": float(o.enableflags),
        },
    }


def platform_tag(model: mujoco.MjModel, *, substeps_per_tick: int = 1) -> PlatformTag:
    """The platform tag of a run of `model` in this process. Raises `PlatformUnknown` when a component cannot be read."""
    return PlatformTag.model_validate({**_fixed(), "compute": compute_settings(model, substeps_per_tick=substeps_per_tick)})
