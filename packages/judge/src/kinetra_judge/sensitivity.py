"""J-03 one-at-a-time sensitivity ranking over real Monte-Carlo verdicts.

The baseline is `run_verdict` itself. Only its `sampled` rows are varied: those are the random rows whose values the
compiled model actually consumed, including typed project bindings. Each row is pinned at its 5% and 95% distribution
quantiles while every other row keeps the same per-key RNG stream, seed and sample index (common random numbers).
Unbound and bound-but-unconsumed rows stay in `not_applied`; they are not ranked as if sensitivity had been measured.

This is a local, two-point, one-factor-at-a-time comparison, not global sensitivity analysis. It does not measure
interactions, and a large difference between two finite Monte-Carlo verdicts is not causal proof or a guarantee about
values between or beyond the pins.
"""

from __future__ import annotations

from statistics import NormalDist
from typing import Literal

from kinetra_core import (
    Assumption,
    Badge,
    FixedDistribution,
    NormalDistribution,
    PlatformTag,
    Project,
    Quantity,
    Source,
    UniformDistribution,
    VerdictAssumptionTable,
    load_body,
    verdict_assumption_table,
)
from kinetra_engine.parts import PartCache
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .goal import Goal
from .mc import Verdict, _run_verdict_table, is_random, run_verdict, wilson_ci

SENSITIVITY_METHOD = "one_at_a_time_q05_q95"
SENSITIVITY_METHOD_LABEL = (
    "민감도는 가정 하나씩을 분포의 5%·95% 분위수로 고정하고 나머지 가정은 기준 판정과 같은 시드·표본 인덱스로 유지해 "
    "실제 시뮬 몬테카를로 판정을 다시 계산했다"
)
SENSITIVITY_FLIP_LABEL = (
    "판정 뒤집기는 기준 p_success와 고정 표본의 p_success가 0.5의 엄격히 반대편에 있는 경우만 뜻한다. "
    "한쪽이 0.5이거나 판단된 표본이 없으면 뒤집기로 세지 않는다"
)
SENSITIVITY_LIMIT_LABEL = (
    "두 분위수에서의 일변량 국소 비교다. 가정 사이 상호작용과 전역 민감도는 측정하지 않으며, 몬테카를로 표본 오차와 "
    "모델 근사 오차가 남는다. 이 순위 하나만으로 인과나 최종 실현 가능성을 단정하지 않는다"
)


def _crosses_half(baseline: float | None, counterfactual: float | None) -> bool | None:
    if baseline is None or counterfactual is None:
        return None
    return (baseline - 0.5) * (counterfactual - 0.5) < 0


class SensitivityScenario(BaseModel):
    """One pinned counterfactual and the numbers of its actual engine verdict.

    `value` is computed from the original row's declared distribution, not measured or cited independently;
    `value_source` records that derivation. The verdict numbers retain their simulation provenance and platform tag.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    quantile: float = Field(strict=True, gt=0, lt=1, allow_inf_nan=False)
    value: float = Field(strict=True, allow_inf_nan=False)
    value_source: Literal["original_assumption_distribution_quantile"]
    assumptions_hash: str
    seed: int
    platform: PlatformTag
    n_samples: int = Field(ge=1)
    n_met: int = Field(ge=0)
    n_failed: int = Field(ge=0)
    n_undetermined: int = Field(ge=0)
    p_success: float | None = Field(default=None, ge=0, le=1)
    ci_low: float | None = Field(default=None, ge=0, le=1)
    ci_high: float | None = Field(default=None, ge=0, le=1)
    crosses_baseline: bool | None

    @model_validator(mode="after")
    def _consistent_verdict_numbers(self) -> "SensitivityScenario":
        if self.n_met + self.n_failed + self.n_undetermined != self.n_samples:
            raise ValueError("n_met + n_failed + n_undetermined must be n_samples")
        determined = self.n_met + self.n_failed
        expected = (
            (None, None, None) if determined == 0
            else (self.n_met / determined, *wilson_ci(self.n_met, determined))
        )
        if (self.p_success, self.ci_low, self.ci_high) != expected:
            raise ValueError("scenario p_success and CI must come from its counted verdict samples")
        return self

    @classmethod
    def from_verdict(
        cls, verdict: Verdict, *, quantile: float, value: float, baseline_p: float | None,
    ) -> "SensitivityScenario":
        return cls(
            quantile=quantile,
            value=value,
            value_source="original_assumption_distribution_quantile",
            assumptions_hash=verdict.assumptions_hash,
            seed=verdict.seed,
            platform=verdict.platform,
            n_samples=verdict.n_samples,
            n_met=verdict.n_met,
            n_failed=verdict.n_failed,
            n_undetermined=verdict.n_undetermined,
            p_success=verdict.p_success,
            ci_low=verdict.ci_low,
            ci_high=verdict.ci_high,
            crosses_baseline=_crosses_half(baseline_p, verdict.p_success),
        )


class SensitivityRow(BaseModel):
    """One applied assumption, ranked by `abs(p_at_q95 - p_at_q05)` with key-order tie breaking."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(ge=1)
    assumption_key: str
    label: str
    unit: str
    low: SensitivityScenario
    high: SensitivityScenario
    effect: float | None = Field(default=None, ge=-1, le=1)
    """Signed `high.p_success - low.p_success`; `None` when either verdict has no determined sample."""
    flips_verdict: bool | None
    """Whether either pin strictly crosses the baseline over 0.5; `None` when the available evidence cannot decide."""

    @model_validator(mode="after")
    def _consistent_measurements(self) -> "SensitivityRow":
        if (self.low.quantile, self.high.quantile) != (0.05, 0.95):
            raise ValueError("sensitivity scenarios must be the 5% and 95% quantiles")
        expected = (
            self.high.p_success - self.low.p_success
            if self.low.p_success is not None and self.high.p_success is not None else None
        )
        if self.effect != expected:
            raise ValueError("effect must be high.p_success - low.p_success")
        crosses = (self.low.crosses_baseline, self.high.crosses_baseline)
        expected_flip = True if any(v is True for v in crosses) else None if any(v is None for v in crosses) else False
        if self.flips_verdict != expected_flip:
            raise ValueError("flips_verdict must follow the two baseline-crossing measurements")
        return self


class SensitivityReport(BaseModel):
    """Simulation-derived sensitivity data for the existing verdict report; no UI-specific view model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    badge: Literal["sim"]
    method: Literal["one_at_a_time_q05_q95"]
    baseline: Verdict
    assumptions: tuple[Assumption, ...]
    """The original, unpinned verdict table, including each value/distribution badge, source and typed binding."""
    rows: tuple[SensitivityRow, ...]
    """Only baseline `sampled` rows, in measured-effect rank order."""
    not_applied: tuple[str, ...]
    """Random rows the model did not consume. No counterfactual was run and no sensitivity is claimed for them."""
    fixed: tuple[str, ...]
    """Rows without a spread; there is no distribution variation to measure."""
    dominant_flip_assumption: str | None
    """The highest-ranked row with a measured strict 0.5 crossing, or `None` when no such row exists."""
    labels: tuple[str, ...]

    @model_validator(mode="after")
    def _consistent_report(self) -> "SensitivityReport":
        assumptions = {a.key: a for a in self.assumptions}
        if len(assumptions) != len(self.assumptions):
            raise ValueError("duplicate sensitivity assumption key")
        if self.not_applied != self.baseline.not_applied or set(self.not_applied) - assumptions.keys():
            raise ValueError("not_applied must be the baseline verdict's unconsumed random rows")
        expected_fixed = tuple(a.key for a in self.assumptions if not is_random(a))
        if self.fixed != expected_fixed:
            raise ValueError("fixed must name exactly the rows without a spread")
        ranked_keys = tuple(r.assumption_key for r in self.rows)
        if len(set(ranked_keys)) != len(ranked_keys) or set(ranked_keys) != set(self.baseline.sampled):
            raise ValueError("ranked rows must be exactly the baseline sampled assumptions")
        if any(r.assumption_key not in assumptions for r in self.rows):
            raise ValueError("ranked sensitivity row is missing its original assumption")
        if tuple(r.rank for r in self.rows) != tuple(range(1, len(self.rows) + 1)):
            raise ValueError("sensitivity ranks must be consecutive from one")
        expected_order = tuple(sorted(self.rows, key=_row_order))
        if self.rows != expected_order:
            raise ValueError("sensitivity rows are not in measured-effect order")
        for row in self.rows:
            for scenario in (row.low, row.high):
                if (scenario.seed, scenario.platform, scenario.n_samples) != (
                    self.baseline.seed, self.baseline.platform, self.baseline.n_samples,
                ):
                    raise ValueError("counterfactual must use the baseline seed, platform and sample count")
                if scenario.crosses_baseline != _crosses_half(self.baseline.p_success, scenario.p_success):
                    raise ValueError("scenario crossing must be measured against the baseline p_success")
        expected_dominant = next((r.assumption_key for r in self.rows if r.flips_verdict is True), None)
        if self.dominant_flip_assumption != expected_dominant:
            raise ValueError("dominant flip assumption must be the highest-ranked measured crossing")
        return self


def _row_order(row: SensitivityRow) -> tuple[bool, float, str]:
    return row.effect is None, -abs(row.effect or 0.0), row.assumption_key


def _quantile(a: Assumption, q: float) -> float:
    d = a.distribution
    if isinstance(d, UniformDistribution):
        return d.low + q * (d.high - d.low)
    if isinstance(d, NormalDistribution):
        value = NormalDist(mu=d.mean, sigma=d.std).inv_cdf(q)
        if d.clip_low is not None:
            value = max(value, d.clip_low)
        if d.clip_high is not None:
            value = min(value, d.clip_high)
        return value
    raise ValueError(f"assumption {a.key!r} has no distribution quantile to vary")


def _pinned_table(table: VerdictAssumptionTable, key: str, q: float, value: float) -> VerdictAssumptionTable:
    """Make one counterfactual fixed row with explicit derived-value provenance; never mutate the original table."""
    original = table.row(key)
    distribution_source = getattr(original.distribution, "source", None)
    source = Source(
        ref=(
            f"J-03 one-at-a-time pin: q={q:g} of the original distribution for {key!r}; "
            f"original spread evidence: {distribution_source.ref if distribution_source is not None else 'fixed row'}"
        ),
        locator="kinetra_judge.sensitivity._quantile",
    )
    pinned = original.model_copy(update={
        "value": Quantity(value=value, unit=original.value.unit, badge=Badge.ESTIMATE, source=source),
        "distribution": FixedDistribution(kind="fixed"),
    })
    if key in {a.key for a in table.planet_rows}:
        return table.model_copy(update={
            "planet_rows": tuple(pinned if a.key == key else a for a in table.planet_rows),
        })
    project = table.project.model_copy(update={
        "assumptions": tuple(pinned if a.key == key else a for a in table.project.assumptions),
    })
    return table.model_copy(update={"project": project})


def run_sensitivity(
    project: Project,
    goal: Goal,
    *,
    n: int,
    seed: int,
    duration_s: float,
    project_id: str,
    revision: int,
    cache: PartCache | None = None,
) -> SensitivityReport:
    """Measure and rank actual verdict changes for every random, model-consumed assumption.

    Runs `n * (1 + 2 * len(baseline.sampled))` real engine samples. A row is eligible only after the baseline's typed
    binding consumption check puts it in `sampled`; unbound and unconsumed rows are reported separately and are never
    silently treated as zero measured sensitivity.
    """
    table = verdict_assumption_table(project.assumptions, load_body(project.world.planet))
    baseline = run_verdict(
        project, goal, n=n, seed=seed, duration_s=duration_s,
        project_id=project_id, revision=revision, cache=cache,
    )
    measured: list[tuple[Assumption, SensitivityScenario, SensitivityScenario]] = []
    for key in baseline.sampled:
        a = table.row(key)
        scenarios = []
        for q in (0.05, 0.95):
            value = _quantile(a, q)
            counterfactual = _run_verdict_table(
                project, goal, _pinned_table(table, key, q, value), n=n, seed=seed, duration_s=duration_s,
                project_id=project_id, revision=revision, cache=cache,
            )
            scenarios.append(SensitivityScenario.from_verdict(
                counterfactual, quantile=q, value=value, baseline_p=baseline.p_success,
            ))
        measured.append((a, scenarios[0], scenarios[1]))

    def order(item: tuple[Assumption, SensitivityScenario, SensitivityScenario]) -> tuple[bool, float, str]:
        a, low, high = item
        effect = high.p_success - low.p_success if low.p_success is not None and high.p_success is not None else None
        return effect is None, -abs(effect or 0.0), a.key

    rows = []
    for rank, (a, low, high) in enumerate(sorted(measured, key=order), 1):
        effect = high.p_success - low.p_success if low.p_success is not None and high.p_success is not None else None
        crosses = (low.crosses_baseline, high.crosses_baseline)
        flips = True if any(v is True for v in crosses) else None if any(v is None for v in crosses) else False
        rows.append(SensitivityRow(
            rank=rank, assumption_key=a.key, label=a.label, unit=a.value.unit.value,
            low=low, high=high, effect=effect, flips_verdict=flips,
        ))
    ranked = tuple(rows)
    dominant = next((r.assumption_key for r in ranked if r.flips_verdict is True), None)
    labels = (SENSITIVITY_METHOD_LABEL, SENSITIVITY_FLIP_LABEL, SENSITIVITY_LIMIT_LABEL)
    labels += tuple(f"미적용: 가정 '{key}'는 모델이 소비하지 않아 민감도를 측정하지 않았다" for key in baseline.not_applied)
    return SensitivityReport(
        badge="sim",
        method=SENSITIVITY_METHOD,
        baseline=baseline,
        assumptions=table.rows,
        rows=ranked,
        not_applied=baseline.not_applied,
        fixed=tuple(a.key for a in table.rows if not is_random(a)),
        dominant_flip_assumption=dominant,
        labels=labels,
    )
