"""The time window of a breakable joint's load (X-10), and the largest time step a run may take.

A joint's load is not one step's constraint force: that force depends on the time step, most of all in a collision, whose
impulse the solver spreads over however many steps the contact takes. The engine compares, every step, the joint's mean
force over the last `BREAK_LOAD_WINDOW` seconds of simulated time (its impulse over the window divided by the window) with
its break threshold (`kinetra_engine.compiler.breaks.BreakWatch`). The window is longer than the largest time step a run may
take (`MAX_TIMESTEP_S`), so it always spans more than one step. Its row is in the verdict's assumption table of a design
with a breakable joint (`verdict_assumption_table`), read-only: a modelling choice, badge `기본값`. See
`docs/architecture/break-threshold.md` ("시간 간격 불변 기준") and `docs/research/engine/break-timestep.md`.
"""

from __future__ import annotations

from .assumption import ENGINE_CONSTANT_NAMES, Assumption, Confidence
from .conventions import Unit
from .provenance import Badge, Quantity, Source

MAX_TIMESTEP_S = 0.002
"""The largest time step [s] a run may take: MuJoCo's default `option/timestep`, the one every run used before X-10. A run
may take a smaller one, fixed for the whole run (`compile_project(timestep_s=...)`); there is no larger one."""

BREAK_LOAD_WINDOW_KEY = "break_load_window"
assert BREAK_LOAD_WINDOW_KEY in ENGINE_CONSTANT_NAMES

BREAK_LOAD_WINDOW = Assumption(
    key=BREAK_LOAD_WINDOW_KEY,
    label="파단 하중 평균 창",
    value=Quantity(
        value=0.02,
        unit=Unit.S,
        badge=Badge.DEFAULT,
        source=Source(
            ref=(
                "Kinetra's choice (X-10): the time constant of the soft contact, MuJoCo's default solref 0.02 s "
                "(kinetra_engine.compiler.contact.CONTACT_PARAMETERS), so a collision's impulse is averaged over the time the "
                "contact takes to resolve it; 10 x MAX_TIMESTEP_S. Not derived from a standard or a measurement; "
                "docs/research/engine/break-timestep.md measures what it gives"
            ),
            locator="docs/architecture/break-threshold.md, 시간 간격 불변 기준",
        ),
    ),
    confidence=Confidence.LOW,
    editable=False,
)
"""The window [s] over which a breakable joint's force is averaged before it is compared with its threshold."""
