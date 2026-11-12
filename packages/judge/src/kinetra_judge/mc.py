"""Monte Carlo verdict: p_success and its 95% CI over the verdict's assumption table (J-01a; `docs/architecture/verdict-mc.md`).

    sample_assumptions(rows, n, seed) -> {key: (x_0 .. x_{n-1})}       # one RNG stream per row, from (seed, key)
    wilson_ci(k, n) -> (low, high)                                    # 95% Wilson score interval
    monte_carlo(table, goal, n=, seed=, duration_s=, applied=, run_sample=) -> Verdict
    run_verdict(project, goal, n=, seed=, duration_s=, project_id=, revision=) -> Verdict   # the engine's samples
    compare_verdicts(a, b) -> VerdictComparisonResult                 # match | mismatch | not_comparable, and what differs

Port of the legacy sampler (`legacy-v0:packages/engine/src/kinetra_engine/mc.py`: `derive_seed`, `sample_assumption`,
`wilson_ci`, `feasibility_fields`). Kept as it was: each row draws from its own NumPy `default_rng` stream seeded by
`derive_seed(seed, "assumption", key)`, so adding or removing a row never shifts another row's samples; `fixed` is the
nominal, `uniform` is `rng.uniform(low, high, n)`, `normal` is `rng.normal(mean, std, n)` clipped to `clip_low`/`clip_high`;
the interval is Wilson's, widened to contain p. One-at-a-time sensitivities (J-03) build on this runner in
`sensitivity.py`. Not carried over: the failure taxonomy counts (J-06), the Clopper-Pearson interval (unused by the legacy verdict).

A verdict is the simulation of every sample (V1): sample i runs the project once (`RunKind.VERDICT_SAMPLE`, one frame per
tick) with the values of row i, and `evaluate_goal` (J-02a) says `met`, `failed` or `undetermined`. p_success is
`met / (met + failed)`; undetermined samples are counted and left out of p and the CI, with a label. A table row whose
sample does not enter the model is not shaken and says so (`not_applied`). `run_verdict` applies `ENGINE_APPLIED` and
project rows with a typed binding; `sampled_values` records the actual draws of every applied random row.

Platform (engine.md 5.4): a verdict carries the platform tag of its runs (H1); every sample must have the same tag, else
there is no verdict. Two verdicts are compared only when they answer the same request (`REQUEST_FIELDS`: project, goal,
assumption table, duration, time step, sample count, seed) under the same tag (H2); otherwise their p_success is not called
the same value (H5) and `compare_verdicts` says `not_comparable`, naming what differs, without looking at it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence, Set
from enum import StrEnum
from typing import Any, Literal

import numpy as np
from kinetra_core import (
    Assumption,
    FixedDistribution,
    InstanceParameterBinding,
    MaterialPropertyBinding,
    Frame,
    NormalDistribution,
    PlatformTag,
    Project,
    RunEnded,
    RunKind,
    RunStarted,
    UniformDistribution,
    VerdictAssumptionTable,
    load_body,
    verdict_assumption_table,
)
from kinetra_core.frames import MAX_SEED
from kinetra_engine.parts import PartCache
from kinetra_engine.run import PreviewRun, end_tick
from kinetra_engine.compiler import contact_friction
from kinetra_engine.run.preview import CompiledModel
from pydantic import BaseModel, ConfigDict, model_validator

from .goal import Goal, Status, evaluate_goal

Z_95 = 1.959963984540054
"""The two-sided 95% standard normal quantile (Φ⁻¹(0.975)), the legacy `wilson_ci` default."""

ENGINE_APPLIED = frozenset({"ground_friction"})
"""Planet rows applied independently of a project binding (`PreviewRun(ground_friction=)`, `to_mjcf`, W-03c).
Bound project rows are added by `run_verdict`; unbound rows remain `not_applied`."""

VERDICT_LABEL = "몬테카를로 판정: 가정표의 분포에서 뽑은 표본마다 시뮬을 한 번씩 돌려 성공 조건을 평가했다"
CI_LABEL = "95% 신뢰구간은 Wilson 점수 구간이다. 표본 수에서 오는 불확실성만 담고 모델의 근사에서 오는 오차는 담지 않는다"
PLATFORM_LABEL = "이 p_success는 함께 기록한 플랫폼 태그에서 낸 값이다. 태그가 다른 실행의 p_success와 같은 값이라고 보지 않는다"


def _undetermined_label(k: int) -> str:
    return f"판단 불가 {k}개 표본은 p_success와 신뢰구간의 분모에서 뺐다"


def _not_applied_label(key: str) -> str:
    return f"미적용: 가정 '{key}'의 분포는 모델이 읽지 않아 흔들지 않았다"


# --- seeds and samples (legacy port) -----------------------------------------------------------------------------


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def derive_seed(seed: int, *tags: Any) -> int:
    """A 32-bit seed for the stream named by `tags` under `seed`: the first 8 hex digits of SHA-256 over
    `"{seed}|" + canonical JSON of the tags` (legacy `derive_seed`)."""
    h = hashlib.sha256(f"{int(seed)}|".encode() + _canonical_json(list(tags)).encode()).hexdigest()
    return int(h[:8], 16)


def sample_assumption(a: Assumption, n: int, seed: int) -> tuple[float, ...]:
    """`n` draws of row `a` under `seed`, from its own stream `derive_seed(seed, "assumption", a.key)`."""
    d = a.distribution
    if isinstance(d, FixedDistribution):
        return (float(a.value.value),) * n
    rng = np.random.default_rng(derive_seed(seed, "assumption", a.key))
    if isinstance(d, UniformDistribution):
        x = rng.uniform(d.low, d.high, n)
    elif isinstance(d, NormalDistribution):
        x = rng.normal(d.mean, d.std, n)
        x = np.clip(x, -np.inf if d.clip_low is None else d.clip_low, np.inf if d.clip_high is None else d.clip_high)
    else:  # the Distribution union is closed; a new kind must be sampled here before it can be judged
        raise TypeError(f"unsupported distribution {d!r}")
    return tuple(float(v) for v in x)


def sample_assumptions(rows: Sequence[Assumption], n: int, seed: int) -> dict[str, tuple[float, ...]]:
    """`n` joint samples of `rows`: sample i is `{key: values[key][i]}`."""
    return {a.key: sample_assumption(a, n, seed) for a in rows}


def is_random(a: Assumption) -> bool:
    """Whether the row has a spread (legacy `is_random`): not `fixed`, not a uniform of one point, not a normal of std 0."""
    d = a.distribution
    if isinstance(d, UniformDistribution):
        return d.low != d.high
    if isinstance(d, NormalDistribution):
        return d.std != 0
    return False


def wilson_ci(k: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval of `k` successes in `n` trials, widened to contain k/n (legacy). Raises `ValueError` for n < 1."""
    if n < 1 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n >= 1, got k={k}, n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, min(p, centre - half)), min(1.0, max(p, centre + half))


# --- the verdict -------------------------------------------------------------------------------------------------


REQUEST_FIELDS = ("definition_hash", "goal_hash", "assumptions_hash", "duration_s", "timestep_s", "n_samples", "seed")
"""What a verdict was asked: the project, the condition set, the assumption table, the run length and step, the sample count and
the seed. Two verdicts are a reproduction of each other only when all of these are equal (`compare_verdicts`)."""


def _sha256(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(obj).encode()).hexdigest()


def goal_hash(goal: Goal) -> str:
    """SHA-256 over the canonical JSON of the goal's conditions."""
    return _sha256(goal.model_dump(mode="json"))


def assumptions_hash(table: VerdictAssumptionTable) -> str:
    """SHA-256 over the canonical JSON of the verdict table: its planet and its rows in order (nominal, distribution, badges)."""
    return _sha256({"planet": table.planet, "rows": [a.model_dump(mode="json") for a in table.rows]})


class Verdict(BaseModel):
    """A Monte Carlo verdict, recorded with the platform tag of its runs (engine.md 5.4 H1) and its request (`REQUEST_FIELDS`).
    `p_success`, `ci_low`, `ci_high` are over the determined samples (`n_met + n_failed`) and `None` when there is none.
    `sampled` are the shaken rows that entered the model, `sampled_values` their draws in sample order, and
    `not_applied` the shaken rows that did not. `model_labels` are the runs' (`RunStarted.model_labels`, in first-seen
    order), `labels` the verdict's own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    badge: Literal["sim"]
    planet: str
    definition_hash: str
    goal_hash: str
    assumptions_hash: str
    duration_s: float
    timestep_s: float
    seed: int
    n_samples: int
    n_met: int
    n_failed: int
    n_undetermined: int
    p_success: float | None
    ci_low: float | None
    ci_high: float | None
    ci_method: Literal["wilson_95"]
    platform: PlatformTag
    sampled: tuple[str, ...]
    sampled_values: dict[str, tuple[float, ...]]
    """The actual draw of every `sampled` row, in sample order; values use the row's unit."""
    not_applied: tuple[str, ...]
    model_labels: tuple[str, ...]
    labels: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent(self) -> "Verdict":
        if min(self.n_met, self.n_failed, self.n_undetermined) < 0 or self.n_met + self.n_failed + self.n_undetermined != self.n_samples:
            raise ValueError("n_met + n_failed + n_undetermined must be n_samples")
        determined = self.n_met + self.n_failed
        if determined == 0:
            if (self.p_success, self.ci_low, self.ci_high) != (None, None, None):
                raise ValueError("no determined sample: p_success and the CI are None")
        else:
            if self.p_success != self.n_met / determined or (self.ci_low, self.ci_high) != wilson_ci(self.n_met, determined):
                raise ValueError("p_success and the CI must be the Wilson 95% of n_met over n_met + n_failed")
        if set(self.sampled_values) != set(self.sampled) or any(len(v) != self.n_samples for v in self.sampled_values.values()):
            raise ValueError("sampled_values must contain exactly n_samples draws for every sampled row")
        return self


RunSample = Callable[[int, Mapping[str, float]], tuple[RunStarted, Sequence[Frame], RunEnded]]
"""Runs sample `i` with the table's values `{key: value}` and returns its whole stream (`run_started`, frames, `run_ended`)."""


def monte_carlo(
    table: VerdictAssumptionTable,
    goal: Goal,
    *,
    n: int,
    seed: int,
    duration_s: float,
    applied: Set[str],
    run_sample: RunSample,
) -> Verdict:
    """Draw `n` samples of `table` under `seed`, run each with `run_sample` (runs of `duration_s`), evaluate `goal` on each
    stream, and count.

    Raises `ValueError` when a run is not a `verdict_sample`, or the runs disagree on the platform tag, the project
    (`definition_hash`), the planet or the time step, or the planet is not the table's, or a run did not run the requested
    `duration_s`: such runs do not make one verdict. A run's length is its own `last_tick × timestep_s`: it must end at
    `end_tick(duration_s, timestep_s)` (the tick a run of `duration_s` ends at, `kinetra_engine.run.end_tick`), whether it
    completed or was stopped there. Only a run the engine could not go on with (`failed`) may end earlier; it is counted,
    and its undecided conditions make it `undetermined`."""
    if not 1 <= n:
        raise ValueError(f"n must be at least 1, got {n}")
    if not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be in 0 .. {MAX_SEED}, got {seed}")
    rows = table.rows
    values = sample_assumptions(rows, n, seed)
    counts = {Status.MET: 0, Status.FAILED: 0, Status.UNDETERMINED: 0}
    first: RunStarted | None = None
    model_labels: dict[str, None] = {}
    for i in range(n):
        started, frames, ended = run_sample(i, {k: v[i] for k, v in values.items()})
        if started.kind != RunKind.VERDICT_SAMPLE:
            raise ValueError(f"sample {i}: run kind {started.kind.value!r}; a verdict counts only verdict_sample runs")
        if first is None:
            first = started
            if started.planet != table.planet:
                raise ValueError(f"sample {i}: run on {started.planet!r}, table of {table.planet!r}")
        elif started.platform != first.platform:
            raise ValueError(f"sample {i}: platform tag differs from sample 0; one verdict has one tag (engine.md 5.4 H1)")
        elif (started.definition_hash, started.planet, started.timestep_s) != (first.definition_hash, first.planet, first.timestep_s):
            raise ValueError(f"sample {i}: a different project, planet or time step than sample 0")
        model_labels.update(dict.fromkeys(started.model_labels))
        result = evaluate_goal(goal, started, frames, ended)  # checks the stream first (`check_run`)
        expected, reason = end_tick(duration_s, started.timestep_s), ended.end.reason
        if ended.last_tick > expected or (ended.last_tick < expected and reason != "failed"):
            raise ValueError(
                f"sample {i}: ran to tick {ended.last_tick} ({ended.last_tick * started.timestep_s:g} s, {reason}); the request is "
                f"{duration_s:g} s, which ends at tick {expected}"
            )
        counts[result.status] += 1
    assert first is not None  # n >= 1
    met, failed, undetermined = counts[Status.MET], counts[Status.FAILED], counts[Status.UNDETERMINED]
    shaken = [a.key for a in rows if is_random(a)]
    sampled = tuple(k for k in shaken if k in applied)
    not_applied = tuple(k for k in shaken if k not in applied)
    labels = [VERDICT_LABEL, CI_LABEL, PLATFORM_LABEL]
    labels += [_not_applied_label(k) for k in not_applied]
    if undetermined:
        labels.append(_undetermined_label(undetermined))
    determined = met + failed
    p, ci = (met / determined, wilson_ci(met, determined)) if determined else (None, (None, None))
    return Verdict(
        badge="sim",
        planet=first.planet,
        definition_hash=first.definition_hash,
        goal_hash=goal_hash(goal),
        assumptions_hash=assumptions_hash(table),
        duration_s=duration_s,
        timestep_s=first.timestep_s,
        seed=seed,
        n_samples=n,
        n_met=met,
        n_failed=failed,
        n_undetermined=undetermined,
        p_success=p,
        ci_low=ci[0],
        ci_high=ci[1],
        ci_method="wilson_95",
        platform=first.platform,
        sampled=sampled,
        sampled_values={key: values[key] for key in sampled},
        not_applied=not_applied,
        model_labels=tuple(model_labels),
        labels=tuple(labels),
    )


def _consumed_bindings(project: Project, compiled: CompiledModel, duration_s: float) -> frozenset[str]:
    """Input reads, not mere references: unused definitions and descriptive specs are not physics inputs."""
    tree = compiled.tree
    parts = {p.id: p for p in tree.design.parts}
    instances = {i.id: i for i in tree.design.instances}
    parameters: set[tuple[str, str]] = set()
    materials: set[tuple[str, str]] = set()
    specs: set[tuple[str, str]] = set()
    for ci in tree.instances:
        parameters.update((ci.instance, p.name) for p in ci.properties.derivation.parameters)
        parameters.update((ci.instance, p.name) for p in ci.proxy.derivation.parameters)
        if ci.properties.derivation.material_id is not None:
            materials.add((ci.properties.derivation.material_id, "density"))
    for geom in contact_friction(tree).geoms:
        if geom.origin == "material":
            materials.add((instances[geom.instance].material, "friction"))
        elif geom.origin == "tread":
            specs.add((geom.part, "tread_friction_kinetic"))
    for prop in tree.terrain:
        if prop.material is not None:
            materials.add((prop.material, "friction"))
    for joint in tree.joints:
        for ref in (joint.a, joint.b):
            inst = instances[ref.instance]
            snap = next(s for s in parts[inst.part].snap_points if s.id == ref.snap_point)
            for axis in (snap.position.x, snap.position.y, snap.position.z):
                parameters.update((inst.id, term.param) for term in axis.terms)
    for spring in compiled.drives.springs:
        parameters.update((spring.instance, name) for name in ("stiffness", "damping"))
    active = {e.actuator for e in tree.design.schedule.actuations if e.command != 0 and e.start < duration_s}
    for motor in compiled.drives.motors:
        if motor.actuator in active and motor.supply is not None:
            specs.update((motor.part.id, name) for name in ("rated_voltage", "no_load_current", "stall_current"))
            source = instances[motor.supply]
            specs.add((source.part, "energy_capacity"))
            parameters.add((source.id, "initial_charge"))
    for thruster in compiled.thrust.thrusters:
        if thruster.actuator in active:
            part = instances[thruster.instance].part
            specs.add((part, "rated_thrust"))
            if thruster.supply is not None:
                specs.add((part, "propellant_flow"))
            nozzle = next(s for s in parts[part].snap_points if s.id == "nozzle")
            for axis in (nozzle.position.x, nozzle.position.y, nozzle.position.z):
                parameters.update((thruster.instance, term.param) for term in axis.terms)
    for store in compiled.thrust.stores:
        parameters.update((store.instance, name) for name in ("propellant_density", "initial_fill"))
    for entry in tree.design.schedule.entries:
        if entry.type == "separate" and entry.at < duration_s:
            parameters.add((entry.separator, "separation_impulse"))
    consumed = set()
    for row in project.assumptions.assumptions:
        binding = row.binding
        if isinstance(binding, InstanceParameterBinding):
            used = (binding.instance, binding.parameter) in parameters
        elif isinstance(binding, MaterialPropertyBinding):
            used = (binding.material, binding.property) in materials
        else:
            used = binding is not None and (binding.part, binding.spec) in specs
        if used:
            consumed.add(row.key)
    return frozenset(consumed)


def _run_verdict_table(
    project: Project,
    goal: Goal,
    table: VerdictAssumptionTable,
    *,
    n: int,
    seed: int,
    duration_s: float,
    project_id: str,
    revision: int,
    cache: PartCache | None = None,
) -> Verdict:
    """Run a verdict table against the same project and engine path as `run_verdict`.

    J-03 supplies a counterfactual table with one row pinned. Its independent per-row streams leave every other row's
    draws unchanged; the pinned table also gives the counterfactual its own honest `assumptions_hash`.
    """
    applied = set(ENGINE_APPLIED) | {a.key for a in project.assumptions.assumptions if a.binding is not None}

    def run_sample(i: int, values: Mapping[str, float]) -> tuple[RunStarted, Sequence[Frame], RunEnded]:
        run = PreviewRun(
            project,
            run_id=f"verdict-{seed}-{i}",
            project_id=project_id,
            revision=revision,
            duration_s=duration_s,
            seed=seed,
            kind=RunKind.VERDICT_SAMPLE,
            frame_every_ticks=1,
            cache=cache,
            ground_friction=values["ground_friction"],
            assumption_values=values,
        )
        applied.intersection_update(ENGINE_APPLIED | _consumed_bindings(project, run.compiled, duration_s))
        stream = list(run)
        return run.started, stream[:-1], stream[-1]

    return monte_carlo(table, goal, n=n, seed=seed, duration_s=duration_s, applied=applied, run_sample=run_sample)


def run_verdict(
    project: Project,
    goal: Goal,
    *,
    n: int,
    seed: int,
    duration_s: float,
    project_id: str,
    revision: int,
    cache: PartCache | None = None,
) -> Verdict:
    """The verdict of `project` on `goal` from the engine: the table is `verdict_assumption_table` of the project on its
    planet (W-03c), and sample i is one `PreviewRun` of kind `verdict_sample` (run id `verdict-{seed}-{i}`, the verdict's
    seed, one frame per tick) with the ground at the sample's `ground_friction` and every bound project row applied to its
    typed target. The base project is never mutated; its hash remains the run/request identity."""
    table = verdict_assumption_table(project.assumptions, load_body(project.world.planet))
    return _run_verdict_table(
        project, goal, table, n=n, seed=seed, duration_s=duration_s,
        project_id=project_id, revision=revision, cache=cache,
    )


class VerdictComparison(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARABLE = "not_comparable"


class VerdictComparisonResult(BaseModel):
    """`status` and the fields behind it: for `not_comparable` the request fields that differ (then `platform` when the tags
    differ too, or `platform` alone); for `mismatch` the recorded fields that differ; empty for `match`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: VerdictComparison
    differs: tuple[str, ...]


def compare_verdicts(a: Verdict, b: Verdict) -> VerdictComparisonResult:
    """Whether `b` reproduces `a`. `not_comparable` when they were not the same request (`REQUEST_FIELDS`) or their platform
    tags differ: p_success is then not looked at (H5). Else `match` when every recorded field is equal, `mismatch` otherwise (H2)."""
    differs = tuple(f for f in REQUEST_FIELDS if getattr(a, f) != getattr(b, f))
    differs += ("platform",) if a.platform != b.platform else ()
    if differs:
        return VerdictComparisonResult(status=VerdictComparison.NOT_COMPARABLE, differs=differs)
    differs = tuple(f for f in Verdict.model_fields if getattr(a, f) != getattr(b, f))
    return VerdictComparisonResult(status=VerdictComparison.MISMATCH if differs else VerdictComparison.MATCH, differs=differs)
