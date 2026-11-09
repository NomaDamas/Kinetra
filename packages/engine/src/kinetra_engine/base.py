"""Template contract shared by every Kinetra physics template.

A template owns: default SpecSheet, necessary-condition screen, search (CMA-ES over
low-dim params via MuJoCo rollouts), Monte-Carlo over Assumption distributions,
and trajectory export. `pipeline.run` composes these into a Verdict.
All numbers must come from simulation. Same (spec, seed, budget) => same result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from physlab_core.schemas import NecessaryCheck, SpecSheet, Trajectory, BomItem


@dataclass
class Budget:
    max_evals: int = 6000
    max_seconds: float = 60.0
    mc_samples: int = 100


@dataclass
class SearchResult:
    found: bool                      # a witness satisfying all success criteria on the NOMINAL model
    best_params: dict[str, float]    # keys == SpecSheet.param_bounds names
    n_evals: int
    wall_seconds: float
    best_cost: float
    detail: dict[str, Any] = field(default_factory=dict)  # free-form, e.g. metrics of best rollout


@dataclass
class McResult:
    n: int
    n_success: int
    failure_counts: dict[str, int]   # taxonomy code -> count (see docs/judgment-spec.md section A)
    sensitivities: list[dict[str, Any]] = field(default_factory=list)  # {assumption_key, effect, method}
    binding: dict[str, Any] | None = None  # {name, margin, unit}


class Template(Protocol):
    id: str

    def default_spec(self, idea: str, overrides: dict[str, float] | None = None) -> SpecSheet:
        """Spec with assumptions/param_bounds/success_criteria. `overrides` set assumption values by key
        (this is how sweep variants and the UI 'what-if' work)."""

    def necessary_screen(self, spec: SpecSheet) -> list[NecessaryCheck]:
        """Cheap checks; any failure with favorable-end assumptions => INFEASIBLE_NECESSARY_CONDITION."""

    def search(self, spec: SpecSheet, seed: int, budget: Budget) -> SearchResult: ...

    def monte_carlo(self, spec: SpecSheet, params: dict[str, float], seed: int, n: int) -> McResult: ...

    def rollout(self, spec: SpecSheet, params: dict[str, float], seed: int) -> Trajectory:
        """Nominal-assumption rollout of `params`, exported for Three.js replay (schema Trajectory)."""

    def bom(self, spec: SpecSheet, params: dict[str, float]) -> list[BomItem]: ...
