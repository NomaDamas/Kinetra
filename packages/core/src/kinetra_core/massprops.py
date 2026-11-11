"""Mass, centre of mass and inertia of a part, computed from its shape recipe (B-01a), with the inputs that produced them.

This is the result contract; the computation is `kinetra_engine.parts.mass_properties`. The core computes derived
values and sends them with their badges (`client-adapter.md` D4); a client never recomputes them.

**Badge of a derived value.** Every number here is badge `sim` ("our computation produced it", the one badge for values
that are not transcribed or declared) and its source says which computation. That badge alone would hide how good the
inputs were, so the value never travels without its `Derivation`: the shape recipe with its badge and source, the density
with its badge and source, and each parameter value used with its own. `Derivation.input_badges` lists the distinct
badges of those inputs. A mass computed from a declared density is exactly as good as that declaration. How a consumer
combines input badges into one (X-07's "weakest input" rule) is its decision; this module does not rank them.

Conventions (`conventions.py`): SI, the part's local frame, right-handed, +Z up. The inertia is the tensor about the
centre of mass, written in the part's axes, with the usual signs: `ixy = -integral(x*y dm)` (the matrix entry, not the
product of inertia).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .conventions import ID_PATTERN, Unit
from .geometry import Name, Quaternion
from .material import Density
from .provenance import Badge, Number, Provenance, Quantity


class SimProvenance(Provenance):
    """Provenance fixed to badge `sim`: a derived value cannot claim to be cited or declared."""

    badge: Literal[Badge.SIM]


class DerivedScalar(SimProvenance):
    value: Number
    unit: Unit


class DerivedVector(SimProvenance):
    """A point in the part's local frame [m]."""

    x: Number
    y: Number
    z: Number
    unit: Literal[Unit.M]


class DerivedInertia(SimProvenance):
    """Inertia tensor about the centre of mass, in the part's axes [kg*m^2]."""

    ixx: Number
    iyy: Number
    izz: Number
    ixy: Number
    ixz: Number
    iyz: Number
    unit: Literal[Unit.KG_M2]


class ParameterUse(BaseModel):
    """The value one length parameter had in this computation, with the badge and source it came with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name
    value: Quantity


class Dimension(BaseModel):
    """One resolved length of a primitive, in metres, under the field name `shape.py` gives it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Name
    value: Number


# The dimension names of each primitive, in the order `shape.py` lists them.
PRIMITIVE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "box": ("size_x", "size_y", "size_z"),
    "cylinder": ("radius", "length"),
    "sphere": ("radius",),
}


class ComponentContribution(BaseModel):
    """What one shape component added or removed, with the values it was evaluated at.

    `dimensions` are the primitive's resolved lengths in metres under the field names of `shape.py` (`size_x`, `radius`,
    `length`, ...), `center` its resolved position in the part frame and `orientation` its rotation about that centre.
    `volume` and `mass` are positive; `operation` says which way they count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Literal["box", "cylinder", "sphere"]
    operation: Literal["add", "subtract"]
    dimensions: tuple[Dimension, ...]
    volume: Number
    mass: Number
    center: tuple[Number, Number, Number]
    orientation: Quaternion

    @model_validator(mode="after")
    def _dimensions_fit_the_primitive(self) -> "ComponentContribution":
        got = tuple(d.name for d in self.dimensions)
        want = PRIMITIVE_DIMENSIONS[self.primitive]
        if got != want:
            raise ValueError(f"a {self.primitive} has dimensions {list(want)}, got {list(got)}")
        return self

    def dimension(self, name: str) -> float:
        return next(d.value for d in self.dimensions if d.name == name)


class Derivation(BaseModel):
    """Everything the numbers were computed from, so a reviewer can redo them by hand."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Literal["analytic-primitives"] = "analytic-primitives"
    shape: Provenance
    material_id: str = Field(pattern=ID_PATTERN)
    density: Density
    parameters: tuple[ParameterUse, ...]
    components: tuple[ComponentContribution, ...]
    input_badges: tuple[Badge, ...]
    assumptions: tuple[str, ...]

    @model_validator(mode="after")
    def _input_badges_are_the_inputs_badges(self) -> "Derivation":
        """`input_badges` is what a consumer ranks (X-07), so it must be exactly the distinct badges of the shape, the
        density and the parameter values listed here, in `Badge` order. It cannot be edited on its own."""
        order = list(Badge)
        want = tuple(sorted({self.shape.badge, self.density.badge, *(u.value.badge for u in self.parameters)}, key=order.index))
        if self.input_badges != want:
            raise ValueError(f"input_badges must be {[b.value for b in want]} (the badges of the inputs listed), got {[b.value for b in self.input_badges]}")
        return self


class MassProperties(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    part_id: str = Field(pattern=ID_PATTERN)
    volume: DerivedScalar
    mass: DerivedScalar
    center_of_mass: DerivedVector
    inertia: DerivedInertia
    derivation: Derivation
