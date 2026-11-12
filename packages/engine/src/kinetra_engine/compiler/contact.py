"""Contact of a compiled model (X-01e): the friction of every geom and of the ground, how two touching faces combine, and the
contact parameters. `docs/architecture/contact.md` is the decision record.

    contact_friction(tree, ground_friction=None) -> ContactFriction
    contact_labels(friction) -> tuple[ModelLabel, ...]

**Friction of a geom.** One Coulomb coefficient per instance, given to every geom of its collision proxy, from the first that
applies:

1. the part's spec `tread_friction_kinetic` (B-03a wheel, `parts-wheel.md`): the tread is what touches the ground;
2. the instance's material, `Material.friction` (B-07, `materials.md`);
3. neither (a part whose mass is declared and that has no material): MuJoCo's own default 1, badge `default`, and a label says so.

The kinetic coefficient is used everywhere: `Material.friction` is kinetic, and MuJoCo has one coefficient per contact, so the static
one of a tread (1.0) is not used (a label says so).

**Ground.** The ground's coefficient is the planet's `ground_friction` (`data/bodies`, W-01, carried on `tree.planet`): its nominal
by default, or a value a Monte Carlo sample gives (W-03c), which must lie inside the distribution's support.

**Combination: the smaller of the two.** MuJoCo takes the larger (`max`) of two geoms of equal `priority` and the parameters of the
higher-priority geom otherwise. The compiler ranks every distinct coefficient (ground included) and gives the smaller coefficient the
higher priority, so every contact pair uses `min(mu_1, mu_2)`. Why `min`, not `max`: the ground's tan(phi) is an upper bound for a
part sliding on soil (`bodies.md`: the interface angle delta is below phi), which `max` would break by giving a 0.21 POM part on soil
the soil's 0.56; and a smaller coefficient is the conservative side for a vehicle's grip, the verdict this feeds.

**Contact parameters.** `condim` 3 (sliding friction only: no torsional or rolling friction), elliptic friction cone, `solref` and
`solimp` MuJoCo's defaults. All are MuJoCo defaults except the cone; `CONTACT_PARAMETERS` carries each with its badge and source.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Literal

from kinetra_core import Assumption, Badge, NormalDistribution, Quantity, UniformDistribution

from .bodytree import BodyTree
from .labels import ModelLabel

GROUND_GEOM = "__kinetra_ground"
"""The ground plane's geom name. A project id cannot start with `_`, so it never collides with `<instance>/<proxy geom>`."""

TREAD_FRICTION_SPEC = "tread_friction_kinetic"

_MUJOCO_XML = "https://mujoco.readthedocs.io/en/stable/XMLreference.html"
_MUJOCO_CONTACT = "https://mujoco.readthedocs.io/en/stable/computation/index.html#contact"
_SEEN = "MuJoCo 4.0.0 (docs/decisions/engine.md), accessed 2026-11-12"

DEFAULT_FRICTION = Quantity.model_validate(
    {
        "value": 1.0,
        "unit": "1",
        "badge": "default",
        "source": {
            "ref": f"MuJoCo's default geom friction '1 0.005 0.0001', its sliding coefficient 1; used for a part with neither a material nor a tread spec. {_SEEN}",
            "locator": "XML reference, geom/friction",
            "url": _MUJOCO_XML + "#body-geom",
        },
    }
)


@dataclass(frozen=True)
class ContactParameter:
    """One contact parameter as written in the MJCF: `value` is the attribute text, `badge` `default` (MuJoCo's own value) or
    `estimate` (Kinetra's choice, reason in `source`)."""

    name: str
    value: str
    badge: Badge
    source: str
    url: str


CONTACT_PARAMETERS: tuple[ContactParameter, ...] = (
    ContactParameter(
        "condim",
        "3",
        Badge.DEFAULT,
        f"MuJoCo's default: normal force and sliding friction in the tangent plane; no torsional (spinning) or rolling friction, so no rolling resistance. {_SEEN}",
        _MUJOCO_XML + "#body-geom",
    ),
    ContactParameter(
        "cone",
        "elliptic",
        Badge.ESTIMATE,
        "Kinetra's choice over MuJoCo's default 'pyramidal': the elliptic cone is the Coulomb cone |f_t| <= mu f_n in every tangent "
        f"direction; the pyramid's faces lie inside it off its edges, so the slip angle would depend on the contact frame. {_SEEN}",
        _MUJOCO_CONTACT,
    ),
    ContactParameter(
        "solref",
        "0.02 1",
        Badge.DEFAULT,
        f"MuJoCo's default: time constant 0.02 s, damping ratio 1 of the soft contact (penetration recovers like a critically damped spring). {_SEEN}",
        _MUJOCO_XML + "#body-geom",
    ),
    ContactParameter(
        "solimp",
        "0.9 0.95 0.001 0.5 2",
        Badge.DEFAULT,
        f"MuJoCo's default: constraint impedance 0.9 to 0.95 over 1 mm of penetration. {_SEEN}",
        _MUJOCO_XML + "#body-geom",
    ),
)


@dataclass(frozen=True)
class GeomFriction:
    """The friction of one geom: `geom` `<instance>/<proxy geom>`, `mu` the coefficient, `origin` where it comes from (`tread`: the
    part's spec, `material`: `Material.friction`, `default`: none of them), `quantity` that number with its badge and source."""

    geom: str
    instance: str
    part: str
    origin: Literal["tread", "material", "default"]
    quantity: Quantity

    @property
    def mu(self) -> float:
        return self.quantity.value


@dataclass(frozen=True)
class ContactFriction:
    """Every geom's friction (tree order) and the ground's. `ground_assumption` is the planet's `ground_friction` (its nominal,
    distribution, badge and source); `ground` the coefficient this model uses."""

    geoms: tuple[GeomFriction, ...]
    ground: float
    ground_assumption: Assumption

    @cached_property
    def levels(self) -> tuple[float, ...]:
        """The distinct coefficients of the model (ground included), largest first."""
        return tuple(sorted({g.mu for g in self.geoms} | {self.ground}, reverse=True))

    def priority(self, mu: float) -> int:
        """MuJoCo `priority` of a geom with coefficient `mu`: its index in `levels` (the number of distinct coefficients above it),
        so the smaller of two coefficients always has the higher priority and its friction is the contact's (`min`)."""
        return self.levels.index(mu)

    @staticmethod
    def combined(a: float, b: float) -> float:
        """The coefficient of a contact between faces of coefficients `a` and `b`."""
        return min(a, b)


def _in_support(value: float, a: Assumption) -> bool:
    d = a.distribution
    if isinstance(d, UniformDistribution):
        return d.low <= value <= d.high
    if isinstance(d, NormalDistribution):
        return (d.clip_low is None or value >= d.clip_low) and (d.clip_high is None or value <= d.clip_high)
    return value == a.value.value


def contact_friction(tree: BodyTree, ground_friction: float | None = None) -> ContactFriction:
    """The friction of every geom of `tree` and of the ground. `ground_friction` is the ground's coefficient (a Monte Carlo sample,
    W-03c); `None` is the planet's nominal. Raises `ValueError` for a value outside the planet's distribution: a sample comes from
    the planet's data, never from the caller's choice (rule C4)."""
    assumption = tree.planet.ground_friction
    ground = assumption.value.value if ground_friction is None else float(ground_friction)
    if not _in_support(ground, assumption):
        raise ValueError(
            f"ground friction {ground!r} is outside the {tree.planet.planet!r} ground friction distribution "
            f"{assumption.distribution.model_dump(include={'kind', 'low', 'high', 'mean', 'clip_low', 'clip_high'})}: "
            "a sample must come from the planet's data (data/bodies)"
        )
    parts = {p.id: p for p in tree.design.parts}
    materials = {m.id: m for m in tree.design.materials}
    per_instance: dict[str, tuple[Literal["tread", "material", "default"], Quantity]] = {}
    for ci in tree.instances:
        tread = next((s for s in parts[ci.part].specs if s.name == TREAD_FRICTION_SPEC), None)
        if tread is not None:
            per_instance[ci.instance] = ("tread", tread)
        elif ci.material is not None:
            per_instance[ci.instance] = ("material", materials[ci.material].friction)
        else:
            per_instance[ci.instance] = ("default", DEFAULT_FRICTION)
    part_of = {ci.instance: ci.part for ci in tree.instances}
    geoms = tuple(
        GeomFriction(g.name, g.instance, part_of[g.instance], *per_instance[g.instance]) for body in tree.bodies for g in body.geoms
    )
    return ContactFriction(geoms, ground, assumption)


FRICTION_RULE_LABEL = "근사: 접촉 마찰은 두 면 중 작은 계수, 정지·운동 구분 없이 운동 마찰 계수 하나"
SLOW_SLIP_LABEL = "근사: 소프트 접촉이라 정지 마찰 범위 안에서도 느리게 미끄러짐"
NO_ROLLING_LABEL = "근사: 구름·비틀림 마찰 없음(미끄럼 마찰만)"


def contact_labels(friction: ContactFriction) -> tuple[ModelLabel, ...]:
    """The contact approximation labels of a model (`docs/architecture/contact.md`): the three model-wide ones (rule, slow slip, no
    rolling resistance), then per instance in canonical order a `tread` label (the tread coefficient on every geom of the part)
    or a `default` label (no material and no tread spec: MuJoCo's 1)."""
    out = [
        ModelLabel(FRICTION_RULE_LABEL, "contact", None, None, None, None),
        ModelLabel(SLOW_SLIP_LABEL, "contact", None, None, None, None),
        ModelLabel(NO_ROLLING_LABEL, "contact", None, None, None, None),
    ]
    seen: dict[str, GeomFriction] = {}
    for g in friction.geoms:
        seen.setdefault(g.instance, g)
    for instance in sorted(seen):
        g = seen[instance]
        if g.origin == "tread":
            text = f"근사: {instance}의 모든 접촉 면에 트레드 마찰 {g.mu:g}"
        elif g.origin == "default":
            text = f"기본값: {instance}의 마찰 {g.mu:g}(재료도 트레드 사양도 없음, MuJoCo 기본값)"
        else:
            continue
        out.append(ModelLabel(text, "contact", instance, g.part, None, None))
    return tuple(out)
