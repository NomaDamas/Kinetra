"""The validator (C-02c): the one gate every edit goes through, whoever sends it (`client-adapter.md` C1, C4).

Three entry points:

- `parse_command(data)`: JSON from any client to one exact `Command`, or `CommandRejected`. A payload that is not a
  command is `invalid_command` (schema violation). A payload that tries to carry a planet constant, a verdict or a
  change of the material catalog is `forbidden` and says why.
- `validate_command(project, command)`: `apply_command` plus the policy and placement checks below. This is what
  C-02b (history), C-05a (wire) and the agent tools (G-02a) call instead of `apply_command`.
- `check_placement(project)`: the placement findings of a project, as `Reason`s.

**Who sent it does not matter.** None of these functions takes an origin: a mouse, an agent, a voice sentence, an XR
hand and the MCP server get the same answer (the issuer is the history's, C-02b). The ban on planet constants, the
material catalog and verdicts is structural first: no command type or field carries them (`extra="forbid"`, a closed
`Command` union), so such a payload is refused as a schema violation anyway. `forbidden` only tells the sender why.
The word lists below (`FORBIDDEN_WORDS`) make that message precise; they are a courtesy, not the guarantee.

What is refused beyond `apply_command`:

| code | when |
|---|---|
| `forbidden` | the payload names a planet constant or a verdict; an assumption keyed like a planet constant; a material definition that uses the id of a catalog material (`load_material_catalog`) but is not that material exactly; a material of another id whose `cite` property uses a catalog source with other numbers |
| `unknown_id` (ref kind `planet`) | `world.planet` is not a planet of `data/bodies` (W-01). Material references of terrain props are checked by `Project` itself |
| `invalid_snap` | a joint whose two snap points do not accept each other's `kind`, or do not coincide in the world |
| `overlap` | two instances whose collision shapes interpenetrate, or one that goes below the ground or into a terrain prop |
| `floating` | a group of instances (joined or touching) that touches neither the ground nor a terrain prop |

Placement rules (frame and units are `conventions.py`; ground is the plane z = 0, `world.py`):

- **Geometry** of an instance is the added components of its part's shape recipe (`shape.py`) at the instance's
  parameter values and world pose: the same primitives the collision proxy copies (B-01b), voids filled. A part
  without a shape recipe has no geometry: it is skipped by `overlap` and `floating` (nothing is known to test), and a
  group joined to such an instance is not called floating. That is a limit, not a pass: it is shown by the tests.
- **Snap**: each joint's `a` and `b` snap points must accept each other (`b.kind in a.accepts` and `a.kind in
  b.accepts`) and must be at the same world point (the joint does not move anything, `project-model.md`). The
  orientation of the two snap frames is not compared: which frames may mate is B-04a/B-04b's rule.
- **Overlap**: separation is `convex.separated` (the test the mass computation uses for its disjoint sum). Touching
  is fine; penetration deeper than the tolerance is not. That holds against the ground plane (z = 0), against other
  instances and against terrain props: a part inside a step or under a ramp's slope overlaps it (`overlap`, refs the
  instance and the `prop`), it is not supported by it.
- **Floating**: instances are grouped by joints and by contact (gap within the tolerance). A group is supported when
  one of its geometries touches the ground (lowest point within the tolerance of z = 0) or a terrain prop. A ramp
  is a wedge (a triangular prism: `length` run, `width`, rise = `length * tan(incline)`) and a step a box, both exact
  to the `world.py` description, turned by `yaw`. A project has no launch height yet (the scenario is J-02's), so a whole assembly in the air is floating.
- **Tolerance** `PLACEMENT_TOLERANCE` is a numerical tolerance for stored doubles, not a physical claim: a client
  snaps before it sends, so a pose that meets within 1 micrometre is a pose that was meant to meet.
- **Only what the command introduces is refused.** A project that already has an overlap (opened from a file, or an
  older rule set) can still be edited elsewhere: findings of the result that the project did not already have are
  the command's. A `CommandBatch` is judged on its end state (the structure, `apply_command`, is judged at every
  step), so `[add_instance, add_joint]` or "move every part of an assembly" works though the middle state is loose.

Not here: the issuer and policy by origin (C-02b records it; nothing is allowed for one origin and refused for another),
snap orientation and joint axes (B-04a, B-04b), compile errors (X-01d), terrain prop edits (W-05).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from . import convex as cx
from .assumption import Assumption
from .bodies import check_world_references, load_bodies
from .commands import (
    AddAssumption,
    AddMaterialDef,
    ApplyResult,
    Command,
    CommandBatch,
    CommandRejected,
    Reason,
    ReasonCode,
    ReplaceMaterialDef,
    SetAssumption,
    apply_command,
    missing_reasons,
)
from .designspec import Instance
from .material import Material
from .material_catalog import load_material_catalog
from .missing import BlockedOperation, MissingDefinition, missing_definitions, missing_users
from .partdef import PartDef
from .project import Project
from .provenance import Badge
from .refs import Ref, RefError, RefKind
from .world import PLANET_CONSTANT_NAMES, RampProp

PLACEMENT_TOLERANCE = 1e-6
"""Metres. Numerical tolerance of the placement checks (see the module docstring); not a physical claim."""

VERDICT_FIELD_NAMES = frozenset({"verdict", "p_success", "ci", "confidence_interval"})
"""Names of what the core's verdict (L2 card) is made of (`studio-plan.md` 4.5: `FEASIBLE_FOUND`, p_success, CI). A
command that carries one is refused: a verdict flows from the core to the client, never back (`client-adapter.md` C4)."""

FORBIDDEN_WORDS = frozenset(
    {"gravity", "atmosphere", "insolation", "irradiance", "constant", "constants", "catalog", "verdict", "p_success"}
)
"""Words of a command `type` that name a planet constant, the material catalog or a verdict (`set_gravity`,
`set_planet_constants`, `edit_catalog`, `set_verdict`). Only for the message: an unknown `type` is refused anyway."""

_COMMAND = TypeAdapter(Command)
_FORBIDDEN_KEYS = PLANET_CONSTANT_NAMES | VERDICT_FIELD_NAMES


def _forbidden(message: str, *refs: Ref) -> CommandRejected:
    return CommandRejected((Reason(code=ReasonCode.FORBIDDEN, message=message, ids=refs),))


# --- wire: JSON to a Command --------------------------------------------------------------------------------


def _forbidden_names(data: Any, where: str = "") -> list[str]:
    """Where `data` (JSON) has a key that is a planet constant or a verdict field, or a command `type` that names one."""
    found: list[str] = []
    if isinstance(data, Mapping):
        for key, value in data.items():
            path = f"{where}.{key}" if where else str(key)
            if key in _FORBIDDEN_KEYS:
                found.append(path)
            if key == "type" and isinstance(value, str) and FORBIDDEN_WORDS.intersection(value.split("_")):
                found.append(f"{path} = {value!r}")
            found.extend(_forbidden_names(value, path))
    elif isinstance(data, (list, tuple)):
        for n, item in enumerate(data):
            found.extend(_forbidden_names(item, f"{where}[{n}]"))
    return found


def parse_command(data: Any) -> Command:
    """The `Command` that JSON `data` is, from whichever client or agent it came. Raises `CommandRejected`:
    `forbidden` for a payload that tries to carry a planet constant or a verdict (the planet is chosen by id with
    `select_planet`; the constants live in `data/bodies`; a verdict comes from the core), `invalid_command` for every
    other schema violation, one reason per violation."""
    names = _forbidden_names(data)
    if names:
        raise CommandRejected(
            tuple(
                Reason(
                    code=ReasonCode.FORBIDDEN,
                    message=(
                        f"{name}: a command cannot carry a planet constant or a verdict. Planets are chosen by id "
                        "(select_planet) and their constants are read from data/bodies; a verdict comes from the "
                        "core's simulation and Monte Carlo, never from a command"
                    ),
                )
                for name in names
            )
        )
    try:
        return _COMMAND.validate_python(data)
    except ValidationError as e:
        reasons = []
        for err in e.errors():
            cause = err.get("ctx", {}).get("error")
            where = ".".join(str(part) for part in err["loc"])
            text = err["msg"].removeprefix("Value error, ")
            reasons.append(
                Reason(
                    code=ReasonCode.INVALID_COMMAND,
                    message=f"not a valid command: {where + ': ' if where else ''}{text}",
                    ids=cause.refs if isinstance(cause, RefError) else (),
                )
            )
        raise CommandRejected(tuple(reasons)) from e


# --- policy of a typed command ------------------------------------------------------------------------------


def _edits(command: Command) -> Iterable:
    return command.commands if isinstance(command, CommandBatch) else (command,)


def _check_policy(command: Command) -> None:
    catalog = load_material_catalog()
    for edit in _edits(command):
        if isinstance(edit, (AddAssumption, SetAssumption)):
            key = edit.assumption.key
            if key in PLANET_CONSTANT_NAMES:
                raise _forbidden(
                    f"assumption {key!r} is a planet constant, not an assumption of the project: the engine reads it "
                    "from data/bodies",
                    Ref(kind=RefKind.ASSUMPTION, id=key),
                )
        elif isinstance(edit, (AddMaterialDef, ReplaceMaterialDef)):
            material = edit.material
            try:
                entry = catalog.get(material.id)
            except KeyError:
                _check_own_material(material, catalog)
                continue
            if material != entry.material:
                raise _forbidden(
                    f"material {material.id!r} is a material of the catalog and the catalog cannot be changed by a "
                    "command: use the catalog's definition as it is, or give your own material another id",
                    Ref(kind=RefKind.MATERIAL, id=material.id),
                )


_PROPERTIES = ("density", "yield_strength", "elastic_modulus", "friction")


def _check_own_material(material: Material, catalog) -> None:
    """A material that is not in the catalog is the user's own: its numbers are `declared` (or `cite` of the user's own
    source). What it cannot do is wear the catalog's citation with other numbers: a `cite` property whose source is one
    the catalog cites for a property must carry that property's value and unit, or the catalog is being edited under
    a new id (`forbidden`)."""
    cited = {}
    for entry in catalog.entries:
        for name in _PROPERTIES:
            q = getattr(entry.material, name)
            cited.setdefault(q.source.ref, []).append((entry.material.id, name, q.value, q.unit))
    for name in _PROPERTIES:
        q = getattr(material, name)
        if q.badge is not Badge.CITE:
            continue
        known = cited.get(q.source.ref)
        if known and not any((q.value, q.unit) == (v, u) for _, _, v, u in known):
            owner, field, value, unit = known[0]
            raise _forbidden(
                f"material {material.id!r}: {name} cites the source of {owner!r} {field} (a catalog value, "
                f"{value} {unit.value}) with {q.value} {q.unit.value}. The catalog cannot be changed under another "
                "id: use the catalog value, or declare your own value (badge declared, your own source)",
                Ref(kind=RefKind.MATERIAL, id=material.id),
            )


# --- placement ----------------------------------------------------------------------------------------------

_Vec = cx.Vec
_Finding = tuple[frozenset, Reason]


def _apply(r: cx.Mat, v: _Vec) -> _Vec:
    return (cx.dot(r[0], v), cx.dot(r[1], v), cx.dot(r[2], v))


def _parameter_values(part: PartDef, inst: Instance) -> dict[str, float]:
    return {p.name: p.default.value for p in part.parameters} | {p.name: p.value for p in inst.parameters}


def _instance_bodies(part: PartDef, inst: Instance) -> list[cx.Body]:
    """The collision geometry of `inst` in the world frame: the added components of the part's recipe. Empty when the
    part has no shape recipe."""
    if part.shape is None:
        return []
    values = _parameter_values(part, inst)
    r = cx.rotation(inst.pose.orientation)
    t = (inst.pose.position.x, inst.pose.position.y, inst.pose.position.z)
    out = []
    for comp in part.shape.components:
        if comp.operation != "add":
            continue
        dims = {name: expr.evaluate(values) for name, expr in comp.primitive.dimensions()}
        local = cx.make_body(comp.primitive, dims, comp.position.evaluate(values), cx.rotation(comp.orientation))
        out.append(cx.Body(local.kind, cx.add(_apply(r, local.center), t), tuple(_apply(r, a) for a in local.axes), local.half))  # type: ignore[arg-type]
    return out


def _prop_bodies(project: Project) -> list[tuple[str, cx.Body]]:
    """Terrain props as convex bodies (`world.py` frame): a ramp is a wedge rising along its local +x from z = 0, a
    step a box `height` tall. Exact for both, so a part lying on a ramp's slope touches it and one inside it overlaps."""
    out = []
    for prop in project.world.terrain_props:
        c, s = math.cos(prop.placement.yaw), math.sin(prop.placement.yaw)
        axes = ((c, s, 0.0), (-s, c, 0.0), (0.0, 0.0, 1.0))
        x, y = prop.placement.x, prop.placement.y
        if isinstance(prop, RampProp):
            rise = prop.length.value * math.tan(prop.incline.value)
            body = cx.Body("wedge", (x, y, 0.0), axes, (prop.length.value / 2, prop.width.value / 2, rise))
        else:
            h = prop.height.value
            body = cx.Body("box", (x, y, h / 2), axes, (prop.length.value / 2, prop.width.value / 2, h / 2))
        out.append((prop.id, body))
    return out


def _snap_world(part: PartDef, inst: Instance, snap_id: str) -> _Vec:
    snap = next(s for s in part.snap_points if s.id == snap_id)
    local = snap.position.evaluate(_parameter_values(part, inst))
    r = cx.rotation(inst.pose.orientation)
    return cx.add(_apply(r, local), (inst.pose.position.x, inst.pose.position.y, inst.pose.position.z))


def _bound(body: cx.Body) -> float:
    return body.farthest_from(body.center)


def _touch(a: cx.Body, b: cx.Body, tol: float) -> bool:
    """The gap between `a` and `b` is within `tol`, or they overlap. Errs towards True for oblique contacts."""
    return not cx.separated(a, b, -tol)


def _snap_findings(project: Project, tol: float) -> list[_Finding]:
    parts = {p.id: p for p in project.design.parts}
    insts = {i.id: i for i in project.design.instances}
    out: list[_Finding] = []
    for joint in project.design.joints:
        if any(insts[side.instance].part not in parts for side in (joint.a, joint.b)):
            continue  # an end is a placeholder (C-06): its snap points are not known, so the joint is not judged
        ends = []
        for side in (joint.a, joint.b):
            inst = insts[side.instance]
            part = parts[inst.part]
            ends.append((side, inst, part, next(s for s in part.snap_points if s.id == side.snap_point)))
        (ra, ia, pa, sa), (rb, ib, pb, sb) = ends
        refs = (
            Ref(kind=RefKind.JOINT, id=joint.id),
            Ref(kind=RefKind.SNAP_POINT, id=f"{ra.instance}/{ra.snap_point}"),
            Ref(kind=RefKind.SNAP_POINT, id=f"{rb.instance}/{rb.snap_point}"),
        )
        key = frozenset({("snap", joint.id)})
        if sb.kind not in sa.accepts or sa.kind not in sb.accepts:
            out.append(
                (
                    key,
                    Reason(
                        code=ReasonCode.INVALID_SNAP,
                        message=(
                            f"joint {joint.id!r}: snap point {ra.snap_point!r} of {ra.instance!r} (kind {sa.kind!r}, "
                            f"accepts {list(sa.accepts)}) and {rb.snap_point!r} of {rb.instance!r} (kind {sb.kind!r}, "
                            f"accepts {list(sb.accepts)}) are not compatible: each must accept the other's kind"
                        ),
                        ids=refs,
                    ),
                )
            )
            continue
        gap = math.dist(_snap_world(pa, ia, ra.snap_point), _snap_world(pb, ib, rb.snap_point))
        if gap > tol:
            out.append(
                (
                    key,
                    Reason(
                        code=ReasonCode.INVALID_SNAP,
                        message=(
                            f"joint {joint.id!r}: snap point {ra.snap_point!r} of {ra.instance!r} and "
                            f"{rb.snap_point!r} of {rb.instance!r} are {gap:.6g} m apart at their stored poses; a "
                            "joined pair must meet (a joint moves nothing: move the instance, or both in a batch)"
                        ),
                        ids=refs,
                    ),
                )
            )
    return out


def _body_findings(project: Project, tol: float) -> list[_Finding]:
    parts = {p.id: p for p in project.design.parts}
    bodies = {i.id: (_instance_bodies(parts[i.part], i) if i.part in parts else []) for i in project.design.instances}
    shaped = [i for i in project.design.instances if bodies[i.id]]
    out: list[_Finding] = []

    z_min: dict[str, float] = {}
    for inst in shaped:
        z_min[inst.id] = min(-b.support((0.0, 0.0, -1.0)) for b in bodies[inst.id])
        if z_min[inst.id] < -tol:
            out.append(
                (
                    frozenset({("ground", inst.id)}),
                    Reason(
                        code=ReasonCode.OVERLAP,
                        message=f"instance {inst.id!r} goes {-z_min[inst.id]:.6g} m below the ground (z = 0)",
                        ids=(Ref(kind=RefKind.INSTANCE, id=inst.id),),
                    ),
                )
            )

    bound = {i.id: [(_bound(b), b) for b in bodies[i.id]] for i in shaped}
    parent = {i.id: i.id for i in shaped}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for n, a in enumerate(shaped):
        for b in shaped[n + 1 :]:
            overlap = contact = False
            for ra, ba in bound[a.id]:
                for rb, bb in bound[b.id]:
                    if math.dist(ba.center, bb.center) > ra + rb + tol:
                        continue
                    if not cx.separated(ba, bb, tol):
                        overlap = contact = True
                    elif _touch(ba, bb, tol):
                        contact = True
            if overlap:
                out.append(
                    (
                        frozenset({("pair", *sorted((a.id, b.id)))}),
                        Reason(
                            code=ReasonCode.OVERLAP,
                            message=(
                                f"instances {a.id!r} and {b.id!r} overlap: their collision shapes interpenetrate by "
                                f"more than {tol:g} m"
                            ),
                            ids=(Ref(kind=RefKind.INSTANCE, id=a.id), Ref(kind=RefKind.INSTANCE, id=b.id)),
                        ),
                    )
                )
            if contact:
                parent[find(a.id)] = find(b.id)

    unknown_partner: set[str] = set()  # joined to an instance without geometry: what holds it is not known
    for joint in project.design.joints:
        a, b = joint.a.instance, joint.b.instance
        if a in parent and b in parent:
            parent[find(a)] = find(b)
        elif a in parent:
            unknown_partner.add(a)
        elif b in parent:
            unknown_partner.add(b)

    props = _prop_bodies(project)
    supported = {find(i) for i in unknown_partner}
    penetrating: set[str] = set()  # reported as `overlap` already: not also called floating
    for inst in shaped:
        on_prop = False
        for prop_id, prop in props:
            hit = {"overlap": False, "touch": False}
            for body in bodies[inst.id]:
                if not cx.separated(body, prop, tol):
                    hit["overlap"] = True
                elif _touch(body, prop, tol):
                    hit["touch"] = True
            if hit["overlap"]:
                penetrating.add(find(inst.id))
                out.append(
                    (
                        frozenset({("prop", inst.id, prop_id)}),
                        Reason(
                            code=ReasonCode.OVERLAP,
                            message=f"instance {inst.id!r} penetrates terrain prop {prop_id!r} by more than {tol:g} m",
                            ids=(Ref(kind=RefKind.INSTANCE, id=inst.id), Ref(kind=RefKind.PROP, id=prop_id)),
                        ),
                    )
                )
            on_prop = on_prop or hit["touch"]
        if z_min[inst.id] <= tol or on_prop:
            supported.add(find(inst.id))
    groups: dict[str, list[str]] = {}
    for inst in shaped:
        groups.setdefault(find(inst.id), []).append(inst.id)
    for root, members in groups.items():
        if root not in supported and root not in penetrating:
            out.append(
                (
                    frozenset(("floating", m) for m in members),
                    Reason(
                        code=ReasonCode.FLOATING,
                        message=(
                            f"{', '.join(repr(m) for m in members)} float{'s' if len(members) == 1 else ''}: nothing "
                            "joined or touching reaches the ground or a terrain prop"
                        ),
                        ids=tuple(Ref(kind=RefKind.INSTANCE, id=m) for m in members),
                    ),
                )
            )
    return out


def _world_findings(project: Project) -> list[_Finding]:
    try:
        check_world_references(
            project.world, planets=load_bodies().keys(), materials=[m.id for m in project.design.materials]
        )
    except ValueError as e:
        refs = []
        if project.world.planet not in load_bodies():
            refs.append(Ref(kind=RefKind.PLANET, id=project.world.planet))
        return [
            (
                frozenset({("planet", project.world.planet)}),
                Reason(code=ReasonCode.UNKNOWN_ID, message=str(e), ids=tuple(refs)),
            )
        ]
    return []


def _findings(project: Project, tol: float) -> list[_Finding]:
    return _world_findings(project) + _snap_findings(project, tol) + _body_findings(project, tol)


def check_placement(project: Project, *, tolerance: float = PLACEMENT_TOLERANCE) -> tuple[Reason, ...]:
    """Everything the checks of the module docstring find in `project` (not only what a command introduced), in
    a fixed order: planet, snaps, ground and overlaps, floating. Empty when the project passes."""
    return tuple(reason for _, reason in _findings(project, tolerance))


# --- the gate -----------------------------------------------------------------------------------------------


# --- missing definitions (C-06) -----------------------------------------------------------------------------


class ProjectIncomplete(Exception):
    """An operation was refused because the project has missing definitions. `missing` lists them, `reasons` is the
    same as `Reason`s for the wire."""

    def __init__(self, operation: BlockedOperation, missing: tuple[MissingDefinition, ...]):
        self.operation = operation
        self.missing = missing
        self.reasons = missing_reasons(missing)
        listed = ", ".join(f"{m.kind} {m.id!r}" for m in missing)
        super().__init__(
            f"cannot {operation.value}: the project has no definition for {listed}. Relink the instances, add the "
            "definition, or delete the instances"
        )


def require_complete(project: Project, operation: BlockedOperation) -> None:
    """Raise `ProjectIncomplete` when `project` has a missing definition. Compile, run, verdict and Halo export call
    this first: a project is never run with a part left out."""
    missing = missing_definitions(project)
    if missing:
        raise ProjectIncomplete(operation, missing)


def _refuse_new_missing(before: Project, after: Project) -> None:
    """A command never makes a placeholder (C-06): an instance of a part or material the project does not carry can
    only come from a file that was opened. What was missing before may stay missing while the user works on it (and
    undo, redo, which use `apply_command`, may put it back)."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for kind, ident, user in sorted(missing_users(after) - missing_users(before)):
        grouped.setdefault((kind, ident), []).append(user)
    if grouped:
        missing = tuple(MissingDefinition(kind=k, id=i, instances=tuple(u)) for (k, i), u in grouped.items())  # type: ignore[arg-type]
        raise CommandRejected(missing_reasons(missing))


def validate_command(project: Project, command: Command, *, tolerance: float = PLACEMENT_TOLERANCE) -> ApplyResult:
    """`apply_command` with the policy and placement checks. Raises `CommandRejected` and leaves `project` as it is
    when the command (or one command of a batch) is refused, with one reason per problem; otherwise returns the same
    `ApplyResult`. Takes no origin: every source gets the same answer."""
    _check_policy(command)
    result = apply_command(project, command)
    if result.project == project:
        return result
    _refuse_new_missing(project, result.project)
    found = _findings(result.project, tolerance)
    if found:
        before = {key for keys, _ in _findings(project, tolerance) for key in keys}
        introduced = tuple(reason for keys, reason in found if not keys <= before)
        if introduced:
            raise CommandRejected(introduced)
    return result
