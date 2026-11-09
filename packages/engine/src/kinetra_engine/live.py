"""Live simulation backend: real MuJoCo stepping streamed to the web demo (``/ws/sim``) or returned by ``POST /simulate``.

Nothing here is a replay of a stored file. A run is built from (template, params, overrides, seed), the MuJoCo model is
compiled for exactly those assumption values, and ``mujoco.mj_step`` is executed while the client is connected:

* rocket_car   - *incremental*: every frame (5 physics steps = 20 ms) is produced by stepping the model, paced against the
                 wall clock (``speed`` x real time, 0 = as fast as possible). The exact same stepping code serves ``/simulate``.
* humanoid_jump - *batch*: the template's rollout is one monolithic controller loop, so the whole rollout is computed first
                 (``compute_ms`` is reported) and the frames are then paced out. The start message says ``compute: "batch"``.
* search (rocket_car) - a short real CMA-ES search over the 21 burn-window parameters (pitch, lift and roll windows); every generation evaluates a population
                 with ``mujoco.rollout`` (thread pool); progress and best-so-far rollouts are streamed; then the best
                 schedule is replayed with the incremental stepper.

Frames use the Trajectory layout (``pos[frame][body]``, ``quat[frame][body]`` wxyz, Z-up) of ``physlab_core.schemas``.
Same (template, params, overrides, seed) => bit-identical frames (``trajectory_sha256`` in the result proves it).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Literal

import mujoco
import numpy as np
from pydantic import BaseModel, Field

from physlab_core.schemas import ContactEvent, Geom, GeomType, SpecSheet, TimeSeries, TrajBody, Trajectory, TrajectoryMeta

from . import mc as mclib
from .templates import available, get as get_template

PROTOCOL = 1
DEMO = Path(__file__).resolve().parents[4] / "apps/web/public/demo"
IDEA = {"rocket_car": "Live simulation: roadster rocket roll + pitch rotation", "humanoid_jump": "Live simulation: humanoid jump"}
SEARCH_TEMPLATES = ["rocket_car"]

# Shared native resources (mujoco.rollout pool, the humanoid Sim singleton) are used by one thread at a time.
ENGINE_LOCK = threading.Lock()


class LiveError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- request
class SearchOpts(BaseModel):
    max_seconds: float = Field(default=15.0, gt=0, le=120)
    max_evals: int = Field(default=60000, ge=48, le=1_000_000)
    preview_every: int = Field(default=3, ge=1, le=100, description="send the best-so-far rollout every N generations (only if it improved)")


class SimRequest(BaseModel):
    template: str = "rocket_car"
    mode: Literal["sim", "search"] = "sim"
    params: dict[str, float] | None = Field(default=None, description="search parameters (SpecSheet.param_bounds names) of the schedule to simulate")
    variant: float | None = Field(default=None, description="take params (and rescale_from) from this recorded scenario variant's stored best_params")
    overrides: dict[str, float] = Field(default_factory=dict, description="assumption key -> value (applied on top of the bundle's spec when bundle_defaults)")
    seed: int = 0
    speed: float = Field(default=1.0, ge=0, le=100, description="1 = real time, 0 = as fast as possible")
    rescale_throttle: bool = Field(default=False, description="rocket_car: keep commanded thrust (throttle*Fmax) when Fmax differs from rescale_from")
    rescale_from: float | None = None
    bundle_defaults: bool = Field(default=True, description="start from the recorded scenario's assumption values (so live == recorded at the same inputs)")
    include_trajectory: bool = True
    search: SearchOpts = Field(default_factory=SearchOpts)


# --------------------------------------------------------------------------- recorded bundle lookups (read-only)
_BUNDLE_CACHE: dict[str, tuple[float, dict]] = {}


def bundle_scenario(template_id: str) -> dict | None:
    try:
        idx = json.loads((DEMO / "index.json").read_text())
        sid = next(s["id"] for s in idx["scenarios"] if s["template"] == template_id)
        p = DEMO / sid / "scenario.json"
        mt = p.stat().st_mtime
        hit = _BUNDLE_CACHE.get(sid)
        if hit and hit[0] == mt:
            return hit[1]
        sc = json.loads(p.read_text())
        _BUNDLE_CACHE[sid] = (mt, sc)
        return sc
    except (OSError, StopIteration, KeyError, ValueError):
        return None


@dataclass
class Resolved:
    req: SimRequest
    template_id: str
    tpl: Any
    spec: SpecSheet
    params: dict[str, float] | None
    overrides: dict[str, float]
    note: str


def resolve(req: SimRequest) -> Resolved:
    tid = req.template
    if tid not in available():
        raise LiveError(f"template {tid!r} is not available on this engine; available: {available()}", 404)
    tpl = get_template(tid)
    sc = bundle_scenario(tid)
    known = {a.key for a in tpl.default_spec(IDEA.get(tid, "live"), None).assumptions}
    over: dict[str, float] = {}
    note = []
    if req.bundle_defaults and sc:
        over.update({a["key"]: float(a["value"]) for a in sc["spec"]["assumptions"] if a["key"] in known})
    bad = set(req.overrides) - known
    if bad:
        raise LiveError(f"unknown assumption override(s) {sorted(bad)}; known: {sorted(known)}")
    over.update({k: float(v) for k, v in req.overrides.items()})
    try:
        spec = tpl.default_spec(IDEA.get(tid, "live"), over)
    except (KeyError, ValueError) as e:
        raise LiveError(str(e))
    params = dict(req.params) if req.params else None
    rescale_from = req.rescale_from
    if params is None and req.mode == "sim":
        variants = (sc or {}).get("variants", [])
        if req.variant is not None:
            v = next((v for v in variants if abs(float(v["value"]) - req.variant) < 1e-9), None)
            if v is None:
                raise LiveError(f"no recorded variant with value {req.variant}; have {[x['value'] for x in variants]}")
        else:
            hero = (sc or {}).get("build", {}).get("hero_variant")
            v = next((v for v in variants if hero is not None and abs(float(v["value"]) - float(hero)) < 1e-9), None)
            if v is None:
                raise LiveError("no params given and no recorded hero variant to take a schedule from")
            note.append(f"no params given: used the recorded hero variant {v['value']}")
        params = {k: float(x) for k, x in v["verdict"]["best_params"].items()}
        if not params:
            raise LiveError(f"recorded variant {v['value']} has no witness schedule (its search found none); give params or use mode=search")
        note.append(f"schedule = stored best_params of recorded variant {v['value']}")
        if rescale_from is None:
            rescale_from = float(v["value"])
    if params is not None:
        names = [b.name for b in spec.param_bounds]
        miss = [n for n in names if n not in params]
        if miss:
            raise LiveError(f"params missing {miss}")
        params = {n: float(params[n]) for n in names}
        if req.rescale_throttle:
            if tid != "rocket_car":
                raise LiveError("rescale_throttle only applies to rocket_car")
            f_to = float(over.get("thruster_force_max", [a.value for a in spec.assumptions if a.key == "thruster_force_max"][0]))
            if rescale_from is None:
                raise LiveError("rescale_throttle needs rescale_from (or variant)")
            params = tpl.rescale_params(params, float(rescale_from), f_to)
            note.append(f"throttle rescaled x{rescale_from:g}/{f_to:g} to keep commanded thrust")
    return Resolved(req, tid, tpl, spec, params, over, "; ".join(note))


# --------------------------------------------------------------------------- helpers
def _r(x: float, n: int) -> float:
    return round(float(x), n)


def _hash_frames(pos, quat, series: dict[str, list[float]]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([pos, quat, [[k, v] for k, v in series.items()]], separators=(",", ":")).encode())
    return h.hexdigest()


def _display(key, label, value, unit, ok, threshold=None) -> dict:
    d = {"key": key, "label": label, "value": value, "unit": unit, "ok": ok}
    if threshold is not None:
        d["threshold"] = threshold
    return d


class _Run:
    """Interface shared by the template-specific runs."""

    template_id: str
    mode_note: str = ""

    def header(self) -> dict: ...
    def frames(self, per_chunk: int) -> Iterator[dict]: ...
    def result(self) -> dict: ...
    def trajectory(self) -> Trajectory: ...


# =========================================================================== rocket_car
class RocketRun(_Run):
    template_id = "rocket_car"
    STRIDE = 5
    CHARTS = [("roll_deg", "Roll rotation (progress to 360)", "deg"), ("pitch_deg", "Pitch rotation (progress to 360)", "deg"), ("thrust_total_N", "Total thrust", "N"),
              ("height_m", "Height", "m"), ("speed_mps", "Speed", "m/s"), ("fuel_kg", "Propellant used", "kg")]

    def __init__(self, res: Resolved, params: dict[str, float]):
        from .templates import rocket_car as rc
        self.rc = rc
        self.res, self.spec, self.params = res, res.spec, params
        self.seed = int(res.req.seed)
        self.sim = res.tpl._sim(self.spec)
        vals = rc._vals(self.spec)
        s = {k: np.array([v]) for k, v in vals.items()}
        s.update(rc.aux_jitter(1, self.seed))
        self.env = rc.Env.from_samples(s, vals)
        self.names = [t[0] for t in rc.THRUSTERS]
        self.series_names = [f"thrust_{n}" for n in self.names] + ["pitch_deg", "roll_deg", "height_m", "speed_mps", "fuel_kg", "thrust_total_N"]
        self.n_frames = (rc.NSTEP + self.STRIDE - 1) // self.STRIDE
        self.pos: list = []
        self.quat: list = []
        self.series: dict[str, list[float]] = {n: [] for n in self.series_names}
        self._result: dict | None = None
        self._events: list[ContactEvent] = []

    # ---- trajectory bodies (mirrors RocketCar.rollout)
    def bodies(self) -> list[TrajBody]:
        rc = self.rc
        geoms = [Geom(type=GeomType.box, size=[rc.LENGTH / 2, rc.WIDTH / 2, (rc.HEIGHT - rc.WHEEL_R * 0.5) / 2],
                      pos=[0.0, 0.0, rc.HEIGHT / 2 - (rc.HEIGHT - rc.WHEEL_R * 0.5) / 2], rgba=[0.8, 0.1, 0.1, 1.0])]
        tb = [TrajBody(name="chassis", parent=None, geoms=geoms)]
        for n, *_ in rc.WHEELS:
            tb.append(TrajBody(name=f"wheel_{n}", parent="chassis",
                               geoms=[Geom(type=GeomType.cylinder, size=[rc.WHEEL_R, rc.WHEEL_HW], quat=[0.70710678, 0.70710678, 0.0, 0.0],
                                           rgba=[0.12, 0.12, 0.12, 1.0])]))
        for n in self.names:
            tb.append(TrajBody(name=f"thr_{n}", parent="chassis", geoms=[]))
        return tb

    def header(self) -> dict:
        rc = self.rc
        units = {n: "N" for n in self.series_names if n.startswith("thrust_")}
        units.update(pitch_deg="deg", roll_deg="deg", height_m="m", speed_mps="m/s", fuel_kg="kg")
        full = (self.env.fmax[0] * self.env.tscale[0]).tolist()
        smax = {f"thrust_{n}": round(float(full[i]), 3) for i, n in enumerate(self.names)}
        smax["thrust_total_N"] = round(float(sum(full)), 3)
        info = self.res.tpl.model_info(self.spec)
        return dict(model_id=info["model_id"], model_hash=rc.MODEL_HASH, mujoco_version=mujoco.__version__, dt=self.STRIDE * rc.DT,
                    physics_dt=rc.DT, n_frames_max=self.n_frames, bodies=[b.model_dump(mode="json") for b in self.bodies()],
                    series=[{"name": n, "unit": units.get(n, "N")} for n in self.series_names], series_max=smax,
                    charts=[{"series": s, "label": l, "unit": u} for s, l, u in self.CHARTS], compute="incremental",
                    mass_kg=info["mass_kg"], note="every frame = 5 mj_step calls executed live (implicitfast, 4 ms timestep); "
                    + "simplified model, needs precise validation")

    # ---- the stepping loop (mirrors RocketCar.rollout; the equality is asserted in tests)
    def frames(self, per_chunk: int) -> Iterator[dict]:
        rc, sim, env = self.rc, self.sim, self.env
        x = rc.params_to_x(self.params)
        thr = sim.controls(x[None])[0]
        mdl = sim.models(env)[0]
        d = mujoco.MjData(mdl)
        mujoco.mj_setState(mdl, d, sim.x0(env)[0], mujoco.mjtState.mjSTATE_FULLPHYSICS)
        mujoco.mj_forward(mdl, d)
        bid = [mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_BODY, b) for b in ["car"] + [f"wheel_{n}" for n, *_ in rc.WHEELS]]
        sid = [mujoco.mj_name2id(mdl, mujoco.mjtObj.mjOBJ_SITE, n) for n in self.names]
        st = np.empty((rc.NSTEP, sim.ns))
        buf = np.empty(sim.ns)
        qs = np.zeros(4)
        f6 = np.zeros(6)
        isp = float(env.isp[0])
        fscale = env.fmax[0] * env.tscale[0]
        impulse, pit_u, rol_u = 0.0, 0.0, 0.0           # body-frame rate integrals = rotation progress (same definition as the judge)
        touchdown, peak_force = None, 0.0
        t_step = 0.0                                  # time inside mj_step only
        busy = 0.0                                    # wall time spent computing (excludes pacing sleeps while the generator is suspended)
        t_res = time.perf_counter()
        chunk_pos, chunk_quat, chunk_ser = [], [], {n: [] for n in self.series_names}
        i0 = 0
        for k in range(rc.NSTEP):
            if k % self.STRIDE == 0:
                p = [[_r(c, 4) for c in d.xpos[b]] for b in bid]
                q = [[_r(c, 5) for c in d.xquat[b]] for b in bid]
                for s_ in sid:
                    p.append([_r(c, 4) for c in d.site_xpos[s_]])
                    mujoco.mju_mat2Quat(qs, d.site_xmat[s_])
                    q.append([_r(c, 5) for c in qs])
                tn = [_r(thr[k, i] * fscale[i], 2) for i in range(rc.K)]
                vals = tn + [_r(np.degrees(pit_u), 3), _r(np.degrees(rol_u), 3), _r(d.qpos[2], 4), _r(np.linalg.norm(d.qvel[:3]), 4), _r(impulse / (isp * rc.G0), 4),
                             _r(sum(tn), 2)]
                chunk_pos.append(p)
                chunk_quat.append(q)
                for n, v in zip(self.series_names, vals):
                    chunk_ser[n].append(v)
            impulse += float((thr[k] * fscale).sum()) * rc.DT
            d.ctrl[:] = thr[k]
            t0 = time.perf_counter()
            mujoco.mj_step(mdl, d)
            rol_u += float(d.qvel[3]) * rc.DT
            pit_u += float(d.qvel[4]) * rc.DT
            mujoco.mj_getState(mdl, d, buf, mujoco.mjtState.mjSTATE_FULLPHYSICS)
            t_step += time.perf_counter() - t0
            st[k] = buf
            if d.ncon > 0:
                fsum, cp = 0.0, None
                for ci in range(d.ncon):
                    mujoco.mj_contactForce(mdl, d, ci, f6)
                    fsum += abs(f6[0])
                    cp = d.contact[ci].pos if cp is None else cp
                if touchdown is None and fsum > 0:
                    touchdown = dict(t=(k + 1) * rc.DT, pos=[float(c) for c in cp], force=fsum)
                if touchdown is not None and (k + 1) * rc.DT - touchdown["t"] < 0.3:
                    peak_force = max(peak_force, fsum)
            if len(chunk_pos) >= per_chunk or k == rc.NSTEP - 1:
                if chunk_pos:
                    busy += time.perf_counter() - t_res
                    yield self._emit(i0, chunk_pos, chunk_quat, chunk_ser, k + 1, busy)
                    t_res = time.perf_counter()
                    i0 += len(chunk_pos)
                    chunk_pos, chunk_quat, chunk_ser = [], [], {n: [] for n in self.series_names}
        compute_s = busy
        self._finish(mdl, d, thr, x, st, touchdown, peak_force, t_step, compute_s)

    def _emit(self, i0, pos, quat, ser, steps, compute_s) -> dict:
        self.pos += pos
        self.quat += quat
        for n in self.series_names:
            self.series[n] += ser[n]
        return dict(type="frames", i0=i0, pos=pos, quat=quat, series=ser, t=_r((i0 + len(pos) - 1) * self.STRIDE * self.rc.DT, 4), steps=steps,
                    compute_ms=_r(compute_s * 1000, 3))

    def _finish(self, mdl, d, thr, x, st, touchdown, peak_force, t_step, compute_s) -> None:
        rc, sim, env = self.rc, self.sim, self.env
        m = sim.metrics(st[None], thr[None], env)
        success = bool(m["success"][0])
        ok = {k: bool(v[0]) for k, v in m["ok"].items()}
        failed = [k for k, v in ok.items() if not v]
        ts, du, ma = sim.decode(x[None])
        ev: list[ContactEvent] = []
        for i in range(rc.NWIN):
            if du[0, i] <= 1e-3 or ma[0, i] <= 1e-3:
                continue
            tname = rc.THRUSTERS[int(np.flatnonzero(rc.GROUP_OF == rc.WIN_GROUP[i])[0])][0]
            fN = float(ma[0, i] * env.fmax[0])
            ev.append(ContactEvent(t=_r(ts[0, i], 3), kind="thrust", body=f"thr_{tname}", note=f"{rc.WIN_NAMES[i]} ignition ({fN:.0f} N per nozzle)", magnitude=fN))
            ev.append(ContactEvent(t=_r(min(ts[0, i] + du[0, i], rc.T_SIM), 3), kind="thrust", body=f"thr_{tname}", note=f"{rc.WIN_NAMES[i]} cutoff", magnitude=0.0))
        if touchdown is not None:
            ev.append(ContactEvent(t=_r(touchdown["t"], 3), kind="landing", body="chassis", pos=[_r(c, 4) for c in touchdown["pos"]], magnitude=_r(peak_force, 1),
                                   note=f"first touchdown; peak contact normal force {peak_force:.0f} N in 0.3 s (pitch turned {np.degrees(m['pitch_turn'][0]):.0f} deg, roll turned {np.degrees(m['roll_turn'][0]):.0f} deg, vz {m['vz_td'][0]:.2f} m/s)"))
        if not success:
            ev.append(ContactEvent(t=_r(touchdown["t"] if touchdown else rc.T_SIM, 3), kind="failure", body="chassis",
                                   pos=[_r(c, 4) for c in d.xpos[1]], note="live run FAILED: " + ", ".join(failed)))
        ev.sort(key=lambda e: e.t)
        self._events = ev
        lim = self.sim
        cap = float(env.fuel_cap[0])
        ptd, rtd = np.degrees(m["pitch_turn"][0]), np.degrees(m["roll_turn"][0])
        d_ = lambda a: float(np.degrees(a))
        display = [
            _display("pitch_turn_deg", "Pitch rotation (body-rate integral to touchdown)", _r(abs(ptd), 1), "deg", ok["pitch_turn"], ">= 340 (a full turn minus the 20 deg tolerance)"),
            _display("roll_turn_deg", "Roll rotation (body-rate integral to touchdown)", _r(abs(rtd), 1), "deg", ok["roll_turn"], ">= 340 (a full turn minus the 20 deg tolerance)"),
            _display("touchdown_upright_error_deg", "Touchdown roll / pitch error to a whole turn (worse of the two)", _r(d_(m["err_td"][0]), 1), "deg", ok["upright_td"], "<= 30"),
            _display("final_upright_error_deg", "Final roll / pitch error to a whole turn (worse of the two)", _r(d_(m["err_fin"][0]), 1), "deg", ok["upright_final"], "<= 20"),
            _display("touchdown_vz", "Touchdown vertical speed", _r(m["vz_td"][0], 3), "m/s", ok["impact_vz"], f"<= {lim.vz_max:g}"),
            _display("touchdown_pitch_rate", "Touchdown pitch rate", _r(m["w_td"][0], 3), "rad/s", ok["impact_w"], f"<= {lim.w_max:g}"),
            _display("touchdown_roll_rate", "Touchdown roll rate", _r(m["wr_td"][0], 3), "rad/s", ok["impact_wr"], f"<= {lim.wr_max:g}"),
            _display("fuel_kg", "Propellant used", _r(m["fuel"][0], 3), "kg", ok["fuel"], f"<= {cap:g}"),
            _display("post_contact_impulse_kNs", "Thrust impulse after touchdown", _r(m["post_imp"][0], 4), "kN*s", ok["no_post_thrust"], "< 0.05"),
            _display("final_height_m", "Final ride height", _r(m["z_end"][0], 3), "m", ok["ride_height"], "0.5 .. 0.8"),
            _display("peak_contact_force_N", "Peak contact normal force (0.3 s after touchdown)", _r(peak_force, 1), "N", None),
        ]
        steps = rc.NSTEP
        self._result = dict(
            type="result", mode="sim", success=success, failed_checks=failed, display=display,
            perf=dict(steps=steps, sim_time_s=rc.T_SIM, compute_ms=_r(compute_s * 1000, 3), us_per_step=_r(t_step / steps * 1e6, 3),
                      steps_per_s=_r(steps / max(compute_s, 1e-9), 1), realtime_factor=_r(rc.T_SIM / max(compute_s, 1e-9), 1),
                      frames=len(self.pos), compute="incremental (mj_step + mj_getState timed per step; compute_ms includes frame export and contact bookkeeping)"),
            mujoco_version=mujoco.__version__, seed=self.seed, params=self.params, overrides=self.res.overrides,
            events=[e.model_dump(mode="json") for e in ev], n_frames=len(self.pos), trajectory_sha256=_hash_frames(self.pos, self.quat, self.series),
            metrics={k: _r(float(m[k][0]), 5) for k in ("pitch_turn", "roll_turn", "phi_td", "pit_td", "phi_end", "pit_end", "vz_td", "w_td", "wr_td", "fuel", "post_imp", "z_end", "cost")})

    def result(self) -> dict:
        assert self._result is not None, "run not finished"
        return self._result

    def trajectory(self) -> Trajectory:
        rc = self.rc
        info = self.res.tpl.model_info(self.spec)
        ser = [TimeSeries(name=n, unit=("N" if n.startswith("thrust_") else dict(pitch_deg="deg", roll_deg="deg", height_m="m", speed_mps="m/s", fuel_kg="kg")[n]), values=self.series[n])
               for n in self.series_names]
        meta = TrajectoryMeta(seed=self.seed, mujoco_version=mujoco.__version__, template_id=self.res.spec.template_id, params=self.params,
                              note=f"LIVE run (incremental mj_step); success={self._result['success'] if self._result else None}; simplified model, needs precise validation")
        return Trajectory(model_id=info["model_id"], model_hash=rc.MODEL_HASH, dt=self.STRIDE * rc.DT, bodies=self.bodies(), pos=self.pos, quat=self.quat,
                          events=self._events, series=ser, meta=meta)


# =========================================================================== humanoid_jump (batch)
class HumanoidRun(_Run):
    template_id = "humanoid_jump"
    CHARTS = [("knee_torque_ratio", "Knee torque / limit", ""), ("grf_N", "Ground reaction force", "N"), ("com_height_m", "COM height", "m")]
    _SIM = None

    def __init__(self, res: Resolved, params: dict[str, float]):
        from .templates import humanoid_jump as hj
        self.hj = hj
        self.res, self.spec = res, res.spec
        lo = {b.name: b.low for b in self.spec.param_bounds}
        hi = {b.name: b.high for b in self.spec.param_bounds}
        self.params = {k: float(min(max(params[k], lo[k]), hi[k])) for k in lo}
        self.seed = int(res.req.seed)
        self._result = None
        self.traj: Trajectory | None = None
        self.pos, self.quat = [], []
        self.series: dict[str, list[float]] = {}
        self._compute()

    def _compute(self) -> None:
        hj = self.hj
        v = hj._values(self.spec)
        with ENGINE_LOCK:
            if HumanoidRun._SIM is None:
                HumanoidRun._SIM = hj.Sim()
            s = HumanoidRun._SIM
            s.configure(*hj._cfg(v))
            p = np.array([self.params[k] for k in hj.PNAMES])
            t0 = time.perf_counter()
            r = s.rollout(p, record=True)
            compute_s = time.perf_counter() - t0
            self.traj = hj.export_trajectory(s, r, self.params, self.seed, v)
            dt_phys = float(s.m.opt.timestep)
            self.mu = s.mu
        self.pos = [[list(x) for x in f] for f in self.traj.pos]
        self.quat = [[list(x) for x in f] for f in self.traj.quat]
        self.series = {s_.name: list(s_.values) for s_ in self.traj.series}
        target, limit = v["target_height"], v["landing_grf_limit_bw"]
        ok = {"jump_height": bool(r["liftoff"] and r["ballistic_height"] >= target), "stable_landing": bool(r["liftoff"] and r["stable_landing"]),
              "horizontal_drift": bool(r["drift_m"] <= hj.MAX_DRIFT_M), "landing_grf": bool(r["grf_peak_land_bw"] <= limit)}
        success = bool(hj._succeeded(r, target, limit))
        failed = [k for k, x in ok.items() if not x]
        if not success and not failed:
            failed = ["model_not_finite"]
        steps = int(round(r["t_end"] / dt_phys))
        self.dt_phys = dt_phys
        display = [
            _display("ballistic_height_m", "Ballistic jump height (vz^2/2g at liftoff)", _r(r["ballistic_height"], 4), "m", ok["jump_height"], f">= {target:g}"),
            _display("stable_landing", "Stable landing (upright, no non-foot contact)", bool(r["stable_landing"]), "", ok["stable_landing"]),
            _display("landing_grf_bw", "Landing peak ground force", _r(r["grf_peak_land_bw"], 3), "BW", ok["landing_grf"], f"<= {limit:g}"),
            _display("drift_m", "Horizontal COM drift to touchdown", _r(r["drift_m"], 4), "m", ok["horizontal_drift"], f"<= {hj.MAX_DRIFT_M:g}"),
            _display("torque_applied_ratio_max", "Peak applied/limit torque ratio (any joint)", _r(r["torque_applied_ratio_max"], 3), "", None),
            _display("binding_joint", "Joint saturated longest during push-off", str(r["binding_joint"]), "", None),
        ]
        self.n_steps, self.compute_s = steps, compute_s
        self._result = dict(
            type="result", mode="sim", success=success, failed_checks=failed, display=display,
            perf=dict(steps=steps, sim_time_s=_r(r["t_end"], 4), compute_ms=_r(compute_s * 1000, 3), us_per_step=_r(compute_s / max(steps, 1) * 1e6, 3),
                      steps_per_s=_r(steps / max(compute_s, 1e-9), 1), realtime_factor=_r(r["t_end"] / max(compute_s, 1e-9), 1), frames=len(self.pos),
                      compute="batch (whole rollout computed first by the template's controller loop; us_per_step includes controller + contact bookkeeping)"),
            mujoco_version=mujoco.__version__, seed=self.seed, params=self.params, overrides=self.res.overrides,
            events=[e.model_dump(mode="json") for e in self.traj.events], n_frames=len(self.pos),
            trajectory_sha256=_hash_frames(self.pos, self.quat, self.series))

    def header(self) -> dict:
        assert self.traj is not None
        smax = {}
        units = {s_.name: s_.unit for s_ in self.traj.series}
        return dict(model_id=self.traj.model_id, model_hash=self.traj.model_hash, mujoco_version=mujoco.__version__, dt=self.traj.dt, physics_dt=self.dt_phys,
                    n_frames_max=len(self.pos), bodies=[b.model_dump(mode="json") for b in self.traj.bodies],
                    series=[{"name": n, "unit": units[n]} for n in self.series], series_max=smax,
                    charts=[{"series": s, "label": l, "unit": u} for s, l, u in self.CHARTS], compute="batch",
                    note=f"rollout computed in {self.compute_s * 1000:.0f} ms ({self.n_steps} mj_step calls, Unitree G1), then paced out; "
                         "simplified model, needs precise validation")

    def frames(self, per_chunk: int) -> Iterator[dict]:
        n = len(self.pos)
        stride_steps = self.n_steps / max(n, 1)
        for i0 in range(0, n, per_chunk):
            j = min(i0 + per_chunk, n)
            yield dict(type="frames", i0=i0, pos=self.pos[i0:j], quat=self.quat[i0:j], series={k: v[i0:j] for k, v in self.series.items()},
                       t=_r((j - 1) * self.traj.dt, 4), steps=int(round(j * stride_steps)), compute_ms=_r(self.compute_s * 1000, 3))

    def result(self) -> dict:
        assert self._result is not None
        return self._result

    def trajectory(self) -> Trajectory:
        assert self.traj is not None
        return self.traj


def build_run(res: Resolved, params: dict[str, float] | None = None) -> _Run:
    p = params if params is not None else res.params
    if p is None:
        raise LiveError("no schedule params")
    return RocketRun(res, p) if res.template_id == "rocket_car" else HumanoidRun(res, p)


def drain(run: _Run) -> None:
    for _ in run.frames(10 ** 6):
        pass


def simulate_sync(req: SimRequest) -> dict:
    """``POST /simulate``: run to completion (unpaced) and return the result (+ trajectory)."""
    if req.mode != "sim":
        raise LiveError("POST /simulate runs mode='sim'; use the /ws/sim websocket for mode='search'")
    t0 = time.perf_counter()
    res = resolve(req)
    run = build_run(res)
    h = run.header()
    drain(run)
    out = {k: v for k, v in run.result().items() if k != "type"}
    out["wall_ms_total"] = _r((time.perf_counter() - t0) * 1000, 3)
    out["note"] = res.note
    out["model_id"], out["model_hash"] = h["model_id"], h["model_hash"]
    if req.include_trajectory:
        out["trajectory"] = run.trajectory().model_dump(mode="json")
    return out


# =========================================================================== real CMA-ES search (rocket_car)
def search_iter(res: Resolved) -> Iterator[dict]:
    """Streaming version of ``RocketCar.search`` (same restarts / population doubling / cost); yields progress / preview / done dicts."""
    import cma
    from .templates import rocket_car as rc
    tpl, spec, opts, seed = res.tpl, res.spec, res.req.search, int(res.req.seed)
    sim = tpl._sim(spec)
    env = tpl._env_nom(spec)
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    best: dict[str, Any] = dict(cost=np.inf, x=None, success=False)
    pop, restart, gens, stopped = 64, 0, 0, "time"
    with ENGINE_LOCK:
        seed_x, seed_cost, seed_ok = rc.seeded_start(sim, env)
    best = dict(cost=seed_cost, x=seed_x.copy(), success=seed_ok)
    last_prev_cost = None
    while not best["success"]:
        if sim.evals >= opts.max_evals:
            stopped = "evals"
            break
        if time.perf_counter() - t0 >= opts.max_seconds:
            break
        x0, sigma0, pop = rc.start_point(restart, rng, seed_x)
        es = cma.CMAEvolutionStrategy(x0, sigma0, dict(bounds=[0, 1], popsize=pop, seed=int(rng.integers(1 << 30)), verbose=-9, tolfun=1e-9, tolx=1e-9))
        g = 0
        while not es.stop() and g < 150 and sim.evals < opts.max_evals:
            if time.perf_counter() - t0 >= opts.max_seconds:
                break
            X = np.array(es.ask())
            with ENGINE_LOCK:
                m, _, _ = tpl.eval_x(sim, X, env)
            es.tell(X, m["cost"])
            g += 1
            gens += 1
            if m["success"].any():
                i = int(np.where(m["success"], m["cost"], np.inf).argmin())
                best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=True)
            else:
                i = int(m["cost"].argmin())
                if m["cost"][i] < best["cost"]:
                    best = dict(cost=float(m["cost"][i]), x=X[i].copy(), success=False)
            el = time.perf_counter() - t0
            yield dict(type="progress", gen=gens, evals=int(sim.evals), best_cost=_r(best["cost"], 5), success=bool(best["success"]), elapsed_s=_r(el, 3),
                       evals_per_s=_r(sim.evals / max(el, 1e-9), 1), restart=restart, popsize=pop)
            if best["success"] or (gens % opts.preview_every == 0 and best["cost"] != last_prev_cost):
                last_prev_cost = best["cost"]
                yield dict(type="preview", gen=gens, cost=_r(best["cost"], 5), success=bool(best["success"]), **_preview_frames(res, rc.x_to_params(best["x"])))
            if best["success"]:
                break
        restart += 1
    if best["x"] is None:
        raise LiveError("search ran out of time before evaluating a single generation; raise search.max_seconds")
    params = rc.x_to_params(best["x"])
    with ENGINE_LOCK:
        mb = tpl.eval_x(sim, rc.params_to_x(params)[None], env)[0]
    found = bool(mb["success"][0])
    el = time.perf_counter() - t0
    yield dict(type="search_done", found=found, best_cost=_r(best["cost"], 5), evals=int(sim.evals), wall_s=_r(el, 3), evals_per_s=_r(sim.evals / max(el, 1e-9), 1),
               generations=gens, params=params, stopped_by="success" if best["success"] else stopped)


def _preview_frames(res: Resolved, params: dict[str, float]) -> dict:
    run = RocketRun(res, params)
    drain(run)
    return dict(n_frames=len(run.pos), pos=run.pos, quat=run.quat, series=run.series)


# =========================================================================== websocket session
def frames_per_chunk(speed: float, dt: float) -> int:
    if speed <= 0:
        return 50
    return max(1, int(round(speed * 0.04 / dt)))


async def _paced_stream(ws, run: _Run, speed: float, dt: float) -> None:
    loop = asyncio.get_running_loop()
    gen = run.frames(frames_per_chunk(speed, dt))
    t0 = loop.time()
    nxt = 0
    while True:
        if speed > 0:
            # sleep BEFORE stepping: the physics for the next chunk is executed when its simulated time arrives on the wall clock
            delay = t0 + nxt * dt / speed - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
        chunk = next(gen, None)
        if chunk is None:
            break
        nxt = chunk["i0"] + len(chunk["pos"])
        await ws.send_text(json.dumps(chunk, separators=(",", ":"), allow_nan=False))
    res = dict(run.result())
    res["perf"] = dict(res["perf"], wall_ms=_r((loop.time() - t0) * 1000, 1), speed=speed)
    await ws.send_text(json.dumps(res, separators=(",", ":"), allow_nan=False))


async def stream(ws, req: SimRequest, run_id: int) -> None:
    """Run one request on ``ws`` (cancellable: the caller cancels the task on stop / new start)."""
    res = await asyncio.to_thread(resolve, req)
    send = lambda o: ws.send_text(json.dumps(o, separators=(",", ":"), allow_nan=False))
    if req.mode == "sim":
        run = await asyncio.to_thread(build_run, res)
        h = run.header()
        await send(dict(type="start", run_id=run_id, mode="sim", template=req.template, params=res.params, overrides=res.overrides, seed=req.seed,
                        speed=req.speed, **dict(h, note=h["note"] + (f" | {res.note}" if res.note else ""))))
        await _paced_stream(ws, run, req.speed, h["dt"])
        return
    if req.template not in SEARCH_TEMPLATES:
        raise LiveError(f"live search is not available for {req.template!r}; available: {SEARCH_TEMPLATES}")
    probe = await asyncio.to_thread(RocketRun, res, {})      # header only (no stepping): model/body layout does not depend on the schedule
    h = probe.header()
    await send(dict(type="start", run_id=run_id, mode="search", template=req.template, params={}, overrides=res.overrides, seed=req.seed, speed=req.speed,
                    **dict(h, compute="batch", note="real CMA-ES: every generation = a population of full mujoco.rollout simulations; "
                           f"budget {req.search.max_seconds:g} s | simplified model, needs precise validation")))
    gen = search_iter(res)
    done = None
    while True:
        ev = await asyncio.to_thread(next, gen, None)
        if ev is None:
            break
        await send(ev)
        if ev["type"] == "search_done":
            done = ev
    if done is None:
        return
    await send(dict(type="replay_start", params=done["params"]))
    run = await asyncio.to_thread(build_run, res, done["params"])
    await _paced_stream(ws, run, req.speed if req.speed > 0 else 0.0, h["dt"])


def health_info() -> dict:
    return dict(protocol=PROTOCOL, templates=available(), search=SEARCH_TEMPLATES,
                version_note="rocket_car: incremental mj_step stream; humanoid_jump: batch rollout then paced; search: rocket_car only")
