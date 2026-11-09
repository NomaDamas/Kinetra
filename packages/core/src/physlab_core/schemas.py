"""Shared contracts for the physical feasibility harness.

Three documents flow through the system:

    SpecSheet  (agent + human)  -> builds the MuJoCo model & search problem
    Trajectory (simulator)      -> replayed in Three.js, no MuJoCo needed
    Verdict    (judge)          -> what the user / reviewer sees

Conventions
-----------
* SI units everywhere (m, kg, s, N, rad, J) unless a field says otherwise.
* World frame is MuJoCo's: right-handed, +Z up.
* Quaternions are MuJoCo order ``[w, x, y, z]``. Three.js wants ``[x, y, z, w]``;
  the viewer must reorder.
* Verdict asymmetry (see ``VerdictStatus``): a found solution is strong evidence,
  a violated necessary condition is a strong "impossible", and "not found in
  budget" is WEAK and must never be worded as "impossible".
* All numbers in a Verdict come from tools / simulation, never from an LLM.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.1.0"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# --------------------------------------------------------------------------- #
# SpecSheet
# --------------------------------------------------------------------------- #

class TemplateId(str, Enum):
    rocket_car = "rocket_car"
    humanoid_jump = "humanoid_jump"
    drone = "drone"
    custom = "custom"  # tier-2: no verified template, experimental


class Tier(int, Enum):
    verified_template = 1
    experimental = 2


class Confidence(str, Enum):
    low = "low"
    med = "med"
    high = "high"


class Fixed(_Base):
    kind: Literal["fixed"] = "fixed"


class Uniform(_Base):
    kind: Literal["uniform"] = "uniform"
    low: float
    high: float

    @model_validator(mode="after")
    def _ordered(self):
        if not self.low <= self.high:
            raise ValueError("uniform: low must be <= high")
        return self


class Normal(_Base):
    kind: Literal["normal"] = "normal"
    mean: float
    std: float = Field(ge=0)
    clip_low: Optional[float] = None
    clip_high: Optional[float] = None


Distribution = Annotated[Union[Fixed, Uniform, Normal], Field(discriminator="kind")]


class Assumption(_Base):
    """One physical assumption shown in the human-review panel.

    ``value`` is the nominal (used by the deterministic search); ``distribution``
    is what Monte-Carlo samples from.
    """

    key: str = Field(description="Stable machine key, e.g. 'vehicle_mass'. Referenced by Verdict sensitivities.")
    label: str = Field(description="Human-readable name shown in the panel.")
    value: float
    unit: str = Field(description="SI unit string, '' if dimensionless.")
    distribution: Distribution = Field(default_factory=Fixed)
    source: str = Field(description="URL, citation, 'llm_estimate' or 'user'.")
    confidence: Confidence
    editable: bool = True


class Part(_Base):
    """A candidate real-world component (feeds BOM)."""

    name: str
    role: str = Field(description="e.g. 'thruster', 'battery', 'chassis'.")
    mass_kg: float = Field(ge=0)
    cost_usd: Optional[float] = Field(default=None, ge=0)
    source: str = Field(description="URL, citation, 'llm_estimate' or 'user'.")


class ParamBound(_Base):
    """Search variable of the optimizer (CMA-ES operates on these)."""

    name: str
    low: float
    high: float
    unit: str = ""
    init: Optional[float] = Field(default=None, description="CMA-ES starting point; defaults to midpoint.")
    description: str = ""

    @model_validator(mode="after")
    def _ordered(self):
        if not self.low < self.high:
            raise ValueError("ParamBound: low must be < high")
        if self.init is not None and not self.low <= self.init <= self.high:
            raise ValueError("ParamBound: init outside [low, high]")
        return self


class Comparator(str, Enum):
    ge = ">="
    le = "<="
    gt = ">"
    lt = "<"


class SuccessCriterion(_Base):
    """A measurable condition on a simulated rollout, e.g. rotation_deg >= 360."""

    name: str
    metric: str = Field(description="Name of a rollout metric produced by the template, e.g. 'rotation_deg'.")
    comparator: Comparator
    threshold: float
    unit: str = ""
    description: str = ""


class SpecSheet(_Base):
    schema_version: str = SCHEMA_VERSION
    idea: str = Field(description="The user's one-sentence idea, verbatim.")
    template_id: TemplateId
    tier: Tier
    assumptions: list[Assumption]
    parts: list[Part] = Field(default_factory=list)
    param_bounds: list[ParamBound] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion]

    @model_validator(mode="after")
    def _checks(self):
        keys = [a.key for a in self.assumptions]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate assumption keys")
        names = [p.name for p in self.param_bounds]
        if len(set(names)) != len(names):
            raise ValueError("duplicate param_bounds names")
        if self.template_id == TemplateId.custom and self.tier != Tier.experimental:
            raise ValueError("template_id 'custom' must be tier 2 (experimental)")
        return self


# --------------------------------------------------------------------------- #
# Trajectory
# --------------------------------------------------------------------------- #

Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Quat = Annotated[list[float], Field(min_length=4, max_length=4)]


class GeomType(str, Enum):
    box = "box"
    sphere = "sphere"
    capsule = "capsule"
    cylinder = "cylinder"
    ellipsoid = "ellipsoid"
    plane = "plane"
    mesh = "mesh"


class Geom(_Base):
    """Render hint for one geom attached to a body (MuJoCo geom_size semantics)."""

    type: GeomType
    size: list[float] = Field(description="MuJoCo geom size: box=half-extents[3], sphere=[r], capsule/cylinder=[r, half_len], plane=[hx,hy,grid].")
    pos: Vec3 = Field(default_factory=lambda: [0.0, 0.0, 0.0], description="Local to the body frame.")
    quat: Quat = Field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0], description="[w,x,y,z], local to the body frame.")
    rgba: list[float] = Field(default_factory=lambda: [0.7, 0.7, 0.7, 1.0], min_length=4, max_length=4)
    mesh: Optional[str] = Field(default=None, description="Asset name/URL when type == 'mesh'.")


class TrajBody(_Base):
    name: str
    parent: Optional[str] = Field(default=None, description="Parent body name; null for children of the world.")
    geoms: list[Geom] = Field(default_factory=list)


class ContactEvent(_Base):
    t: float = Field(description="Seconds from start.")
    kind: Literal["contact", "impact", "thrust", "landing", "failure", "custom"] = "contact"
    body: str = Field(description="Primary body name.")
    other: Optional[str] = Field(default=None, description="Other body name, or null for world/ground.")
    pos: Optional[Vec3] = None
    force: Optional[Vec3] = Field(default=None, description="World-frame force vector [N].")
    magnitude: Optional[float] = Field(default=None, description="Scalar force/impulse magnitude; unit in 'note' if not N.")
    note: str = ""


class TimeSeries(_Base):
    name: str = Field(description="e.g. 'thrust_N', 'pitch_deg', 'joint_torque_knee'.")
    unit: str = ""
    values: list[float] = Field(description="One value per frame.")


class TrajectoryMeta(_Base):
    seed: int
    mujoco_version: str
    template_id: Optional[TemplateId] = None
    params: dict[str, float] = Field(default_factory=dict, description="Search parameters that produced this rollout.")
    note: str = ""


class Trajectory(_Base):
    schema_version: str = SCHEMA_VERSION
    model_id: str = Field(description="Human label of the model, e.g. 'rocket_car_v1'.")
    model_hash: str = Field(description="Hash (e.g. sha256 hex) of the compiled MJCF XML used.")
    dt: float = Field(gt=0, description="Seconds between stored frames (may be a multiple of the physics timestep).")
    bodies: list[TrajBody]
    pos: list[list[Vec3]] = Field(description="[frame][body][x,y,z] world position, metres.")
    quat: list[list[Quat]] = Field(description="[frame][body][w,x,y,z] world orientation.")
    events: list[ContactEvent] = Field(default_factory=list)
    series: list[TimeSeries] = Field(default_factory=list)
    meta: TrajectoryMeta

    @property
    def n_frames(self) -> int:
        return len(self.pos)

    @model_validator(mode="after")
    def _shapes(self):
        nb, nf = len(self.bodies), len(self.pos)
        names = [b.name for b in self.bodies]
        if len(set(names)) != nb:
            raise ValueError("duplicate body names")
        for b in self.bodies:
            if b.parent is not None and b.parent not in names:
                raise ValueError(f"body {b.name!r}: unknown parent {b.parent!r}")
        if len(self.quat) != nf:
            raise ValueError("pos and quat must have the same number of frames")
        for i, (p, q) in enumerate(zip(self.pos, self.quat)):
            if len(p) != nb or len(q) != nb:
                raise ValueError(f"frame {i}: expected {nb} bodies in pos and quat")
        for s in self.series:
            if len(s.values) != nf:
                raise ValueError(f"series {s.name!r}: expected {nf} values, got {len(s.values)}")
        for e in self.events:
            if e.body not in names:
                raise ValueError(f"event references unknown body {e.body!r}")
        return self


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #

class VerdictStatus(str, Enum):
    FEASIBLE_FOUND = "FEASIBLE_FOUND"                          # strong: a witness exists within model assumptions
    INFEASIBLE_NECESSARY_CONDITION = "INFEASIBLE_NECESSARY_CONDITION"  # strong: provably impossible under assumptions
    NOT_FOUND_IN_BUDGET = "NOT_FOUND_IN_BUDGET"                # WEAK: absence of evidence only
    MODEL_INVALID = "MODEL_INVALID"                            # simulation/model itself failed sanity checks


class Feasibility(_Base):
    p_success: float = Field(ge=0, le=1)
    ci_low: float = Field(ge=0, le=1)
    ci_high: float = Field(ge=0, le=1)
    n_samples: int = Field(ge=0)
    ci_method: str = Field(default="wilson_95", description="How the CI was computed.")

    @model_validator(mode="after")
    def _ci(self):
        if not self.ci_low <= self.p_success <= self.ci_high:
            raise ValueError("require ci_low <= p_success <= ci_high")
        return self


class NecessaryCheck(_Base):
    """A cheap analytic/static check; failing it proves infeasibility under the assumptions."""

    name: str = Field(description="e.g. 'energy_budget', 'static_torque_saturation', 'impulse'.")
    passed: bool
    measured: float
    limit: float
    unit: str = ""
    note: str = ""


class Sensitivity(_Base):
    assumption_key: str
    effect: float = Field(description="Signed change in p_success (or in the margin) per +1 std / full range of the assumption; see 'method'.")
    rank: int = Field(ge=1)
    method: str = Field(default="one_at_a_time", description="e.g. 'one_at_a_time', 'sobol_total', 'spearman'.")


class BindingConstraint(_Base):
    name: str
    margin: float = Field(description="Signed slack in the constraint's units; <0 means violated.")
    unit: str = ""
    sensitivities: list[Sensitivity] = Field(default_factory=list, description="Assumptions ranked by influence on this constraint.")


class ParamChange(_Base):
    param: str = Field(description="A param_bounds name or assumption key.")
    from_value: float
    to_value: float
    unit: str = ""


class SuggestedFix(_Base):
    """Produced by the optimizer, never by an LLM."""

    changes: list[ParamChange]
    rationale: str = Field(description="Generated from optimizer output (what changed, by how much, what it bought).")
    verified: bool = Field(description="True iff the changed configuration was re-simulated and met the success criteria.")
    verified_p_success: Optional[float] = Field(default=None, ge=0, le=1)


class BomItem(_Base):
    name: str
    role: str = ""
    quantity: int = Field(default=1, ge=1)
    mass_kg: Optional[float] = Field(default=None, ge=0)
    unit_cost_usd: Optional[float] = Field(default=None, ge=0)
    source: str = ""


class SimCost(_Base):
    n_evals: int = Field(ge=0)
    wall_seconds: float = Field(ge=0)


class PhysicalEquivalentEstimate(_Base):
    is_estimate: Literal[True] = True
    low_usd: float = Field(ge=0)
    high_usd: float = Field(ge=0)
    basis: str
    sources: list[str] = Field(default_factory=list)


class CostEstimate(_Base):
    sim_cost: SimCost
    physical_equivalent_estimate: Optional[PhysicalEquivalentEstimate] = None


class ReviewItem(_Base):
    assumption_key: Optional[str] = None
    reason: str
    severity: Literal["info", "warn", "block"] = "warn"


class HumanReview(_Base):
    required: bool
    items: list[ReviewItem] = Field(default_factory=list)


class Reproducibility(_Base):
    seed: int
    versions: dict[str, str] = Field(description="e.g. {'mujoco': '3.2.0', 'cma': '3.3.0', 'physlab_core': '0.1.0'}.")
    search_budget: dict[str, float] = Field(description="e.g. {'cma_evals': 2000, 'mc_samples': 500}.")
    spec_hash: Optional[str] = Field(default=None, description="Hash of the SpecSheet used.")


class Verdict(_Base):
    schema_version: str = SCHEMA_VERSION
    status: VerdictStatus
    summary: str = Field(description="One or two plain-language sentences. For NOT_FOUND_IN_BUDGET must be worded as weak evidence, not impossibility.")
    feasibility: Feasibility
    necessary_checks: list[NecessaryCheck] = Field(default_factory=list)
    binding_constraint: Optional[BindingConstraint] = None
    best_params: dict[str, float] = Field(default_factory=dict)
    suggested_fix: Optional[SuggestedFix] = None
    bom: list[BomItem] = Field(default_factory=list)
    cost_estimate: Optional[CostEstimate] = None
    model_labels: list[str] = Field(
        default_factory=list,
        description="Uncertainty labels, e.g. 'simplified model, needs precise validation' (mandatory for CFD/thermal/FEA-like submodels).",
    )
    human_review: HumanReview
    reproducibility: Reproducibility
    trajectory_ref: Optional[str] = Field(default=None, description="Path/URL of the best-run Trajectory JSON.")

    @model_validator(mode="after")
    def _asymmetry(self):
        failed = [c for c in self.necessary_checks if not c.passed]
        if self.status == VerdictStatus.INFEASIBLE_NECESSARY_CONDITION and not failed:
            raise ValueError("INFEASIBLE_NECESSARY_CONDITION requires at least one failed necessary_check")
        if self.status == VerdictStatus.FEASIBLE_FOUND and failed:
            raise ValueError("FEASIBLE_FOUND is inconsistent with a failed necessary_check")
        if self.status == VerdictStatus.FEASIBLE_FOUND and not self.best_params:
            raise ValueError("FEASIBLE_FOUND requires best_params (the witness)")
        if self.suggested_fix is not None and self.suggested_fix.verified and self.suggested_fix.verified_p_success is None:
            raise ValueError("verified suggested_fix must carry verified_p_success")
        return self


MODELS: dict[str, type[BaseModel]] = {
    "spec_sheet": SpecSheet,
    "trajectory": Trajectory,
    "verdict": Verdict,
}

__all__ = [
    "SCHEMA_VERSION", "MODELS", "SpecSheet", "Trajectory", "Verdict",
    "Assumption", "Part", "ParamBound", "SuccessCriterion", "Comparator",
    "TemplateId", "Tier", "Confidence", "Fixed", "Uniform", "Normal",
    "Geom", "GeomType", "TrajBody", "ContactEvent", "TimeSeries", "TrajectoryMeta",
    "VerdictStatus", "Feasibility", "NecessaryCheck", "Sensitivity", "BindingConstraint",
    "ParamChange", "SuggestedFix", "BomItem", "SimCost", "PhysicalEquivalentEstimate",
    "CostEstimate", "ReviewItem", "HumanReview", "Reproducibility",
]
