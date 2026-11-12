"""Contact events of a run (#562): which bodies touch the ground, a terrain prop or another body, tick by tick, as the
`contact` `begin`/`end` events of `client-adapter.md` 3.3 (C-05b).

    ContactWatch(model) -> .events(model, data, tick) -> list of `contact` event dicts; .bind(model) after a recompile

**What touches (threshold).** At a tick, the engine's own collision detection (`mj_collision`, after `mj_kinematics` of the
tick's positions) lists the contact points of that tick's pose. A point counts when its distance is at most 0 (the two
geoms touch or overlap): every compiled geom has MuJoCo's default margin 0, and the explicit `dist <= 0` keeps the rule
the same if a margin is ever set. No force threshold and no debounce: a resting body stays in contact (its soft contact
holds a steady small overlap), and a bounce that leaves the surface is an `end` and a new `begin`. Two bodies joined
directly by a joint (a parent and its child in the body tree) never collide (MuJoCo excludes parent-child pairs), so they
have no contact events while the joint holds; once a break releases the joint (X-04b) they collide like any two bodies.

**Dedupe.** The points are reduced to pairs: (body, ground), (body, prop id), or (body, body) for two bodies, written once
with `body` the smaller id and `other` the larger. Every geom of a body (its instances' proxy geoms, `bodytree.py`) is
that body; the ground is `GROUND_GEOM`, a prop is its `PROP_GEOM_PREFIX + <id>` geom. An event is sent only when a pair's
state changes: `begin` at the first tick the pair touches, `end` at the first tick it does not. Tick 0 (the saved pose)
gives the `begin` of every pair touching at the start; a pair still touching when the run ends has no `end`.

**Order.** Within a tick, `begin` events come before `end` events, each in pair order (body id, then ground, props by id,
bodies by id). Begins first: when one body touches down in the tick another lifts off, the run never had a tick with
nothing touching, and a reader that walks the events in order (J-02a `landing`) does not see one.

**Breaks.** The pairs are keyed by name, not by engine index, so after a break the run binds the watch to the model
compiled again (`bind`) and goes on: a pair touching before the break and after it has no event at the break.

`force` is not given: the contact force of a tick comes from that tick's constraint solve, which this pose-only
collision pass does not run (the field is optional in C-05b and its accuracy is out of this leaf's scope).
"""

from __future__ import annotations

import mujoco
import numpy as np

from ..compiler import GROUND_GEOM, PROP_GEOM_PREFIX

Pair = tuple[str, str, str]
"""(body id, other kind `ground`/`prop`/`body`, other id; `""` for the ground)."""

_RANK = {"ground": 0, "prop": 1, "body": 2}


def _other(kind: str, ident: str) -> dict:
    return {"kind": "ground"} if kind == "ground" else {"kind": kind, "id": ident}


class ContactWatch:
    """The contact pairs of one run, followed tick by tick (module docstring)."""

    def __init__(self, model: mujoco.MjModel):
        self._touching: set[Pair] = set()
        self.bind(model)

    def bind(self, model: mujoco.MjModel) -> None:
        """Read what each geom of `model` is (a body, the ground or a prop): the compiled model, or the one after a break."""
        targets: list[tuple[str, str]] = []
        for g in range(model.ngeom):
            name = model.geom(g).name
            if name == GROUND_GEOM:
                targets.append(("ground", ""))
            elif name.startswith(PROP_GEOM_PREFIX):
                targets.append(("prop", name[len(PROP_GEOM_PREFIX) :]))
            else:
                targets.append(("body", model.body(int(model.geom_bodyid[g])).name))
        self._targets = targets

    def _pairs(self, model: mujoco.MjModel, data: mujoco.MjData) -> set[Pair]:
        mujoco.mj_kinematics(model, data)
        mujoco.mj_collision(model, data)  # the next mj_step recomputes both from the positions; nothing carries over
        pairs: set[Pair] = set()
        n = data.ncon
        if not n:
            return pairs
        con = data.contact
        touching = np.flatnonzero(con.dist[:n] <= 0.0)
        for g1, g2 in zip(con.geom1[touching], con.geom2[touching]):
            a, b = self._targets[int(g1)], self._targets[int(g2)]
            if a[0] != "body":  # a world geom (ground, prop) only collides with a body's geom
                a, b = b, a
            if b[0] == "body":
                lo, hi = sorted((a[1], b[1]))
                pairs.add((lo, "body", hi))
            else:
                pairs.add((a[1], b[0], b[1]))
        return pairs

    def events(self, model: mujoco.MjModel, data: mujoco.MjData, tick: int) -> list[dict]:
        """The `contact` events of `tick`: the pairs that began and ended touching since the previous call."""
        now = self._pairs(model, data)
        key = lambda p: (p[0], _RANK[p[1]], p[2])  # noqa: E731
        begun = sorted(now - self._touching, key=key)
        ended = sorted(self._touching - now, key=key)
        self._touching = now
        return [
            {"kind": "contact", "tick": tick, "phase": phase, "body": p[0], "other": _other(p[1], p[2])}
            for phase, pairs in (("begin", begun), ("end", ended))
            for p in pairs
        ]
