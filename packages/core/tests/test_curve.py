"""B-03b: `Curve` and `PartDef.curves`. A curve is points with one badge and source; no point is believed without them."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kinetra_core import Curve, NamedCurve, Unit

SRC = {"ref": "unit-test fixture", "locator": "test_curve.py"}


def curve(points, **kw):
    d = {"badge": "declared", "source": SRC, "x_unit": "rad/s", "y_unit": "N*m", "points": [{"x": x, "y": y} for x, y in points]}
    d.update(kw)
    return d


def test_curve_accepts_two_or_more_increasing_points():
    c = Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.5), (3.0, 0.0)]))
    assert [p.x for p in c.points] == [0.0, 1.0, 3.0]
    assert c.x_unit is Unit.RAD_PER_S and c.y_unit is Unit.N_M


@pytest.mark.parametrize(
    "points, message",
    [
        ([(0.0, 1.0)], "at least 2 points"),
        ([], "at least 2 points"),
        ([(0.0, 1.0), (0.0, 2.0)], "strictly increasing"),
        ([(1.0, 1.0), (0.5, 2.0)], "strictly increasing"),
        ([(0.0, math.inf), (1.0, 0.0)], "finite"),
        ([(0.0, 1.0), (math.nan, 0.0)], "finite"),
    ],
)
def test_curve_rejects_bad_points(points, message):
    with pytest.raises(ValidationError, match=message):
        Curve.model_validate(curve(points))


def test_curve_needs_badge_and_source_and_units():
    for key in ("badge", "source", "x_unit", "y_unit"):
        d = curve([(0.0, 1.0), (1.0, 0.0)])
        del d[key]
        with pytest.raises(ValidationError, match=key):
            Curve.model_validate(d)


def test_curve_units_are_the_closed_unit_vocabulary():
    with pytest.raises(ValidationError, match="x_unit"):
        Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)], x_unit="rpm"))


def test_curve_cited_needs_a_place_in_the_source_and_declared_does_not():
    Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)]))
    with pytest.raises(ValidationError, match="cited"):
        Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)], badge="cite", source={"ref": "a datasheet"}))
    Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)], badge="cite", source={"ref": "a datasheet", "locator": "p. 3, fig. 2"}))


def test_curve_name_follows_the_name_pattern():
    NamedCurve.model_validate({"name": "torque_speed", "curve": curve([(0.0, 1.0), (1.0, 0.0)])})
    with pytest.raises(ValidationError, match="name"):
        NamedCurve.model_validate({"name": "Torque-Speed", "curve": curve([(0.0, 1.0), (1.0, 0.0)])})


def test_curve_rejects_unknown_fields_and_a_json_roundtrip_is_equal():
    with pytest.raises(ValidationError, match="extrapolate"):
        Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)], extrapolate=True))
    c = Curve.model_validate(curve([(0.0, 1.0), (1.0, 0.0)]))
    assert Curve.model_validate_json(c.model_dump_json()) == c and hash(c) == hash(c)
