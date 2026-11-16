"""Contrail view weight (LOOK_GENERATION 14): #13's four bright diagonal streaks
that read as light beams.

A trail is a CROSSED ribbon (two strips at right angles through every sample).
From a chase camera looking along the trail, one strip is nearly edge-on and its
whole across profile collapses into a hard full-opacity line down the middle of
the face-on strip: a bright beam core. A circular cylinder projects to the same
chord from every azimuth about its axis, so contrail_opacity.hlsl now weights
each strip by (n.v)^2 / (1 - (a.v)^2); with n0, n1, a orthonormal the two weights
sum to exactly 1 at every view. -contrail-view-weight=off (ViewWeight 0) is
generation 13. BEAUTY ONLY: the trails are BeautyOnlyActors and no label or
measure path is touched.
"""
from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import aircraft_look as look  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_CPP = BRIDGE / "Private" / "FlightSimAircraftFX.cpp"
FX_H = BRIDGE / "Public" / "FlightSimAircraftFX.h"
MASTERS = REPO / "scripts" / "ue_aircraft_master_materials.py"
SHADER = REPO / look.SHADER_DIR / "contrail_opacity.hlsl"

CRUISE_CM = (7.0e5, -3.2e5, 1.05e6)
CELL_CM = 100.0 * look.CONTRAIL_DEFAULTS["PuffCellM"]


def _read(path):
    return path.read_text(encoding="utf-8")


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _random_unit(rng):
    while True:
        v = tuple(rng.uniform(-1.0, 1.0) for _ in range(3))
        n = math.sqrt(sum(c * c for c in v))
        if 0.1 < n <= 1.0:
            return tuple(c / n for c in v)


# -- the geometry, in numbers ----------------------------------------------------------

def test_the_two_strip_weights_sum_to_one_at_every_view():
    rng = random.Random(1307)
    for _ in range(2000):
        along = _random_unit(rng)
        if abs(along[2]) > 0.99:
            continue
        view = _random_unit(rng)
        w0 = look.contrail_view_weight(along, 0.0, view)
        w1 = look.contrail_view_weight(along, 1.0, view)
        assert 0.0 <= w0 <= 1.0 and 0.0 <= w1 <= 1.0
        assert abs(w0 + w1 - 1.0) < 1e-9, (along, view, w0, w1)


def test_the_strip_normals_are_orthonormal_with_the_axis_as_the_cpp_builds_them():
    rng = random.Random(7)
    for _ in range(200):
        along = _random_unit(rng)
        if abs(along[2]) > 0.99:
            continue
        up_n, side = look.contrail_strip_normals(along)
        for a, b in ((up_n, side), (up_n, along), (side, along)):
            assert abs(sum(x * y for x, y in zip(a, b))) < 1e-9
        assert abs(sum(c * c for c in up_n) - 1.0) < 1e-9 and abs(sum(c * c for c in side) - 1.0) < 1e-9
        assert side[2] == 0.0 and up_n[2] > 0.0       # Side horizontal, Up leans up (cross(Side, a))
    # a vertical axis falls back to RightVector, as GetSafeNormal does in the C++
    assert look.contrail_strip_normals((0.0, 0.0, 1.0))[1] == (0.0, 1.0, 0.0)


def test_the_chase_view_fades_the_edge_on_strip_and_keeps_the_face_on_one():
    # #13: a trail running along +X; the chase camera 110 m behind and 12 m
    # above the trail plane, looking at a point 60 m up the trail.
    along = (1.0, 0.0, 0.0)
    to_camera = _unit((-(110.0 - 60.0), 0.0, 12.0))    # pixel -> camera
    horizontal = look.contrail_view_weight(along, 0.0, to_camera)   # plane normal Up: seen from above
    vertical = look.contrail_view_weight(along, 1.0, to_camera)     # plane normal Side: edge-on
    assert abs(horizontal - 1.0) < 1e-12 and vertical < 1e-12
    # from beside the trail the vertical strip is the face-on one
    beside = _unit((0.2, -1.0, 0.0))
    assert abs(look.contrail_view_weight(along, 1.0, beside) - 1.0) < 1e-12
    assert look.contrail_view_weight(along, 0.0, beside) < 1e-12
    # 45 deg between the strips: half each
    diag = _unit((0.0, 1.0, 1.0))
    assert abs(look.contrail_view_weight(along, 0.0, diag) - 0.5) < 1e-12
    # straight down the axis the split is undefined: 0.5 each, never 0/0
    assert look.contrail_view_weight(along, 0.0, (-1.0, 0.0, 0.0)) == 0.5
    assert look.contrail_view_weight(along, 1.0, (1.0, 0.0, 0.0)) == 0.5
    # the sign of the view line does not matter (CameraVectorWS points to the camera)
    assert look.contrail_view_weight(along, 0.0, to_camera) == look.contrail_view_weight(
        along, 0.0, tuple(-c for c in to_camera))


def test_the_beam_core_is_gone_and_the_face_on_profile_is_untouched():
    # Old (ViewWeight 0): an edge-on strip projects its PEAK opacity onto the axis,
    # composited over the face-on strip's peak -> the core is 1 - (1 - a)^2, brighter
    # than either strip: the light-beam line. New: the edge-on strip's weight is 0.
    along = (1.0, 0.0, 0.0)
    to_camera = _unit((-50.0, 0.0, 12.0))
    args = ((0.02, 0.5), CRUISE_CM, 0.01, 0.55, 0.0, 0.04, 0.0, CELL_CM)
    face_old = look.contrail_opacity(*args, camera_dir=to_camera, along=along, strip=0.0, view_weight=0.0)
    edge_old = look.contrail_opacity(*args, camera_dir=to_camera, along=along, strip=1.0, view_weight=0.0)
    face_new = look.contrail_opacity(*args, camera_dir=to_camera, along=along, strip=0.0, view_weight=1.0)
    edge_new = look.contrail_opacity(*args, camera_dir=to_camera, along=along, strip=1.0, view_weight=1.0)
    core_old = 1.0 - (1.0 - face_old) * (1.0 - edge_old)
    core_new = 1.0 - (1.0 - face_new) * (1.0 - edge_new)
    assert edge_old == face_old > 0.2                 # the edge-on line is as dense as the face peak
    assert core_old > 1.5 * face_old                  # the doubled core
    assert edge_new < 1e-12 and abs(face_new - face_old) < 1e-12   # the face-on strip is generation 13's
    assert abs(core_new - face_old) < 1e-12


def test_view_weight_off_is_generation_13_byte_for_byte_in_the_twin():
    rng = random.Random(99)
    for _ in range(300):
        uv = (rng.uniform(0.0, 1.0), rng.uniform(0.0, 1.0))
        life = rng.uniform(0.0, 1.0)
        base = look.contrail_opacity(uv, CRUISE_CM, life, 0.55, 0.006, 0.01, 0.6, CELL_CM)
        off = look.contrail_opacity(uv, CRUISE_CM, life, 0.55, 0.006, 0.01, 0.6, CELL_CM,
                                    camera_dir=_random_unit(rng), along=_random_unit(rng),
                                    strip=float(rng.randint(0, 1)), view_weight=0.0)
        assert off == base


# -- the shader, the master and the C++ --------------------------------------------------

def test_the_shader_weights_each_strip_and_rebuilds_the_cpp_normals():
    shader = _read(SHADER)
    documented = re.findall(r"^//\s{2,}(\w+)\s+float", shader, re.M)
    assert tuple(documented) == look.SHADER_INPUTS["contrail_opacity"]
    assert look.SHADER_INPUTS["contrail_opacity"][-5:] == ("CameraDir", "AlongXY", "AlongZStrip", "ViewWeight",
                                                           "Facing")
    for line in ("float3 axis = float3(AlongXY, AlongZStrip.x);",
                 "float3 side = cross(axis, float3(0.0, 0.0, 1.0));",
                 "side = length(side) > 1.0e-4 ? side / length(side) : float3(0.0, 1.0, 0.0);",
                 "float3 upN = cross(side, axis);",
                 "float3 plane = AlongZStrip.y < 0.5 ? upN : side;",
                 "float offAxis = 1.0 - av * av;",
                 "float faceOn = offAxis > 1.0e-3 ? saturate(nv * nv / offAxis) : 0.5;",
                 "float view = lerp(1.0, faceOn, saturate(ViewWeight));",
                 "return saturate(Opacity * formed * fade * across * lumpy * view);"):
        assert line in shader, line
    assert not re.search(r"\b(for|while)\s*\(", shader)
    # cheap: no texture fetch added (iGPU, D3D11 SM5)
    assert "Texture" not in shader and "Sample(" not in shader


def test_the_master_reads_the_view_line_and_uv1_uv2_and_defaults_to_generation_13():
    masters = _read(MASTERS)
    assert re.search(r'^LOOK_GENERATION = "17"$', masters, re.M)
    body = masters[masters.index("def create_aircraft_contrail"):]
    body = body[:body.index("\ndef ", 10)]
    # LOOK_GENERATION 15 shares the view line and UV1/UV2 nodes with the facing pair.
    assert "camera_dir = _node(material, unreal.MaterialExpressionCameraVectorWS" in body
    assert "along_xy = _uv_channel(material, 1," in body
    assert "along_z_strip = _uv_channel(material, 2," in body
    assert '"CameraDir": (camera_dir, "")' in body and '"AlongXY": (along_xy, "")' in body
    assert '"AlongZStrip": (along_z_strip, "")' in body
    assert '"ViewWeight": (_scalar(material, view_name, 0.0,' in body
    assert look.FX_PARAMETERS["M_AircraftContrail"][-2] == "ViewWeight"


def test_the_cpp_writes_the_axis_and_strip_and_sets_the_switch():
    text = _read(FX_CPP)
    body = text[text.index("void FFlightSimAircraftFX::RebuildTrail"):text.index("void FFlightSimAircraftFX::Advance")]
    assert "UV1.Add(FVector2D(Along.X, Along.Y));" in body
    assert "UV2.Add(FVector2D(Along.Z, static_cast<double>(Strip)));" in body
    # the strip index matches the shader's: strip 0's normal is Up, strip 1's is Side
    assert "const FVector Normal = Strip == 0 ? Up : Side;" in body
    assert "FVector::CrossProduct(Along, FVector::UpVector)" in body
    assert "FVector::CrossProduct(Side, Along)" in body
    # the actor is only translated (local axis == world axis for UV1/UV2)
    assert "Trail.Owner->SetActorLocation(Anchor);" in body and "SetActorRotation" not in body
    assert 'AircraftFxSwitch(Params, TEXT("contrail-view-weight="), true, SwitchError)' in text
    assert "bContrailViewWeight = bAll && bViewWeightSwitch;" in text
    assert "Options.bContrailViewWeight ? 1.0f : 0.0f" in text
    assert 'TEXT("ViewWeight")' in text
    assert 'SetBoolField(TEXT("view_weight_on"), Options.bContrailViewWeight)' in text
    assert "bool bContrailViewWeight = true;" in _read(FX_H)
    assert ("contrail-view-weight=", True) in look.FX_SWITCHES
    assert look.parse_fx_switches("")["contrail-view-weight"] is True
    assert look.parse_fx_switches("-contrail-view-weight=off")["contrail-view-weight"] is False
    assert look.parse_fx_switches("-aircraft-look=off")["contrail-view-weight"] is False


def test_the_trails_stay_beauty_only():
    text = _read(FX_CPP)
    assert "BeautyOnlyActors.Add(Trail.Owner);" in text
