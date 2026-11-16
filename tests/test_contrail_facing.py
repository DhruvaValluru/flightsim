"""Camera-facing contrail ribbon (LOOK_GENERATION 15): #13's contrails still read
as light beams under generation 14's view weight.

Looking along a trail from a chase camera, (a.v)^2 is ~0.8, so both strips of the
crossed ribbon kept a real weight and the edge-on one drew its whole profile in
a few pixels: a thin bright core line down the middle of the face-on strip.
A circular tube projects to the same chord from every azimuth about its axis, so
contrail_facing.hlsl turns strip 0 about the axis until its across direction is
cross(a, v) and folds strip 1 onto the axis; contrail_normal.hlsl gives the tube's
own world normal, so the sun side is lit and the far side sky-lit (no emissive).
-contrail-facing=off (Facing 0) is generation 14. BEAUTY ONLY.
"""
from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import aircraft_look as look  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_CPP = (BRIDGE / "Private" / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
FX_H = (BRIDGE / "Public" / "FlightSimAircraftFX.h").read_text(encoding="utf-8")
MASTERS = (REPO / "scripts" / "ue_aircraft_master_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / look.SHADER_DIR


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _len(a):
    return math.sqrt(_dot(a, a))


def _vertex(centre, along, strip, s, half_cm):
    """A crossed-ribbon vertex as RebuildTrail writes it."""
    up_n, side = look.contrail_strip_normals(look._norm(along))
    across = side if strip == 0 else up_n
    return _add(centre, tuple(c * half_cm * s for c in across))


def _moved(centre, along, strip, uv_y, half_cm, camera):
    p = _vertex(centre, along, strip, uv_y * 2.0 - 1.0, half_cm)
    return _add(p, look.contrail_facing_offset(uv_y, _sub(camera, p), along, strip, half_cm))


def test_strip0_faces_the_camera_from_every_view():
    """After the offset, strip 0 spans 2 x half width across the axis and its
    across direction is perpendicular to both the axis and the line to the camera."""
    rng = random.Random(15)
    for _ in range(200):
        along = look._norm((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-0.2, 0.2)))
        centre = (rng.uniform(-1e5, 1e5), rng.uniform(-1e5, 1e5), 1.0e6)
        camera = _add(centre, (rng.uniform(-3e4, 3e4), rng.uniform(-3e4, 3e4), rng.uniform(-5e3, 5e3)))
        half = rng.uniform(60.0, 1500.0)
        lo = _moved(centre, along, 0, 0.0, half, camera)
        hi = _moved(centre, along, 0, 1.0, half, camera)
        span = _sub(hi, lo)
        assert abs(_len(span) - 2.0 * half) < 1e-6 * half + 1e-6
        mid = tuple(0.5 * (a + b) for a, b in zip(lo, hi))
        assert _len(_sub(mid, centre)) < 1e-6 * half + 1e-6       # turned about the axis
        u = tuple(c / _len(span) for c in span)
        view = look._norm(_sub(camera, centre))
        assert abs(_dot(u, along)) < 1e-9
        assert abs(_dot(u, view)) < 1e-9


def test_strip1_folds_onto_the_axis_and_draws_nothing():
    along, centre, camera = (0.0, -1.0, 0.0), (0.0, 5e3, 1e6), (0.0, 1.1e4, 1.0012e6)
    for uv_y in (0.0, 0.3, 1.0):
        assert _len(_sub(_moved(centre, along, 1, uv_y, 600.0, camera), centre)) < 1e-6
    a = look.contrail_opacity((0.5, 0.5), (0.0, 5e3, 1e6), 0.1, 0.55, 0.006, 0.01, 0.6, 600.0,
                              camera_dir=(0, 0.98, 0.2), along=along, strip=1.0, view_weight=1.0, facing=1.0)
    assert a == 0.0


def test_facing_off_is_generation_14():
    assert look.contrail_facing_offset(0.9, (1e3, 2e3, 3e2), (1, 0, 0), 0, 700.0, facing=0.0) == (0.0, 0.0, 0.0)
    for strip in (0.0, 1.0):
        g14 = look.contrail_opacity((0.5, 0.4), (7e5, -3e5, 1e6), 0.3, 0.55, 0.006, 0.01, 0.6, 600.0,
                                    camera_dir=(0.1, 0.9, 0.4), along=(0, -1, 0), strip=strip, view_weight=1.0)
        off = look.contrail_opacity((0.5, 0.4), (7e5, -3e5, 1e6), 0.3, 0.55, 0.006, 0.01, 0.6, 600.0,
                                    camera_dir=(0.1, 0.9, 0.4), along=(0, -1, 0), strip=strip, view_weight=1.0,
                                    facing=0.0)
        assert g14 == off
    assert look.contrail_tube_normal(0.8, (0, 1, 0), (1, 0, 0), (0.0, 0.6, 0.8), facing=0.0) == \
        look._norm((0.0, 0.6, 0.8 + 1e-5))


def test_no_core_line_looking_along_the_trail():
    """#13's chase view: (a.v)^2 ~ 0.8. Generation 14 draws strip 1's whole profile
    in a band sqrt(1 - faceOn0) of the width; the facing ribbon has one chord
    profile, peak at the axis and monotone to the rim (no step, no second peak)."""
    along, view = (0.0, -1.0, 0.0), look._norm((0.25, 0.9, 0.35))
    w1 = look.contrail_view_weight(along, 1.0, view, 1.0)
    assert 0.1 < w1 < 0.9                     # the edge-on strip kept a real weight
    prof = [look.contrail_across(y, 0.05) for y in [0.5 + 0.025 * i for i in range(21)]]
    assert all(b <= a + 1e-12 for a, b in zip(prof, prof[1:]))
    assert prof[0] == max(prof)


def test_tube_normal_lit_side_and_shadow_side():
    """The normal is unit, faces the camera at the axis, lies along +-across at the
    rims, and a sun on one side lights that half (N.L > 0) and not the other."""
    along, view = (0.0, -1.0, 0.0), look._norm((0.0, 0.95, 0.31))
    n0 = look.contrail_tube_normal(0.5, view, along)
    assert abs(_len(n0) - 1.0) < 1e-9
    perp = look._norm(_sub(view, tuple(a * _dot(along, view) for a in along)))
    assert _dot(n0, perp) > 0.999
    across = look._norm((along[1] * view[2] - along[2] * view[1], along[2] * view[0] - along[0] * view[2],
                         along[0] * view[1] - along[1] * view[0]))
    assert _dot(look.contrail_tube_normal(1.0, view, along), across) > 0.999
    assert _dot(look.contrail_tube_normal(0.0, view, along), across) < -0.999
    sun = look._norm(tuple(1.0 * a + 0.2 * p for a, p in zip(across, perp)))
    lit = _dot(look.contrail_tube_normal(0.9, view, along), sun)
    dark = _dot(look.contrail_tube_normal(0.1, view, along), sun)
    assert lit > 0.7 and dark < -0.5


def test_shaders_material_and_switch_are_wired():
    assert look.SHADER_INPUTS["contrail_facing"] == ("UV", "ToCamera", "AlongXY", "AlongZStrip", "HalfCm", "Facing")
    assert look.SHADER_INPUTS["contrail_normal"] == ("UV", "CameraDir", "AlongXY", "AlongZStrip", "VertexNormal",
                                                     "Facing")
    assert look.SHADER_INPUTS["contrail_opacity"][-1] == "Facing"
    assert look.FX_PARAMETERS["M_AircraftContrail"][-1] == "Facing"
    for name in ("contrail_facing", "contrail_normal", "contrail_opacity"):
        body = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        assert not re.search(r"\b(for|while)\s*\(", body)
        assert "Texture" not in body and "Emissive" not in body
    assert re.search(r'^LOOK_GENERATION = "16"$', MASTERS, re.M)
    assert "MP_WORLD_POSITION_OFFSET" in MASTERS and "MP_NORMAL" in MASTERS
    assert 'set_editor_property("tangent_space_normal", False)' in MASTERS
    assert 'TEXT("contrail-facing="), true' in FX_CPP
    assert "AircraftFxParamFacing" in FX_CPP and "UV3.Add(FVector2D(HalfCm, 0.0));" in FX_CPP
    assert "UV0, UV1, UV2, UV3," in FX_CPP
    assert "bool bContrailFacing = true;" in FX_H
