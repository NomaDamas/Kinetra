"""Two records of a run compared by their trajectory evidence (X-02d; `docs/decisions/engine.md` 5.4, H1 and H2).

    trajectory_evidence(record) -> TrajectoryEvidence       # refuses a hash without its platform tag (UntaggedTrajectory)
    compare_trajectories(a, b) -> TrajectoryComparison      # match | mismatch | not_comparable

A record is the `trajectory` of a `run_ended` (`RunCompleted.trajectory`, `RunStopped.trajectory`): the hash and the
platform tag it was computed under (`TrajectoryEvidence`, field names of C-05b). The core computes the hash
(`kinetra_engine.run.preview`, F7); a hash without its tag is not evidence (H1), so it is refused here, never compared.

The result is one of three (H2):

| result | when | what it says |
|---|---|---|
| `match` (일치) | the tags are equal and the hashes are equal | the two runs produced the same trajectory |
| `mismatch` (불일치) | the tags are equal and the hashes differ | the runs differ; find the cause (a component missing from the tag table is one) |
| `not_comparable` (비교 불가) | the tags differ | nothing: the hashes are not compared |

Two tags are equal only when all eight components are equal (`==`, `client-adapter.md` 3.3); one differing
component, including ⑦ (the compute settings of the run), makes them different tags.

What is observed: the same project, seed and inputs give the same hash on one build and one machine, repeated
(`packages/engine/tests/test_determinism.py`). That an equal tag implies an equal hash on another machine is an
assumption that A0-05a #432 verifies [확인 필요]; until then a `match` across machines says only that the hashes are equal.
Comparing two records says nothing about whether they are records of the same project, seed and inputs: the caller
compares those (`run_started.definition_hash`, `seed`, `last_tick`).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from .frames import TrajectoryEvidence


class TrajectoryComparison(StrEnum):
    """The result of comparing two trajectory records (H2)."""

    MATCH = "match"
    MISMATCH = "mismatch"
    NOT_COMPARABLE = "not_comparable"

    @property
    def label_ko(self) -> str:
        return _LABEL_KO[self]


_LABEL_KO = {
    TrajectoryComparison.MATCH: "일치",
    TrajectoryComparison.MISMATCH: "불일치",
    TrajectoryComparison.NOT_COMPARABLE: "비교 불가",
}


class UntaggedTrajectory(ValueError):
    """A trajectory hash without its platform tag: not evidence (H1), so it is not compared."""


def trajectory_evidence(record: TrajectoryEvidence | Mapping) -> TrajectoryEvidence:
    """`record` as trajectory evidence: a `TrajectoryEvidence`, or its JSON object (`{"hash": ..., "platform": ...}`).
    Raises `UntaggedTrajectory` when the object has no platform tag (missing or `null`), and pydantic's
    `ValidationError` when the hash or the tag is malformed (a tag lacking one of its eight components included)."""
    if isinstance(record, TrajectoryEvidence):
        return record
    if not isinstance(record, Mapping):
        raise TypeError(f"a trajectory record is a TrajectoryEvidence or its JSON object, not {type(record).__name__}")
    if record.get("platform") is None:
        raise UntaggedTrajectory("a trajectory hash without its platform tag is not evidence (engine.md 5.4 H1)")
    return TrajectoryEvidence.model_validate(record)


def compare_trajectories(a: TrajectoryEvidence | Mapping, b: TrajectoryEvidence | Mapping) -> TrajectoryComparison:
    """Compare two trajectory records (H2): `not_comparable` when their platform tags differ (the hashes are then not
    looked at), else `match` or `mismatch` by the hashes. Both records are read by `trajectory_evidence` first, so an
    untagged one raises `UntaggedTrajectory` instead of giving a result."""
    a, b = trajectory_evidence(a), trajectory_evidence(b)
    if a.platform != b.platform:
        return TrajectoryComparison.NOT_COMPARABLE
    return TrajectoryComparison.MATCH if a.hash == b.hash else TrajectoryComparison.MISMATCH
