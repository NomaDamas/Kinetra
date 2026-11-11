"""W-01: planet data files and loader (`-k bodies`). The numbers are the data files' own; tests check structure,
badges, sources, cross-checks between a value and what its source text says, and that no code carries a gravity."""

from __future__ import annotations

import io
import json
import math
import re
import tokenize
from pathlib import Path

import pytest
from pydantic import ValidationError

from kinetra_core import (
    BODIES_DIR,
    BODY_IDS,
    PLANET_CONSTANT_NAMES,
    AssumptionTable,
    Badge,
    Body,
    Unit,
    World,
    check_world_references,
    load_bodies,
    load_body,
)

REPO = Path(__file__).resolve().parents[3]


def raw(body_id):
    return json.loads((BODIES_DIR / f"{body_id}.json").read_text(encoding="utf-8"))


def quantities(body):
    d = body.ground_friction.distribution
    return {
        "gravity": body.gravity,
        "atmosphere_density": body.atmosphere_density,
        "insolation": body.insolation,
        "ground_friction.value": body.ground_friction.value,
        "ground_friction.distribution": d,
    }


def test_bodies_three_planets_load_with_expected_ids():
    bodies = load_bodies()
    assert tuple(bodies) == BODY_IDS == ("earth", "mars", "moon")
    for i, b in bodies.items():
        assert b.id == i
    assert sorted(p.name for p in BODIES_DIR.glob("*.json")) == ["earth.json", "mars.json", "moon.json"]


def test_bodies_every_item_has_badge_source_and_access_date():
    for b in load_bodies().values():
        for name, q in quantities(b).items():
            assert q.badge in set(Badge), (b.id, name)
            assert re.search(r"accessed \d{4}-\d{2}-\d{2}", q.source.ref), (b.id, name, "no access date")
            assert q.source.ref and (q.source.url or q.source.locator), (b.id, name)
            if q.source.url:
                assert q.source.url.startswith("https://"), (b.id, name)


def test_bodies_cited_values_say_where_in_the_source():
    for b in load_bodies().values():
        for name, q in quantities(b).items():
            if q.badge is Badge.CITE:
                assert q.source.locator and q.source.url, (b.id, name)


def test_bodies_units_are_si_and_closed_vocabulary():
    for b in load_bodies().values():
        assert b.gravity.unit is Unit.M_PER_S2
        assert b.atmosphere_density.unit is Unit.KG_PER_M3
        assert b.insolation.unit is Unit.W_PER_M2
        assert b.ground_friction.value.unit is Unit.ONE


@pytest.mark.parametrize(
    "body_id, g, rho, s",
    [("earth", 9.80665, 1.217, 1361.0), ("mars", 3.73, 0.016, 586.2), ("moon", 1.62, 0.0, 1361.0)],
)
def test_bodies_values_match_what_their_sources_print(body_id, g, rho, s):
    """Values as printed on the NASA NSSDCA fact sheets read 2026-11-11 (see each `source.ref`)."""
    b = load_body(body_id)
    assert (b.gravity.value, b.atmosphere_density.value, b.insolation.value) == (g, rho, s)


def test_bodies_gravity_ordering_and_cross_checks():
    e, m, moon = (load_body(i) for i in BODY_IDS)
    assert e.gravity.value > m.gravity.value > moon.gravity.value
    # GM/R^2 from the GM and mean radius in km^3/s^2 and km (Earth, Mars: the fact sheets; Moon: JPL SSD DE440), within
    # 1% of the stored surface gravity.
    for body, gm, radius in [(e, 398600.0, 6371.0), (m, 42828.0, 3389.5), (moon, 4902.8, 1737.4)]:
        assert body.gravity.value == pytest.approx(gm / radius**2 * 1e3, rel=0.01)
    assert e.atmosphere_density.value > m.atmosphere_density.value > moon.atmosphere_density.value == 0.0
    assert moon.insolation.value == e.insolation.value > m.insolation.value


def test_bodies_ground_friction_is_a_c01c_assumption_with_an_honest_distribution():
    for b in load_bodies().values():
        a = b.ground_friction
        d = a.distribution
        assert a.key == "ground_friction" and a.editable is False
        assert d.kind == "uniform" and 0 < d.low < a.value.value < d.high
        assert d.badge is Badge.ESTIMATE and a.value.badge is Badge.ESTIMATE
        assert a.confidence.value == "low"  # never higher: no source gives a distribution or a part-on-ground coefficient


TAN_PAIR = r"tan\((\d+(?:\.\d+)?) deg\) = (\d+\.\d+)"


def test_bodies_friction_values_are_tangents_of_the_angles_in_their_sources():
    """One bounds rule and one nominal rule for all three planets, checked against the stored numbers.

    Bounds: `low` and `high` are tan of the two angles the distribution's `source.ref` names, and equal the numbers
    printed there. Nominal: the mean of the bounds, and its `source.ref` names the same two pairs."""
    for b in load_bodies().values():
        a = b.ground_friction
        d = a.distribution
        pairs = re.findall(TAN_PAIR, d.source.ref)
        assert len(pairs) == 2, (b.id, "distribution ref names exactly two angles")
        (lo_deg, lo_txt), (hi_deg, hi_txt) = pairs
        assert float(lo_deg) < float(hi_deg), b.id
        assert d.low == pytest.approx(math.tan(math.radians(float(lo_deg))), abs=5e-5), (b.id, "low")
        assert d.high == pytest.approx(math.tan(math.radians(float(hi_deg))), abs=5e-5), (b.id, "high")
        assert (d.low, d.high) == (float(lo_txt), float(hi_txt)), (b.id, "bounds differ from their ref text")
        assert re.findall(TAN_PAIR, a.value.source.ref) == pairs, (b.id, "nominal ref names the same bounds")
        assert a.value.value == pytest.approx((d.low + d.high) / 2, abs=5.1e-5), (b.id, "nominal is the midpoint")
        assert "Midpoint of the bounds" in a.value.source.ref


def test_bodies_friction_text_states_the_high_grip_bias_and_names_its_source():
    for b in load_bodies().values():
        ref = b.ground_friction.value.source.ref
        assert "upper bound for a smooth part" in ref and "NAVFAC DM 7.02" in ref and "0.20 to 0.60" in ref, b.id
        (reason,) = [u.reason for u in b.unverified if u.item == "ground_friction"]
        assert "upper bound" in reason and "grip biased high" in reason, b.id
        assert "no source measures" not in reason.lower(), b.id


def test_bodies_weak_items_are_marked_unverified_and_cited_ones_are_not():
    expected = {
        "earth": {"ground_friction"},
        "mars": {"ground_friction"},
        "moon": {"atmosphere_density", "ground_friction"},
    }
    for i, b in load_bodies().items():
        assert {u.item for u in b.unverified} == expected[i]
        assert all(len(u.reason) > 40 for u in b.unverified)
    assert load_body("moon").atmosphere_density.badge is Badge.DEFAULT
    assert load_body("moon").atmosphere_density.value == 0.0


@pytest.mark.parametrize("drop", ["earth", "moon"])
def test_bodies_unverified_must_match_badges(drop):
    d = raw(drop)
    d["unverified"] = []
    with pytest.raises(ValidationError, match="must be listed in unverified"):
        Body.model_validate(d)
    d = raw(drop)
    d["unverified"] = d["unverified"] + [{"item": "gravity", "reason": "claimed unverified though cited"}]
    with pytest.raises(ValidationError, match="listed in unverified"):
        Body.model_validate(d)


def test_bodies_a_value_without_badge_or_source_fails():
    for key in ("badge", "source"):
        d = raw("mars")
        del d["gravity"][key]
        with pytest.raises(ValidationError):
            Body.model_validate(d)
    d = raw("mars")
    d["gravity"]["source"]["ref"] = "TBD"
    with pytest.raises(ValidationError, match="placeholder"):
        Body.model_validate(d)
    d = raw("mars")
    d["gravity"]["badge"] = "cite"
    del d["gravity"]["source"]["locator"], d["gravity"]["source"]["url"]
    with pytest.raises(ValidationError, match="locator or source.url"):
        Body.model_validate(d)


def test_bodies_rejects_wrong_units_negative_values_and_unknown_fields():
    d = raw("earth")
    d["gravity"]["unit"] = "m/s"
    with pytest.raises(ValidationError):
        Body.model_validate(d)
    d = raw("earth")
    d["gravity"]["value"] = -9.8
    with pytest.raises(ValidationError):
        Body.model_validate(d)
    d = raw("earth")
    d["ground_friction"]["value"]["unit"] = "m"
    with pytest.raises(ValidationError, match="dimensionless"):
        Body.model_validate(d)
    d = raw("earth")
    d["ground_friction"]["distribution"]["low"] = -0.1
    with pytest.raises(ValidationError, match="below 0"):
        Body.model_validate(d)
    d = raw("earth")
    d["wind"] = 1
    with pytest.raises(ValidationError):
        Body.model_validate(d)


@pytest.mark.parametrize("badge", ["sim", "declared"])
def test_bodies_loader_refuses_badges_a_planet_constant_cannot_have(badge):
    d = raw("mars")
    d["gravity"]["badge"] = badge
    d["gravity"]["source"] = {"ref": "typed by a user", "locator": "x"}
    if badge == "declared":
        d["gravity"]["source"]["declared_by"] = "user"
    with pytest.raises(ValidationError, match="cite, default or estimate"):
        Body.model_validate(d)


def test_bodies_loader_refuses_a_fixed_or_missing_friction_distribution_and_an_editable_one():
    for change in ({"distribution": {"kind": "fixed"}}, {"distribution": None}):
        d = raw("moon")
        if change["distribution"] is None:
            del d["ground_friction"]["distribution"]  # the Assumption default is fixed
        else:
            d["ground_friction"].update(change)
        with pytest.raises(ValidationError, match="needs a distribution"):
            Body.model_validate(d)
    for editable in (True, None):
        d = raw("moon")
        if editable is None:
            del d["ground_friction"]["editable"]  # the Assumption default is True
        else:
            d["ground_friction"]["editable"] = True
        with pytest.raises(ValidationError, match="editable must be false"):
            Body.model_validate(d)
    d = raw("moon")
    d["ground_friction"]["distribution"] = {
        "kind": "normal", "mean": 0.65, "std": 0.1, "clip_low": 0.3, "clip_high": 1.0,
        "badge": "estimate", "source": {"ref": "unit test", "locator": "x"},
    }
    d["ground_friction"]["value"]["value"] = 0.65
    assert Body.model_validate(d).ground_friction.distribution.kind == "normal"


def test_bodies_planet_friction_is_not_a_row_of_the_projects_assumption_table():
    """Contract (docs/architecture/bodies.md, "Gravity and the verdict's table"): the project's `AssumptionTable`
    rejects planet keys. The verdict's table is composed at judge time from project rows and planet rows read from
    `data/bodies` (W-03c). This pins the rejection so a change to it is a decision, not an accident."""
    mars = load_body("mars")
    with pytest.raises(ValidationError, match="planet constant"):
        AssumptionTable(assumptions=(mars.ground_friction,))
    assert "ground_friction" in PLANET_CONSTANT_NAMES


def test_bodies_wheel_carries_the_data_as_package_data():
    """The wheel build puts `data/bodies` into `kinetra_core/bodies_data/` (hatch force-include), so a non-editable
    install does not need the checkout. The config is the part a test can pin without building."""
    cfg = (REPO / "packages" / "core" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"../../data/bodies" = "kinetra_core/bodies_data"' in cfg
    assert (REPO / "data" / "bodies").is_dir()


def test_bodies_loader_errors(tmp_path):
    with pytest.raises(KeyError, match="unknown planet"):
        load_body("venus")
    with pytest.raises(FileNotFoundError, match="not found"):
        load_body("earth", directory=tmp_path)
    d = raw("earth")
    (tmp_path / "earth.json").write_text(json.dumps({**d, "id": "mars"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must equal the file name"):
        load_body("earth", directory=tmp_path)
    (tmp_path / "earth.json").write_text(json.dumps(d), encoding="utf-8")
    assert load_body("earth", directory=tmp_path) == load_body("earth")


def test_bodies_world_names_planet_that_exists_and_materials_of_the_project():
    src = {"ref": "unit-test fixture", "locator": "test_bodies.py"}
    size = {"value": 1.0, "unit": "m", "badge": "declared", "source": src}
    prop = {
        "kind": "step",
        "id": "prop-a",
        "material": "oak",
        "placement": {"x": 0.0, "y": 0.0, "yaw": 0.0, "badge": "declared", "source": src},
        "length": size,
        "width": size,
        "height": size,
    }
    world = World.model_validate({"planet": "mars", "terrain_props": [prop]})
    check_world_references(world, planets=BODY_IDS, materials=["oak"])
    with pytest.raises(ValueError, match="unknown material 'oak'"):
        check_world_references(world, planets=BODY_IDS, materials=[])
    ghost = World.model_validate({"planet": "venus", "terrain_props": [{**prop, "material": None}]})
    with pytest.raises(ValueError, match="unknown planet 'venus'"):
        check_world_references(ghost, planets=BODY_IDS, materials=[])
    with pytest.raises(ValueError) as e:
        check_world_references(
            World.model_validate({"planet": "venus", "terrain_props": [prop]}), planets=BODY_IDS, materials=[]
        )
    assert "venus" in str(e.value) and "oak" in str(e.value)  # every problem is listed


def test_bodies_world_rejects_planet_constants_so_the_data_files_are_their_only_home():
    assert {"gravity", "air_density", "ground_friction", "insolation"} <= PLANET_CONSTANT_NAMES
    with pytest.raises(ValidationError, match="data/bodies"):
        World.model_validate({"planet": "earth", "gravity": 9.8})


# --- no gravity literal in engine or client code ---------------------------------------------------------------
#
# What is scanned: code files under CODE_ROOTS (not tests, build output, or `spikes/`, which are experiments), by
# numeric value. Comments and string literals are removed first with each language's own syntax, so `#` is a comment
# in Python only, `//` and `/* */` only in C-family files, and `"#ffffff"`, URLs and `#private` fields are not
# mistaken for comments. A number is compared as a float (`9.810`, `981e-2`, `0.981e1`, `9.806_65`, `9.81f`) to the
# three gravities with a 1.5% tolerance: the usual roundings (9.8, 9.81, 3.7, 3.71, 1.6, 1.62) and the sheets' own
# surface ranges (Earth 9.780 to 9.832, Mars 3.69 to 3.73) are inside it.
# Not seen: a number in a string (`"0 0 -9.81"` in a TS string is data, not a literal; JSON string values likewise), a template-literal text, a
# computed value (`GM / r**2`), another name for the same constant. Those are the structure's job (the engine reads
# `load_body`; the validator refuses commands that change a planet; C-02c).
# A line that carries `gravity-scan: ok <reason>` is exempt (a CSS line height of 1.62, a 3.7 V cell). No reason, no
# exemption.

C_FAMILY = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".wgsl", ".glsl", ".vert", ".frag"}
MARKUP = {".html", ".vue", ".svelte", ".xml", ".mjcf", ".urdf", ".sdf", ".xacro"}
CODE_SUFFIXES = {".py", ".json"} | C_FAMILY | MARKUP
CODE_ROOTS = ["packages", "apps", "scripts", "tools"]
SKIP_DIRS = {
    "node_modules", ".venv", "dist", "build", "__pycache__", ".next", ".svelte-kit", "coverage", "tests", "test",
    "out", "spikes", "schemas",
}
NUMBER = re.compile(r"(?<![\w.])(\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?|\.\d[\d_]*(?:[eE][+-]?\d+)?)[fF]?(?![\w.])")
EXEMPT = re.compile(r"gravity-scan: ok\s+\S")
GRAVITY_RELATIVE_TOLERANCE = 0.015


def gravity_values():
    return sorted(b.gravity.value for b in load_bodies().values())


def is_gravity_like(x: float, gravities=None) -> bool:
    return any(abs(x - g) <= GRAVITY_RELATIVE_TOLERANCE * g for g in (gravities or gravity_values()))


def _blank(src: str, spans) -> str:
    """`src` with every (start, end) span replaced by spaces, newlines kept so line numbers hold."""
    out = list(src)
    for a, b in spans:
        for i in range(a, b):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


REGEX_PRECEDERS = set("(,=:[!&|?{};") | {"return"}


def regex_literal_end(src: str, i: int) -> int | None:
    """End index of a JS/TS regex literal that starts at `src[i] == "/"`, or None when this `/` is a division.

    It is a regex when the previous token is `( , = : [ ! & | ? { } ;` `return`, or nothing on this line. Inside, `\\x`
    is an escape and `[...]` a class in which `/` does not end it; it ends at the next `/`. A line end first means it was
    not a regex."""
    k = i - 1
    while k >= 0 and src[k] in " \t":
        k -= 1
    if k >= 0 and src[k] != "\n":
        word = re.search(r"[A-Za-z_$][\w$]*$", src[: k + 1])
        if not (src[k] in REGEX_PRECEDERS or (word and word.group(0) == "return")):
            return None
    j, in_class = i + 1, False
    while j < len(src) and src[j] != "\n":
        ch = src[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return j + 1
        j += 1
    return None


def strip_c_family(src: str) -> str:
    """Blank comments (`//`, `/* */`), regex literals and string literals ('...', "...", template `...` text; `${ }`
    stays code)."""
    spans, i, n = [], 0, len(src)
    template_depth = []  # brace depth of each open `${`
    brace = 0
    while i < n:
        c = src[i]
        two = src[i : i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j < 0 else j
            spans.append((i, j))
            i = j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            spans.append((i, j))
            i = j
        elif c == "/" and (end := regex_literal_end(src, i)) is not None:
            spans.append((i, end))
            i = end
        elif c in "\"'":
            j = i + 1
            while j < n and src[j] != c and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            spans.append((i, min(j + 1, n)))
            i = j + 1
        elif c == "`" or (c == "}" and template_depth and brace == template_depth[-1]):
            if c == "}":
                template_depth.pop()
            j = i + 1
            while j < n and src[j] != "`":
                if src[j] == "\\":
                    j += 2
                elif src[j : j + 2] == "${":
                    template_depth.append(brace)
                    break
                else:
                    j += 1
            end = j if j < n and src[j] != "`" else min(j + 1, n)
            if j < n and src[j : j + 2] == "${":
                spans.append((i, j + 2))
                i = j + 2
            else:
                spans.append((i, end))
                i = end
        else:
            if c == "{":
                brace += 1
            elif c == "}":
                brace -= 1
            i += 1
    return _blank(src, spans)


def strip_markup(src: str) -> str:
    """Markup files: only `<!-- -->` comments are removed. Attribute values are the data (`gravity="0 0 -9.81"`)."""
    return _blank(src, [m.span() for m in re.finditer(r"<!--.*?-->", src, re.S)])


def strip_json(src: str) -> str:
    """JSON: string values are prose (`"ref": "... 9.8 ..."`); only bare numbers count."""
    return _blank(src, [m.span() for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"', src)])


def python_numbers(src: str):
    """(line, token) for each NUMBER token; strings, f-string text, docstrings and comments are never numbers."""
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.NUMBER:
            yield tok.start[0], tok.string


def file_numbers(path: Path, src: str):
    if path.suffix == ".py":
        yield from python_numbers(src)
        return
    code = (
        strip_c_family(src) if path.suffix in C_FAMILY else strip_markup(src) if path.suffix in MARKUP else strip_json(src)
    )
    for n, line in enumerate(code.splitlines(), 1):
        for m in NUMBER.finditer(line):
            yield n, m.group(0).rstrip("fF") if not m.group(0).lower().startswith("0x") else m.group(0)


def scan_for_gravity_literals(root: Path, roots=CODE_ROOTS):
    gravities = gravity_values()
    hits = []
    for r in roots:
        base = root / r
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in CODE_SUFFIXES or SKIP_DIRS & set(p.relative_to(base).parts):
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            lines = src.splitlines()
            try:
                found = list(file_numbers(p, src))
            except (tokenize.TokenError, SyntaxError, IndentationError) as e:
                hits.append(f"{p.relative_to(root)}: cannot be scanned ({e})")
                continue
            for n, tok in found:
                try:
                    value = float(tok.replace("_", ""))
                except ValueError:
                    continue  # hex, complex: not a gravity written as a plain number
                if is_gravity_like(value, gravities) and not EXEMPT.search(lines[n - 1]):
                    hits.append(f"{p.relative_to(root)}:{n}: {tok}")
    return hits


def test_bodies_no_gravity_literal_in_engine_or_client_code():
    assert scan_for_gravity_literals(REPO) == []


def plant(tmp_path, name, text):
    f = tmp_path / "packages" / "engine" / "src" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return f"packages/engine/src/{name}"


@pytest.mark.parametrize(
    "literal",
    ["9.81", "9.80665", "9.810", "9.80", "981e-2", "0.981e1", "9.8E0", "9.806_65", "9.78", "9.832", "3.73", "3.71", "3.7",
     "3.69", "1.62", "1.620", "162e-2", "1.6", "9.8", "9.81f", "9.81F"],
)
def test_bodies_gravity_scan_catches_every_spelling_by_value(tmp_path, literal):
    plant(tmp_path, "sim.py", f"G = {literal.rstrip('fF')}\n")
    plant(tmp_path, "scene.ts", f"const gravity = [0, 0, -{literal}];\n")
    plant(tmp_path, "g.wgsl", f"const G: f32 = {literal if literal[-1] in 'fF' else literal + 'f'};\n")
    hits = scan_for_gravity_literals(tmp_path)
    assert {h.split(":")[0].rsplit("/", 1)[1] for h in hits} == {"sim.py", "scene.ts", "g.wgsl"}


@pytest.mark.parametrize(
    "name, text",
    [
        ("a.ts", 'class W { #g = 1; world = 9.81; }\n'),  # TS private field: `#` is not a comment
        ("b.ts", 'const c = "#ffffff"; const g = 9.81;\n'),  # a colour string before the number
        ("c.ts", 'const u = "https://example.org/a"; const g = 9.81;\n'),  # `//` inside a string
        ("d.ts", "/* note */ const g = 9.81;\n"),  # code after a block comment on the same line
        ("e.ts", "const g = `${9.81}`;\n"),  # a number inside a template-literal expression
        ("f.ts", "const s = `text ${a} more`; const g = 9.81;\n"),  # template text, then code
        ("g.ts", "const s = 'it\\'s'; const g = 9.81;\n"),  # escaped quote
        ("h.py", "half = n // 2; G = 9.81\n"),  # Python `//` is an operator
        ("i.py", 'name = "a # b"; G = 9.81\n'),  # `#` inside a Python string
        ("j.py", "x = f'{9.81:.2f}'\n" if False else "G = 9.806_65\n"),
        ("k.glsl", "#define GRAVITY 9.81\n"),  # GLSL preprocessor, not a comment
        ("l.wgsl", "const g = 9.81f;\n"),
        ("m.xml", '<option timestep="0.002" gravity="0 0 -9.81"/>\n'),  # MJCF
        ("n.json", '{"note": "9.81 in text", "gravity": [0, 0, -9.81]}\n'),
        ("o.html", '<div data-g="9.81"></div>\n'),
        ("q.ts", "const re = /[\"']/g; const g = 9.81;\n"),  # a quote inside a regex literal is not a string
        ("r.ts", "const t = a / b; const g = 9.81;\n"),  # division, not a regex
        ("s.ts", "const t = (a + b) / 2; const u = x / 3; const g = 9.81;\n"),  # two divisions on one line
        ("t.ts", "const parts = s.split(/\\/+/); const g = 9.81;\n"),  # escaped slash inside a regex
        ("u.ts", "if (/[/\"]/.test(s)) { g = 9.81; }\n"),  # `/` inside a character class, regex after `(`
        ("v.ts", "function f() { return /'/.test(s) ? 9.81 : 0; }\n"),  # regex after `return`
        ("w.ts", "/[\"']/.test(s); const g = 9.81;\n"),  # regex at the start of a line
        ("p.vue", '<!-- g = 1 --><script>const g = 9.81</script>\n'),
    ],
)
def test_bodies_gravity_scan_catches_the_forms_a_naive_scanner_misses(tmp_path, name, text):
    rel = plant(tmp_path, name, text)
    assert any(h.startswith(f"{rel}:1:") for h in scan_for_gravity_literals(tmp_path)), text


@pytest.mark.parametrize(
    "name, text",
    [
        ("a.ts", "// g = 9.81 on Earth\nconst x = 1;\n"),
        ("b.ts", "/* 9.81\n   3.73 */ const x = 1;\n"),
        ("c.ts", 'const label = "gravity 9.81 m/s2";\n'),
        ("d.ts", "const s = `g is 9.81 here`;\n"),
        ("e.ts", "const v1_62 = 19.81 + 3.9 + 21.62 + 5 + 100; const name9_81 = 2;\n"),
        ("f.py", '"""Docstring: g = 9.81."""\nx = 1  # 9.81\n'),
        ("g.py", "x = 'a' + '9.81'\nv = 19.81 + 3.9\n"),
        ("h.xml", '<!-- gravity="0 0 -9.81" --><body/>\n'),
        ("i.ts", "const lineHeight = 1.62; // gravity-scan: ok CSS line height, not a gravity\n"),
        ("j.py", "CELL_VOLTAGE = 3.7  # gravity-scan: ok battery cell volts\n"),
        ("l.json", '{"ref": "g = 9.81 on \\"Earth\\" 3.73"}\n'),
        ("m.ts", "const re = /9.81/g; const x = 1;\n"),  # a number inside a regex literal is not a literal
        ("k.ts", "const hex = 0x3f; const big = 1e10; const t = 2;\n"),
    ],
)
def test_bodies_gravity_scan_ignores_comments_strings_other_numbers_and_marked_lines(tmp_path, name, text):
    plant(tmp_path, name, text)
    assert scan_for_gravity_literals(tmp_path) == []


def test_bodies_gravity_scan_exemption_needs_a_reason_and_skips_tests_and_unparseable_python(tmp_path):
    plant(tmp_path, "a.ts", "const lineHeight = 1.62; // gravity-scan: ok\n")
    assert scan_for_gravity_literals(tmp_path) == ["packages/engine/src/a.ts:1: 1.62"]
    plant(tmp_path, "tests/t.py", "G = 9.81\n")  # SKIP_DIRS: tests are not engine or client code
    assert len(scan_for_gravity_literals(tmp_path)) == 1
    plant(tmp_path, "broken.py", "def (:\n  G = 9.81\n")
    assert any("broken.py: cannot be scanned" in h for h in scan_for_gravity_literals(tmp_path))
