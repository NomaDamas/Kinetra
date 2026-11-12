"""Monte Carlo verdict: p_success and its 95% CI over the verdict's assumption table (J-01a; `docs/architecture/verdict-mc.md`).

    sample_assumptions(rows, n, seed) -> {key: (x_0 .. x_{n-1})}       # one RNG stream per row, from (seed, key)
    wilson_ci(k, n) -> (low, high)                                    # 95% Wilson score interval
    monte_carlo(table, goal, n=, seed=, applied=, run_sample=) -> Verdict
    run_verdict(project, goal, n=, seed=, duration_s=, project_id=, revision=) -> Verdict   # the engine's samples
    compare_verdicts(a, b) -> VerdictComparison                       # match | mismatch | not_comparable (H2, H5)

Port of the legacy sampler (`legacy-v0:packages/engine/src/kinetra_engine/mc.py`: `derive_seed`, `sample_assumption`,
`wilson_ci`, `feasibility_fields`). Kept as it was: each row draws from its own NumPy `default_rng` stream seeded by
`derive_seed(seed, "assumption", key)`, so adding or removing a row never shifts another row's samples; `fixed` is the
nominal, `uniform` is `rng.uniform(low, high, n)`, `normal` is `rng.normal(mean, std, n)` clipped to `clip_low`/`clip_high`;
the interval is Wilson's, widened to contain p. Not carried over: the one-at-a-time sensitivities (J-03), the failure
taxonomy counts (J-06), the Clopper-Pearson interval (unused by the legacy verdict).

A verdict is the simulation of every sample (V1): sample i runs the project once (`RunKind.VERDICT_SAMPLE`, one frame per
tick) with the values of row i, and `evaluate_goal` (J-02a) says `met`, `failed` or `undetermined`. p_success is
`met / (met + failed)`; undetermined samples are counted and left out of p and the CI, with a label. A table row whose
sample does not enter the model is not shaken and says so (`not_applied`): the engine reads only `ENGINE_APPLIED` today.

Platform (engine.md 5.4): a verdict carries the platform tag of its runs (H1); every sample must have the same tag, else
there is no verdict. Two verdicts are compared only under the same tag (H2); under different tags their p_success is not
called the same value (H5) and `compare_verdicts` says `not_comparable` without looking at it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Literal

import numpy as np
from kinetra_core import (
    Assumption,
    FixedDistribution,
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
from kinetra_engine.run import PreviewRun
from pydantic import BaseModel, ConfigDict, model_validator

from .goal import Goal, Status, evaluate_goal

Z_95 = 1.959963984540054
"""The two-sided 95% standard normal quantile (Φ⁻¹(0.975)), the legacy `wilson_ci` default."""

ENGINE_APPLIED = frozenset({"ground_friction"})
"""The table rows whose sample `run_verdict` puts into the model: the planet's ground friction (`PreviewRun(ground_friction=)`,
`to_mjcf`, W-03c). A project row has no binding to a design value yet, so the model never reads it."""

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


class Verdict(BaseModel):
    """A Monte Carlo verdict, recorded with the platform tag of its runs (engine.md 5.4 H1). `p_success`, `ci_low`, `ci_high`
    are over the determined samples (`n_met + n_failed`) and `None` when there is none. `sampled` are the shaken rows that
    entered the model, `not_applied` the shaken rows that did not. `model_labels` are the runs' (`RunStarted.model_labels`,
    in first-seen order), `labels` the verdict's own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    badge: Literal["sim"]
    planet: str
    definition_hash: str
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
        return self


RunSample = Callable[[int, Mapping[str, float]], tuple[RunStarted, Sequence[Frame], RunEnded]]
"""Runs sample `i` with the table's values `{key: value}` and returns its whole stream (`run_started`, frames, `run_ended`)."""


def monte_carlo(
    table: VerdictAssumptionTable,
    goal: Goal,
    *,
    n: int,
    seed: int,
    applied: frozenset[str],
    run_sample: RunSample,
) -> Verdict:
    """Draw `n` samples of `table` under `seed`, run each with `run_sample`, evaluate `goal` on each stream, and count.

    Raises `ValueError` when a run is not a `verdict_sample`, or the runs disagree on the platform tag, the project
    (`definition_hash`) or the planet, or the planet is not the table's: such runs do not make one verdict."""
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
        elif (started.definition_hash, started.planet) != (first.definition_hash, first.planet):
            raise ValueError(f"sample {i}: a different project or planet than sample 0")
        model_labels.update(dict.fromkeys(started.model_labels))
        counts[evaluate_goal(goal, started, frames, ended).status] += 1
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
        not_applied=not_applied,
        model_labels=tuple(model_labels),
        labels=tuple(labels),
    )


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
    seed, one frame per tick) with the ground at the sample's `ground_friction`."""
    table = verdict_assumption_table(project.assumptions, load_body(project.world.planet))

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
        )
        stream = list(run)
        return run.started, stream[:-1], stream[-1]

    return monte_carlo(table, goal, n=n, seed=seed, applied=ENGINE_APPLIED, run_sample=run_sample)


class VerdictComparison(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARABLE = "not_comparable"


def compare_verdicts(a: Verdict, b: Verdict) -> VerdictComparison:
    """Two verdicts of the same request (project, seed, sample count): `not_comparable` when their platform tags differ
    (p_success is then not looked at, H5), else `match` when every recorded field is equal and `mismatch` otherwise (H2).
    Raises `ValueError` for verdicts of different requests, which are not a reproduction of each other."""
    if (a.definition_hash, a.seed, a.n_samples) != (b.definition_hash, b.seed, b.n_samples):
        raise ValueError("not the same verdict request: definition_hash, seed and n_samples must be equal")
    if a.platform != b.platform:
        return VerdictComparison.NOT_COMPARABLE
    return VerdictComparison.MATCH if a == b else VerdictComparison.MISMATCH
