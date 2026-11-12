"""Model labels of a compile (X-01a, W-03b): the approximations the model makes, stated where the user reads the assumptions.

    model_labels(tree) -> tuple[ModelLabel, ...]    # proxy labels, contact labels (X-01e), then the drag label
    proxy_labels(tree) -> tuple[ModelLabel, ...]
    drag_labels(tree) -> tuple[ModelLabel, ...]

A collision proxy is made of convex primitives, so it cannot have a hole. A void it could not keep is filled; a through-bore it
could keep is approximated by box pieces (`collision-proxy.md`). Either way the contact geometry differs from the part, and the
label says by how much. `ModelLabel.text` is the sentence the verdict's assumption table and the run's `model_labels` show; the
other fields say what it is about (D4: the core computes them, a client shows them as given). Labels are in canonical order
(instance id, then host id), so the list is the same for projects with the same `project_hash`.

- **(a) filled void** (`CollisionProxy.filled_voids` not empty, B-01b): `근사: 충돌 프록시가 빈 곳을 메움(+N%)`, one per instance,
  N = the sum of the filled void volumes / `recipe_volume`, in percent. It is **not** `volume_error`: on a part that also has a
  decomposed host, `volume_error` nets the filled volume against the volume the decomposition leaves out and can be 0 or negative.
- **(b) decomposed void** (`decomposed_voids` not empty, B-01f): `근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함(오차 N%, 허용 오차 T%[, 기본값])`,
  one per decomposed host, N = that host's signed `error`, T = `derivation.tolerance`; `, 기본값` follows T when its badge is `default`.
- A part with no void has no label.
- **(c) lumped drag** (W-03b, `drag.py`): `근사: 집중 항력`, one per compile, when the planet's atmosphere density is above 0
  (Earth, Mars). On the Moon the density is 0, no drag force is applied and there is no label.

Percentages are written with three significant digits (`+7.0%`, `-2.47%`, `10%`) and a sign on N.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kinetra_core import Badge

from .bodytree import BodyTree, CompiledInstance
from .drag import DRAG_LABEL

FILLED_PREFIX = "근사: 충돌 프록시가 빈 곳을 메움"
DECOMPOSED_PREFIX = "근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함"


@dataclass(frozen=True)
class ModelLabel:
    """One approximation label. `kind` `filled` or `decomposed` (collision proxy, here), `contact` (`contact.contact_labels`,
    X-01e) or `drag` (`drag_labels`, W-03b); `instance` and `part` say whose proxy or friction it is (`None` for a model-wide
    label); `host` is the decomposed host component (`None` otherwise); `percent` is N, the number in the text (percent,
    signed for `decomposed`; `None` for `contact` and `drag`)."""

    text: str
    kind: Literal["filled", "decomposed", "contact", "drag"]
    instance: str | None
    part: str | None
    host: str | None
    percent: float | None


def _g(x: float) -> str:
    return f"{x:.3g}"


def _labels_of(ci: CompiledInstance) -> list[ModelLabel]:
    proxy = ci.proxy
    out: list[ModelLabel] = []
    if proxy.filled_voids:
        filled = sum(v.volume for v in proxy.filled_voids)
        n = 100.0 * filled / proxy.recipe_volume.value
        out.append(ModelLabel(f"{FILLED_PREFIX}(+{_g(n)}%)", "filled", ci.instance, ci.part, None, n))
    tolerance = proxy.derivation.tolerance
    for v in sorted(proxy.decomposed_voids, key=lambda d: d.host):
        assert tolerance is not None  # ProxyDerivation ties it to a decomposition
        n = 100.0 * v.error
        t = 100.0 * tolerance.value
        default = ", 기본값" if tolerance.badge is Badge.DEFAULT else ""
        out.append(
            ModelLabel(f"{DECOMPOSED_PREFIX}(오차 {'+' if n >= 0 else ''}{_g(n)}%, 허용 오차 {_g(t)}%{default})", "decomposed", ci.instance, ci.part, v.host, n)
        )
    return out


def proxy_labels(tree: BodyTree) -> tuple[ModelLabel, ...]:
    """Every proxy approximation label of the compile, in canonical order (instances by id; per instance (a) then (b) by host id)."""
    return tuple(label for ci in tree.instances for label in _labels_of(ci))


def drag_labels(tree: BodyTree) -> tuple[ModelLabel, ...]:
    """`(c)`: the lumped-drag label when the planet's atmosphere density is above 0, else nothing."""
    if tree.planet.atmosphere_density.value > 0.0:
        return (ModelLabel(DRAG_LABEL, "drag", None, None, None, None),)
    return ()


def model_labels(tree: BodyTree) -> tuple[ModelLabel, ...]:
    """Every model label of the compile: `proxy_labels`, the contact labels (`contact.contact_labels` of the nominal ground
    friction, X-01e), then `drag_labels`. The list the run's `model_labels` and the verdict's assumption table show."""
    from .contact import contact_friction, contact_labels  # contact.py imports ModelLabel from here

    return proxy_labels(tree) + contact_labels(contact_friction(tree)) + drag_labels(tree)
