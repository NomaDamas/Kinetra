"""Shape recipe of a part (B-01a): analytic primitives added to or subtracted from each other.

The recipe is engine-independent Project data. It is what mass, centre of mass and inertia are computed from
(`kinetra_engine.parts`, result model in `massprops.py`). It is not the visual mesh (B-01c) and not the collision
proxy (B-01b).

- Frame: the part's local frame (`conventions.py`). A component's `position` is the centre of its primitive, in metres,
  and may follow length parameters like a snap point does. `orientation` rotates the primitive about that centre.
- Primitives: `box` (full extents along local x, y, z), `cylinder` (axis along local z), `sphere`. Every dimension is
  an `AxisExpr` (a length in metres: offset plus factors times length parameters), so a part resizes with its
  parameters.
- `operation`: `add` is material, `subtract` is a void (hole, pocket). The result is the sum of the added volumes minus
  the subtracted volumes.
- **Components are a disjoint sum.** Added components must not overlap each other, subtracted components must not
  overlap each other, and each subtracted component must lie entirely inside one added component. The model does not
  intersect solids (that needs a CAD kernel). The computation (`kinetra_engine.parts`) checks the three rules on the
  primitives themselves (a separating plane for overlap, a containment test for voids) and raises `ShapeError` when one is
  broken, so a double count is never returned silently. Contact along a face, edge or point is not overlap. The tests can
  reject a valid recipe only when two bodies nearly touch along a feature the separating directions do not name.
- Every dimension must stay above zero over the whole parameter range; `PartDef` checks that.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .geometry import AxisExpr, Name, Position, Quaternion
from .provenance import Provenance


def _identity() -> Quaternion:
    return Quaternion(x=0.0, y=0.0, z=0.0, w=1.0)


class Box(BaseModel):
    """Rectangular block. `size_*` are full extents [m] along the component's local x, y, z."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["box"] = "box"
    size_x: AxisExpr
    size_y: AxisExpr
    size_z: AxisExpr

    def dimensions(self) -> Iterator[tuple[str, AxisExpr]]:
        yield "size_x", self.size_x
        yield "size_y", self.size_y
        yield "size_z", self.size_z


class Cylinder(BaseModel):
    """Solid circular cylinder. `radius` and `length` [m]; the axis is the component's local z."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["cylinder"] = "cylinder"
    radius: AxisExpr
    length: AxisExpr

    def dimensions(self) -> Iterator[tuple[str, AxisExpr]]:
        yield "radius", self.radius
        yield "length", self.length


class Sphere(BaseModel):
    """Solid sphere. `radius` [m]."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["sphere"] = "sphere"
    radius: AxisExpr

    def dimensions(self) -> Iterator[tuple[str, AxisExpr]]:
        yield "radius", self.radius


Primitive = Annotated[Box | Cylinder | Sphere, Field(discriminator="kind")]


class ShapeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Name
    primitive: Primitive
    operation: Literal["add", "subtract"] = "add"
    position: Position
    orientation: Quaternion = Field(default_factory=_identity)

    def axis_exprs(self) -> Iterator[tuple[str, AxisExpr]]:
        """Every length expression of the component with its field path, for parameter checks."""
        for name, expr in self.primitive.dimensions():
            yield f"primitive.{name}", expr
        for axis in ("x", "y", "z"):
            yield f"position.{axis}", getattr(self.position, axis)


class Shape(Provenance):
    """The recipe: one or more components. At least one is `add`; ids are unique.

    The offsets and factors inside the expressions are plain numbers; like a snap point's pose, the recipe carries
    one badge and source for all of them (who drew these dimensions: `declared`, or `cite` with a drawing, ...).
    """

    components: tuple[ShapeComponent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> "Shape":
        ids = [c.id for c in self.components]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate component id")
        if not any(c.operation == "add" for c in self.components):
            raise ValueError("a shape needs at least one added component")
        return self
