"""Shared Monte-Carlo sampler over Assumption distributions + CI helpers.

Everything is deterministic: each assumption gets its own RNG stream derived from
``(seed, key)`` so adding/removing an assumption never shifts the others, and the same
``(spec, seed, n)`` always yields the same samples (common random numbers across OAT runs).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable

import numpy as np
from scipy import stats

from physlab_core.schemas import Assumption, Fixed, Normal, SpecSheet, Uniform

from .base import McResult

# --------------------------------------------------------------------------- hashing / seeds


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def spec_hash(spec: SpecSheet) -> str:
    """sha256 over the canonical JSON of the SpecSheet (docs/judgment-spec.md R6)."""
    return hashlib.sha256(canonical_json(spec.model_dump(mode="json")).encode()).hexdigest()


def spec_seed(spec: SpecSheet) -> int:
    """Seed derivation of judgment-spec R6: int(sha256(canonical_json(spec))[:8], 16)."""
    return int(spec_hash(spec)[:8], 16)


def derive_seed(seed: int, *tags: Any) -> int:
    h = hashlib.sha256(f"{int(seed)}|" .encode() + canonical_json(list(tags)).encode()).hexdigest()
    return int(h[:8], 16)


# --------------------------------------------------------------------------- confidence intervals


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval; (0, 1) when n == 0. Always contains k/n."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, min(p, centre - half)), min(1.0, max(p, centre + half))


def clopper_pearson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Exact (conservative) binomial interval."""
    if n <= 0:
        return 0.0, 1.0
    lo = 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(1 - alpha / 2, k + 1, n - k))
    return lo, hi


# --------------------------------------------------------------------------- sampling


def sample_assumption(a: Assumption, n: int, seed: int) -> np.ndarray:
    d = a.distribution
    rng = np.random.default_rng(derive_seed(seed, "assumption", a.key))
    if isinstance(d, Fixed):
        return np.full(n, float(a.value))
    if isinstance(d, Uniform):
        return rng.uniform(d.low, d.high, n)
    if isinstance(d, Normal):
        x = rng.normal(d.mean, d.std, n)
        lo = -np.inf if d.clip_low is None else d.clip_low
        hi = np.inf if d.clip_high is None else d.clip_high
        return np.clip(x, lo, hi)
    raise TypeError(f"unsupported distribution {d!r}")


def sample_assumptions(
    spec: SpecSheet,
    n: int,
    seed: int,
    aux: Callable[[int, int], dict[str, np.ndarray]] | None = None,
) -> dict[str, np.ndarray]:
    """Draw ``n`` joint samples. Keys = assumption keys; ``aux(n, seed)`` may add extra
    template-specific columns (names starting with '_'), sliced together with the rest."""
    out = {a.key: sample_assumption(a, n, seed) for a in spec.assumptions}
    if aux is not None:
        out.update(aux(n, seed))
    return out


def quantile(a: Assumption, q: float) -> float:
    """q-quantile of the assumption's distribution (the nominal value for 'fixed')."""
    d = a.distribution
    if isinstance(d, Fixed):
        return float(a.value)
    if isinstance(d, Uniform):
        return float(d.low + q * (d.high - d.low))
    x = float(d.mean + d.std * stats.norm.ppf(q))
    lo = -np.inf if d.clip_low is None else d.clip_low
    hi = np.inf if d.clip_high is None else d.clip_high
    return float(min(max(x, lo), hi))


def is_random(a: Assumption) -> bool:
    d = a.distribution
    return not isinstance(d, Fixed) and not (isinstance(d, Uniform) and d.low == d.high) and not (
        isinstance(d, Normal) and d.std == 0
    )


def slice_samples(samples: dict[str, np.ndarray], n: int) -> dict[str, np.ndarray]:
    return {k: v[:n] for k, v in samples.items()}


# --------------------------------------------------------------------------- MC driver

Evaluate = Callable[[dict[str, np.ndarray]], "tuple[np.ndarray, dict[str, np.ndarray]]"]


def run_mc(
    evaluate: Evaluate,
    spec: SpecSheet,
    n: int,
    seed: int,
    *,
    taxonomy: dict[str, str] | None = None,
    aux: Callable[[int, int], dict[str, np.ndarray]] | None = None,
    oat: bool = True,
    n_oat: int = 64,
    q_lo: float = 0.05,
    q_hi: float = 0.95,
) -> McResult:
    """Monte-Carlo over the SpecSheet's assumption distributions.

    ``evaluate(samples) -> (success[m] bool, failed{check_name: bool[m]})`` is the template's
    rollout judge. Failure counts are reported per taxonomy code (``taxonomy`` maps the template's
    fine-grained check names to docs/judgment-spec.md section-A codes); a sample counts once per
    code. Fine-grained counts are attached as ``binding['failed_checks']``.

    One-at-a-time sensitivities: for each random assumption, re-evaluate the first ``n_oat`` samples
    with that assumption pinned at its ``q_lo`` and ``q_hi`` quantile (others unchanged, common
    random numbers). ``effect = p(q_hi) - p(q_lo)`` (signed change in p_success).
    """
    samples = sample_assumptions(spec, n, seed, aux)
    success, failed = evaluate(samples)
    success = np.asarray(success, bool)
    taxonomy = taxonomy or {}
    codes: dict[str, np.ndarray] = {}
    fine: dict[str, int] = {}
    for name, f in failed.items():
        f = np.asarray(f, bool)
        if f.any():
            fine[name] = int(f.sum())
            code = taxonomy.get(name, name)
            codes[code] = codes[code] | f if code in codes else f.copy()
    failure_counts = {c: int(v.sum()) for c, v in codes.items()}

    sens: list[dict[str, Any]] = []
    if oat:
        m = min(n_oat, n)
        sub = slice_samples(samples, m)
        for a in spec.assumptions:
            if not is_random(a):
                continue
            ps = []
            for q in (q_lo, q_hi):
                pinned = dict(sub)
                pinned[a.key] = np.full(m, quantile(a, q))
                s, _ = evaluate(pinned)
                ps.append(float(np.asarray(s, bool).mean()))
            sens.append(dict(assumption_key=a.key, effect=round(ps[1] - ps[0], 4), method="one_at_a_time",
                             detail=dict(p_at_q05=ps[0], p_at_q95=ps[1], n=m)))
        sens.sort(key=lambda s: -abs(s["effect"]))
        for i, s in enumerate(sens):
            s["rank"] = i + 1
    return McResult(
        n=int(n),
        n_success=int(success.sum()),
        failure_counts=failure_counts,
        sensitivities=sens,
        binding=dict(failed_checks=fine),
    )


def feasibility_fields(res: McResult) -> dict[str, Any]:
    lo, hi = wilson_ci(res.n_success, res.n)
    p = res.n_success / res.n if res.n else 0.0
    return dict(p_success=p, ci_low=min(lo, p), ci_high=max(hi, p), n_samples=res.n, ci_method="wilson_95")
