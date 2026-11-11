"""Separator part (B-15): a declared-mass coupling that joins two parts and lets go on command, with one declared push.

What is modelled: the part is a body of declared mass and its own dimensions. Two held parts are joined to its two faces,
`face_a` and `face_b`, by fixed joints (`DesignSpec` rejects any other joint kind at a separator). When the release event
happens (X-08, not here) the two joints let go and each side receives the **declared separation impulse** `J` [N*s]: equal in
size, opposite in direction (momentum is conserved), along the outward normal of the face it was joined to. `J = 0` is allowed:
the joints let go and nothing pushes.

What is not: what makes the push (an energy source of any kind), how it is released, its timing or shape in time, shock and
vibration, the hardware that holds the parts. The part has no field for any of them. The impulse is the user's number or the
definition's placeholder (badge `declared` or `default`), and the assumption table shows it as the simplified model
"단순화 모델: 선언 분리 충격량" (`separation_assumption`).

The release itself, the impulse acting on the two bodies and the velocity that follows are X-08. This module reads the part.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from kinetra_core import (
    SEPARATOR_BADGES,
    SEPARATOR_FACE_A,
    SEPARATOR_FACE_B,
    SEPARATOR_IMPULSE,
    Assumption,
    Badge,
    Confidence,
    PartDef,
    PartRole,
    Quantity,
)
from kinetra_core.convex import rotation

from ._shape import _resolve_parameters

ASSUMPTION_LABEL = "단순화 모델: 선언 분리 충격량"
"""What the assumption table calls the separation impulse (DoD of B-15)."""


class SeparatorError(ValueError):
    """The part is not a separator, or a value given for its impulse is not allowed."""


@dataclass(frozen=True)
class Separator:
    """What a separator part says about the release, at its defaults or at the instance's parameter values.

    `impulse` is the declared separation impulse [N*s] with its badge and source (`declared` or `default`). `direction_a` and
    `direction_b` are unit vectors in the part frame: the push on the body joined at `face_a` (resp. `face_b`) is `impulse` times
    that vector, the outward normal of the face. Faces sit on opposite sides of the part, so the two pushes are opposite when the
    part's faces are antiparallel (`test_separator_library_part_pushes_are_equal_and_opposite`)."""

    part_id: str
    impulse: Quantity
    position_a: tuple[float, float, float]
    position_b: tuple[float, float, float]
    direction_a: tuple[float, float, float]
    direction_b: tuple[float, float, float]


def separator_from_part(part: PartDef, parameters: Mapping[str, Quantity] | None = None) -> Separator:
    """Read the separation impulse and the two faces of a `separator` part. `parameters` is an instance's override (range
    checked by `ShapeError` like every parameter); an impulse badge other than `declared`/`default` raises `SeparatorError`."""
    if part.role is not PartRole.SEPARATOR:
        raise SeparatorError(f"part {part.id!r} has role {part.role.value if part.role else None!r}, not 'separator'")
    q = _resolve_parameters(part, parameters)
    impulse = q[SEPARATOR_IMPULSE]
    if impulse.badge not in SEPARATOR_BADGES:
        raise SeparatorError(
            f"separation impulse of {part.id!r} has badge {impulse.badge.value!r}: only 'declared' or 'default' are allowed"
        )
    values = {name: quantity.value for name, quantity in q.items()}
    snaps = {s.id: s for s in part.snap_points}
    out = {}
    for name in (SEPARATOR_FACE_A, SEPARATOR_FACE_B):
        s = snaps[name]  # PartDef guarantees both faces
        r = rotation(s.orientation)
        out[name] = (s.position.evaluate(values), (r[0][2], r[1][2], r[2][2]))
    return Separator(
        part_id=part.id,
        impulse=impulse,
        position_a=out[SEPARATOR_FACE_A][0],
        position_b=out[SEPARATOR_FACE_B][0],
        direction_a=out[SEPARATOR_FACE_A][1],
        direction_b=out[SEPARATOR_FACE_B][1],
    )


def separation_assumption(sep: Separator, key: str = SEPARATOR_IMPULSE) -> Assumption:
    """The assumption-table row of a separator's impulse: label "단순화 모델: 선언 분리 충격량", the impulse with its own badge
    and source, no distribution (fixed). Confidence is `low` for the definition's placeholder and `med` for a value the user
    declared; neither is `high` because nothing checks that the declared number is what a real mechanism would give."""
    confidence = Confidence.MED if sep.impulse.badge is Badge.DECLARED else Confidence.LOW
    return Assumption(key=key, label=ASSUMPTION_LABEL, value=sep.impulse, confidence=confidence)


__all__ = ["ASSUMPTION_LABEL", "Separator", "SeparatorError", "separation_assumption", "separator_from_part"]
