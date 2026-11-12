"""`Project` (C-02a): the document that commands edit. A `DesignSpec` (what the user built), the `World` it sits in,
and the `AssumptionTable` of its verdict.

This is the unit a command is applied to and the unit a client holds a copy of (`client-adapter.md` D1). It has
no behaviour of its own beyond cross-reference checks and sampled compile inputs: the checks inside each part stay in
the part (`designspec.py`, `world.py`, `assumption.py`). `Project` checks that a terrain prop's `material` is carried
by the project and that every assumption binding names an existing target of the same unit. Together that makes a
dangling reference unconstructible: a `Project` that
validates has no instance without its part, no joint without its snap points, no actuator without its joint, no
schedule entry without its actuator, and no prop without its material.

`world` is required: a project sits on a planet from the start (a planet is chosen with `SelectPlanet`, never
absent). Not here: the file format and hashes (`projectfile.py`, `canonical.py`, C-03), a missing-definitions state
(C-06: `missing.py`; the definition references of `DesignSpec` are open, see there), `planet` existing in `data/bodies` (W-01 data, validator C-02c).
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, model_validator

from .assumption import AssumptionBinding, AssumptionTable, InstanceParameterBinding, MaterialPropertyBinding
from .conventions import Unit
from .designspec import DesignSpec
from .partdef import THRUSTER_CURVE, THRUSTER_RATED_THRUST, PartRole
from .refs import Ref, RefError, RefKind
from .world import World


def _binding_unit(design: DesignSpec, binding: AssumptionBinding) -> tuple[Unit, Ref]:
    """The target's unit and typed reference, or the missing target that makes the binding invalid."""
    if isinstance(binding, InstanceParameterBinding):
        instance = next((i for i in design.instances if i.id == binding.instance), None)
        if instance is None:
            raise RefError(f"unknown instance {binding.instance!r}", Ref(kind=RefKind.INSTANCE, id=binding.instance))
        part = next((p for p in design.parts if p.id == instance.part), None)
        if part is None:
            raise RefError(
                f"instance {instance.id!r}: unknown part {instance.part!r}; its parameters cannot be binding targets",
                Ref(kind=RefKind.INSTANCE, id=instance.id),
                Ref(kind=RefKind.PART, id=instance.part),
            )
        parameter = next((p for p in part.parameters if p.name == binding.parameter), None)
        if parameter is None:
            raise RefError(
                f"part {part.id!r} of instance {instance.id!r} has no parameter {binding.parameter!r}",
                Ref(kind=RefKind.PARAMETER, id=f"{instance.id}/{binding.parameter}"),
            )
        return parameter.unit, Ref(kind=RefKind.PARAMETER, id=f"{instance.id}/{binding.parameter}")
    if isinstance(binding, MaterialPropertyBinding):
        material = next((m for m in design.materials if m.id == binding.material), None)
        if material is None:
            raise RefError(f"unknown material {binding.material!r}", Ref(kind=RefKind.MATERIAL, id=binding.material))
        return getattr(material, binding.property).unit, Ref(kind=RefKind.MATERIAL, id=material.id)
    part = next((p for p in design.parts if p.id == binding.part), None)
    if part is None:
        raise RefError(f"unknown part {binding.part!r}", Ref(kind=RefKind.PART, id=binding.part))
    spec = next((s for s in part.specs if s.name == binding.spec), None)
    if spec is None:
        raise RefError(f"part {part.id!r} has no spec {binding.spec!r}", Ref(kind=RefKind.PART, id=part.id))
    return spec.unit, Ref(kind=RefKind.PART, id=part.id)


def _binding_identity(binding: AssumptionBinding) -> tuple[str, ...]:
    if isinstance(binding, InstanceParameterBinding):
        return (binding.kind, binding.instance, binding.parameter)
    if isinstance(binding, MaterialPropertyBinding):
        return (binding.kind, binding.material, binding.property)
    return (binding.kind, binding.part, binding.spec)


class Project(BaseModel):
    # extra="forbid" is a decision of the project file format (`projectfile.py`, C-03): a field a build does not know
    # is refused, never ignored, and adding a field bumps the file version. C-06 (#455) relaxes the definition
    # references of `DesignSpec` (an instance may name a part or material the project does not carry), not this.
    model_config = ConfigDict(extra="forbid", frozen=True)

    design: DesignSpec = DesignSpec()
    world: World
    assumptions: AssumptionTable = AssumptionTable()

    @model_validator(mode="after")
    def _prop_materials_exist(self) -> "Project":
        materials = {m.id for m in self.design.materials}
        for prop in self.world.terrain_props:
            if prop.material is not None and prop.material not in materials:
                raise RefError(
                    f"world.terrain_props ({prop.id!r}): unknown material {prop.material!r}",
                    Ref(kind=RefKind.MATERIAL, id=prop.material),
                    Ref(kind=RefKind.PROP, id=prop.id),
                )
        return self

    @model_validator(mode="after")
    def _assumption_bindings_exist_with_the_right_unit(self) -> "Project":
        seen: dict[tuple[str, ...], str] = {}
        for assumption in self.assumptions.assumptions:
            binding = assumption.binding
            if binding is None:
                continue
            try:
                unit, target = _binding_unit(self.design, binding)
            except RefError as error:
                raise RefError(
                    f"assumption {assumption.key!r}: {error}",
                    Ref(kind=RefKind.ASSUMPTION, id=assumption.key),
                    *error.refs,
                ) from None
            if assumption.value.unit is not unit:
                raise RefError(
                    f"assumption {assumption.key!r} is in {assumption.value.unit.value!r}, "
                    f"but its binding target is in {unit.value!r}",
                    Ref(kind=RefKind.ASSUMPTION, id=assumption.key),
                    target,
                )
            identity = _binding_identity(binding)
            if identity in seen:
                raise RefError(
                    f"assumptions {seen[identity]!r} and {assumption.key!r} bind the same design value",
                    Ref(kind=RefKind.ASSUMPTION, id=seen[identity]),
                    Ref(kind=RefKind.ASSUMPTION, id=assumption.key),
                    target,
                )
            seen[identity] = assumption.key
        return self


def apply_assumption_values(project: Project, values: Mapping[str, float]) -> Project:
    """Return the compile input with every bound row set to `values[key]`, leaving `project` unchanged.

    The sampled number carries the row nominal's badge and source, not the target's: sampling must not turn a user
    declaration into a citation (or a citation into a declaration). Unbound rows are ignored. A missing value for a
    bound row is an error, never a silent nominal fallback. The returned model is fully validated, including parameter
    ranges, so an inapplicable sample is refused rather than run as if it had been applied.
    """
    bound = tuple(a for a in project.assumptions.assumptions if a.binding is not None)
    if not bound:
        return project
    missing = [a.key for a in bound if a.key not in values]
    if missing:
        raise ValueError(f"missing values for bound assumptions: {missing}")

    data = project.model_dump(mode="python")
    instances = {instance.id: n for n, instance in enumerate(project.design.instances)}
    materials = {material.id: n for n, material in enumerate(project.design.materials)}
    parts = {part.id: n for n, part in enumerate(project.design.parts)}
    for assumption in bound:
        binding = assumption.binding
        assert binding is not None
        quantity = assumption.value.model_dump(mode="python")
        quantity["value"] = values[assumption.key]
        if isinstance(binding, InstanceParameterBinding):
            parameters = data["design"]["instances"][instances[binding.instance]]["parameters"]
            quantity["name"] = binding.parameter
            for n, parameter in enumerate(parameters):
                if parameter["name"] == binding.parameter:
                    parameters[n] = quantity
                    break
            else:
                parameters.append(quantity)
        elif isinstance(binding, MaterialPropertyBinding):
            data["design"]["materials"][materials[binding.material]][binding.property] = quantity
        else:
            part = project.design.parts[parts[binding.part]]
            part_data = data["design"]["parts"][parts[binding.part]]
            spec_n = next(n for n, spec in enumerate(part.specs) if spec.name == binding.spec)
            if part.role is PartRole.THRUSTER and binding.spec == THRUSTER_RATED_THRUST:
                # rated_thrust and the end of the thrust curve are one model invariant. Scale the whole curve so the
                # opening shape is preserved and the force seen by the engine changes with the sampled specification.
                ratio = quantity["value"] / part.specs[spec_n].value
                named = next(c for c in part_data["curves"] if c["name"] == THRUSTER_CURVE)
                curve = named["curve"]
                for point in curve["points"]:
                    point["y"] *= ratio
                original_ref = curve["source"]["ref"]
                curve["badge"] = "estimate"
                curve["source"] = {
                    "ref": f"Monte Carlo binding {assumption.key!r}: thrust curve from {original_ref!r}, "
                    "scaled to the sampled rated_thrust",
                    "locator": "kinetra_core.project.apply_assumption_values",
                }
            quantity["name"] = binding.spec
            part_data["specs"][spec_n] = quantity
    return Project.model_validate(data)
