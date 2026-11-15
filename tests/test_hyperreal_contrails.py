"""Hyperreal contrails (LOOK_GENERATION 13): #13's four bright runway stripes.

The 747 at cruise drew its contrails as four solid lines of one width and one
brightness because (a) RebuildTrail's width was StartWidthM + SpreadMPerS x age,
1.2 m growing to 1.6 m over the 110 m a chase frame shows, (b) the shader's
across profile was a flat tent, its one lump pattern sat in the position
RELATIVE to the newest sample (it slid with the aircraft), and nothing in it
changed with age, and (c) the material was lit Volumetric NonDirectional on flat
normals: no sun side. These tests pin the fix in all three places and the
Python twins of the C++ formulas. BEAUTY ONLY: the FX is in BeautyOnlyActors;
no label or measure path is touched (tests/test_beauty_label_isolation.py).
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

import aircraft_look as look  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_CPP = BRIDGE / "Private" / "FlightSimAircraftFX.cpp"
FX_H = BRIDGE / "Public" / "FlightSimAircraftFX.h"
COND_CPP = BRIDGE / "Private" / "FlightSimCondensation.cpp"
COND_H = BRIDGE / "Public" / "FlightSimCondensation.h"
MASTERS = REPO / "scripts" / "ue_aircraft_master_materials.py"
SHADER = REPO / look.SHADER_DIR / "contrail_opacity.hlsl"
COND_SHADER = REPO / look.SHADER_DIR / "condensation_opacity.hlsl"
API = REPO / "scripts" / "check_bridge_api.sh"


def _read(path):
    return path.read_text(encoding="utf-8")


def _contrail_body():
    masters = _read(MASTERS)
    start = masters.index("def create_aircraft_contrail")
    return masters[start:masters.index("\ndef ", start + 10)]


# -- the material and its stamp ---------------------------------------------------

def test_generation_13_rebuilds_the_contrail_master():
    assert re.search(r'^LOOK_GENERATION = "13"$', _read(MASTERS), re.M)
    assert look.FX_PARAMETERS["M_AircraftContrail"] == ("Opacity", "Formation", "FormationRamp", "Puff")
    assert look.SHADER_INPUTS["contrail_opacity"] == (
        "UV", "WorldPos", "Life", "Opacity", "Formation", "FormationRamp", "Puff", "PuffCellCm")


def test_the_contrail_material_reads_world_position_vertex_life_and_is_lit_directionally():
    body = _contrail_body()
    assert "MaterialExpressionWorldPosition" in body
    assert "MaterialExpressionLocalPosition" not in body   # generation 12's sliding lumps
    assert 'unreal.MaterialExpressionVertexColor, -900, 150), "r"' in body
    assert '"TLM_VOLUMETRIC_DIRECTIONAL"' in body
    assert '"TLM_VOLUMETRIC_NON_DIRECTIONAL"' in body      # the fallback stays
    assert body.index("TLM_VOLUMETRIC_DIRECTIONAL") < body.index("TLM_VOLUMETRIC_NON_DIRECTIONAL")
    assert '"Puff": (_scalar(material, puff_name, look.CONTRAIL_DEFAULTS["PuffBreakup"]' in body
    assert '"PuffCellCm": (_scalar(material, "PuffCellCm", 100.0 * look.CONTRAIL_DEFAULTS["PuffCellM"]' in body
    # round 93's camera fade stays in front of it
    assert "MaterialExpressionPixelDepth" in body and "_saturate(material, ramp" in body
    # the condensation master is built from the same stamp, so it rebuilds too
    assert "M_AircraftCondensation" in _read(MASTERS)


# -- the shader ----------------------------------------------------------------------

def test_the_shader_is_a_tube_with_fixed_cell_world_space_puffs_blended_by_age():
    shader = _read(SHADER)
    documented = re.findall(r"^//\s{2,}(\w+)\s+float", shader, re.M)
    assert tuple(documented) == look.SHADER_INPUTS["contrail_opacity"]
    # round 47's formation ramp is untouched
    assert "float ramp = FormationRamp > 0.0 ? FormationRamp : 0.04;" in shader
    assert "float formed = smoothstep(Formation, Formation + ramp, UV.x);" in shader
    # the chord of a cylinder across, raised to a power with a rim softening on top;
    # never a smoothstep OF the chord (the review's flat-topped box)
    assert "float chord = sqrt(saturate(1.0 - x * x));" in shader
    assert "float acrossPower = lerp(1.0, 2.0, life);" in shader
    assert "float rim = lerp(0.25, 0.6, life);" in shader
    assert "float across = pow(max(chord, 1.0e-4), acrossPower) * smoothstep(0.0, rim, chord);" in shader
    assert "smoothstep(0.0, soft, chord)" not in shader
    # world-space value noise with FIXED cells per octave: nothing scales the lattice
    # about the world origin by Life (the review's shimmer)
    assert "float cell0 = max(PuffCellCm, 50.0);" in shader
    assert "float3 p = WorldPos / cell0;" in shader
    assert "float3 p2 = WorldPos / (cell0 * 0.37) + float3(17.0, 29.0, 43.0);" in shader
    assert "float3 p3 = WorldPos / (cell0 * 5.0) + float3(5.0, 11.0, 23.0);" in shader
    assert "(1.0 + 4.0 * life)" not in shader and "cellCm" not in shader
    assert "float wDetail = lerp(0.35, 0.15, life);" in shader
    assert "float wBody = lerp(0.65, 0.35, life);" in shader
    assert "float wCoarse = lerp(0.0, 0.5, life);" in shader
    assert "float n = wBody * n1 + wDetail * n2 + wCoarse * n3;" in shader
    # every corner wrapped AFTER its +1 offset (cA low, cB high), never the base cell alone
    for lo, hi, c in (("cA", "cB", "cell"), ("dA", "dB", "cell2"), ("eA", "eB", "cell3")):
        assert f"float3 {lo} = {c} - 512.0 * floor({c} / 512.0);" in shader
        assert f"float3 {hi} = ({c} + 1.0) - 512.0 * floor(({c} + 1.0) / 512.0);" in shader
    assert "fmod(" not in shader
    assert not re.search(r"float3\(\s*[01]\s*,\s*[01]\s*,\s*[01]\s*\)", shader)   # no post-wrap +1 corners
    assert "LocalPos" not in shader
    # the break-up: the cut rises with life; Puff 0 is generation 12's even lumpiness
    assert "float cut = saturate(Puff) * smoothstep(0.1, 1.0, life) * 0.75;" in shader
    assert "float lumpy = lerp(0.7 + 0.3 * n, 0.25 + 0.75 * puffs, saturate(Puff));" in shader
    assert "return saturate(Opacity * formed * fade * across * lumpy);" in shader
    # bounded: no loops
    assert not re.search(r"\b(for|while)\s*\(", shader)
    # the twin's constants are the shader's
    assert look.CONTRAIL_NOISE_OCTAVES == ((1.0, (0.0, 0.0, 0.0)), (0.37, (17.0, 29.0, 43.0)), (5.0, (5.0, 11.0, 23.0)))
    assert look.CONTRAIL_NOISE_WRAP == 512.0 and look.CONTRAIL_NOISE_MIN_CELL_CM == 50.0
    assert look.CONTRAIL_ACROSS_POWER == (1.0, 2.0) and look.CONTRAIL_ACROSS_RIM == (0.25, 0.6)


def test_the_tip_vortex_ribbon_takes_the_chord_profile_and_keeps_its_inputs():
    shader = _read(COND_SHADER)
    import aircraft_condensation_material as m
    assert tuple(re.findall(r"^//\s{2,}(\w+)\s+float", shader, re.M)) == m.SHADER_INPUTS
    ribbon = shader[shader.index("if (Shape < 0.5)"):shader.index("else if (Shape < 1.5)")]
    assert "float chord = sqrt(saturate(1.0 - x * x));" in ribbon
    assert ("float across = pow(max(chord, 1.0e-4), lerp(1.0, 2.0, age)) * smoothstep(0.0, lerp(0.25, 0.6, age), chord);"
            in ribbon)
    assert "float age = saturate(UV.x);" in ribbon
    assert "smoothstep(0.0, lerp(0.5, 1.0, saturate(UV.x)), chord)" not in ribbon   # the flat-topped box
    # the ribbon's profile is the contrail twin's (UV.x the age), so the same numbers hold
    for age in (0.02, 0.5, 1.0):
        for v in (0.1, 0.3, 0.5, 0.75, 0.9):
            x = abs(v * 2.0 - 1.0)
            chord = math.sqrt(max(1.0 - x * x, 0.0))
            t = min(max(chord / (0.25 + 0.35 * age), 0.0), 1.0)
            expected = max(chord, 1.0e-4) ** (1.0 + age) * t * t * (3.0 - 2.0 * t)
            assert look.contrail_across(v, age) == pytest.approx(expected)


# -- the shader's numbers (the twin) ---------------------------------------------------

CRUISE_CM = (7.2e5, -3.1e5, 1.1e6)      # 7 km out, 11 km up: a 747's cruise in world cm
CELL_CM = 100.0 * look.CONTRAIL_DEFAULTS["PuffCellM"]


def _old_sweeping_noise(world_cm, life, cell_cm):
    """The review's defect for reference: the lattice scaled about the WORLD
    ORIGIN by (1 + 4 Life). Not the shader; here to show the test discriminates."""
    scale = max(cell_cm, 50.0) * (1.0 + 4.0 * life)
    return (0.65 * look.contrail_value_noise([v / scale for v in world_cm])
            + 0.35 * look.contrail_value_noise([v / (scale * 0.37) + o for v, o in zip(world_cm, (17.0, 29.0, 43.0))]))


def test_a_fixed_world_point_keeps_its_noise_over_a_tenth_of_a_second():
    # a 25 s trail ages 0.004 of Life in 0.1 s; a 240 s persistent one 0.0004
    for lifetime in (look.CONTRAIL_DEFAULTS["LifetimeS"], look.CONTRAIL_DEFAULTS["PersistentLifetimeS"]):
        step = 0.1 / lifetime
        for life in (0.02, 0.3, 0.6, 0.95):
            for point in (CRUISE_CM, (1.0e4, 2.0e4, 3.0e5), (-4.9e6, 2.2e6, 9.5e5)):
                before = look.contrail_puff_noise(point, life, CELL_CM)
                after = look.contrail_puff_noise(point, life + step, CELL_CM)
                # only the blend weights move: |dn| <= |dweights| x |n_a - n_b| < 0.5 step
                assert abs(after - before) <= 0.5 * step + 1e-9, (lifetime, life, point)
                assert abs(after - before) < 0.003
    # the full opacity at a fixed point moves only by the slow fade and blend
    uv = (0.5, 0.5)
    for life in (0.1, 0.5):
        a = look.contrail_opacity(uv, CRUISE_CM, life, 1.0, 0.0, 0.04, 0.6, CELL_CM)
        b = look.contrail_opacity(uv, CRUISE_CM, life + 0.004, 1.0, 0.0, 0.04, 0.6, CELL_CM)
        assert a > 0.0 and abs(a - b) < 0.02
    # and the review's origin-scaled lattice re-rolled the lump in that same 0.1 s
    swept = max(abs(_old_sweeping_noise(CRUISE_CM, life, CELL_CM) - _old_sweeping_noise(CRUISE_CM, life + 0.004, CELL_CM))
                for life in (0.1, 0.3, 0.6))
    assert swept > 0.05


def _old_base_wrapped_noise(p):
    """The review's seam for reference: the base cell wrapped, the +1 corners
    added after. Not the shader; here to show the test discriminates."""
    cell = [math.floor(v) for v in p]
    f = [v - c for v, c in zip(p, cell)]
    f = [t * t * (3.0 - 2.0 * t) for t in f]
    base = [(c + 4096.0) % 512.0 for c in cell]
    h = {(ix, iy, iz): look._contrail_hash(base[0] + ix, base[1] + iy, base[2] + iz)
         for ix in (0, 1) for iy in (0, 1) for iz in (0, 1)}
    x0 = look._lerp(look._lerp(h[0, 0, 0], h[1, 0, 0], f[0]), look._lerp(h[0, 1, 0], h[1, 1, 0], f[0]), f[1])
    x1 = look._lerp(look._lerp(h[0, 0, 1], h[1, 0, 1], f[0]), look._lerp(h[0, 1, 1], h[1, 1, 1], f[0]), f[1])
    return look._lerp(x0, x1, f[2])


def test_the_value_noise_has_no_seam_at_the_wrap_boundary():
    wrap = look.CONTRAIL_NOISE_WRAP
    # a trilinear octave's steepest slope is 1.5 per cell (the smoothstep's), so a
    # 0.002 cell step moves it under 0.003 anywhere, boundary or not
    h = 0.002
    for axis in range(3):
        for boundary in (wrap, 2.0 * wrap, -wrap, 7.0 * wrap):
            for other in (0.3, 511.7, 1023.45):
                p = [other, other * 0.7 + 3.0, other * 1.3 + 1.0]
                p[axis] = boundary - h
                before = look.contrail_value_noise(p)
                p[axis] = boundary + h
                after = look.contrail_value_noise(p)
                assert abs(after - before) < 0.003 * 2.0, (axis, boundary, other)
                # the shared corner hashes agree from both sides: the limit values match
                p[axis] = boundary - 1e-7
                p_lo = look.contrail_value_noise(p)
                p[axis] = boundary
                assert look.contrail_value_noise(p) == pytest.approx(p_lo, abs=1e-5)
    # the three octaves' world-space wrap positions, in cm, are seam-free too
    cell0 = CELL_CM
    for scale, offset in look.CONTRAIL_NOISE_OCTAVES:
        for axis in range(3):
            world = [1234.5, 876.0, 5432.1]
            world[axis] = (wrap - offset[axis]) * cell0 * scale
            lo, hi = list(world), list(world)
            lo[axis] -= 0.5
            hi[axis] += 0.5
            assert abs(look.contrail_puff_noise(hi, 0.4, cell0) - look.contrail_puff_noise(lo, 0.4, cell0)) < 0.005
    # the review's base-only wrap jumps at the boundary (the test discriminates)
    jumps = []
    for other in (0.3, 511.7, 1023.45, 200.2, 77.7):
        p = [other, other * 0.7 + 3.0, other * 1.3 + 1.0]
        p[0] = wrap - h
        a = _old_base_wrapped_noise(p)
        p[0] = wrap + h
        jumps.append(abs(_old_base_wrapped_noise(p) - a))
    assert max(jumps) > 0.05


def test_the_young_trail_profile_is_not_flat_and_the_old_one_is_softer():
    ys = [i / 200.0 for i in range(1, 200)]
    young = [look.contrail_across(y, 0.02) for y in ys]
    peak = max(young)
    assert young[99] == pytest.approx(peak)                      # thickest through the axis
    # it varies over the WHOLE width: strictly decreasing from the axis outwards
    outward = young[99:]
    assert all(b < a for a, b in zip(outward, outward[1:]))
    # the review's smoothstep(0, 0.46, chord) sat within 1 % of its peak over 89 % of
    # the width; the chord profile is that flat over well under a quarter of it
    near_peak = sum(1 for v in young if v > 0.99 * peak) / len(young)
    assert near_peak < 0.25
    # and it has come well down by a quarter of the way out (the flat top had not)
    assert young[149] < 0.9 * peak and young[179] < 0.65 * peak
    # the body is a chord at youth: half a radius out it is sqrt(0.75)^1.02
    assert look.contrail_across(0.75, 0.02) == pytest.approx(math.sqrt(0.75) ** 1.02, rel=1e-6)
    # nothing at the rim, at every age
    for life in (0.0, 0.5, 1.0):
        assert look.contrail_across(0.0, life) == 0.0 and look.contrail_across(1.0, life) == 0.0
        assert look.contrail_across(0.5, life) == pytest.approx(1.0)
    # an old trail is softer still everywhere off the axis (a parabola with a wide rim)
    old = [look.contrail_across(y, 1.0) for y in ys]
    assert all(o <= y_ + 1e-12 for o, y_ in zip(old, young))
    assert old[149] < young[149] and old[189] < 0.5 * young[189]
    # the across profile is the whole-opacity's shape too
    o = [look.contrail_opacity((0.5, y), CRUISE_CM, 0.02, 1.0, 0.0, 0.04, 0.0, CELL_CM) for y in (0.5, 0.75, 0.9)]
    assert o[0] > o[1] > o[2] > 0.0


# -- the C++ -------------------------------------------------------------------------

def test_the_ribbon_widens_by_the_jet_model_rolls_up_sinks_and_carries_life():
    text = _read(FX_CPP)
    body = text[text.index("void FFlightSimAircraftFX::RebuildTrail"):text.index("void FFlightSimAircraftFX::Advance")]
    assert "const FTrailShape& Shape)" in body
    assert ("Shape.JetSpreadM * (1.0 - FMath::Exp(-Age / FMath::Max(Shape.JetMixS, 0.001)))" in body)
    assert "+ Shape.SpreadMPerS * Age;" in body
    assert "Lateral = Trail.VortexOffsetM * T * T * (3.0 - 2.0 * T);" in body
    assert "const double Sink = Shape.WakeSinkMPerS * Age;" in body
    assert "S.RightWorld * (Lateral * AircraftFxCmPerMetre)" in body
    # each sample expires by its own lifetime (the persistence gate)
    assert "NowS - S.TimeS > FMath::Max(S.LifetimeS, 0.01)" in body
    # the half-cylinder normals: a sun side and a shadow side
    assert "Normals.Add((Normal - Across).GetSafeNormal(UE_SMALL_NUMBER, Normal));" in body
    assert "Normals.Add((Normal + Across).GetSafeNormal(UE_SMALL_NUMBER, Normal));" in body
    # vertex colour R = Life; UV.x stays the formation clock
    assert "const FLinearColor Colour(Life, 1.0f, 1.0f, 1.0f);" in body
    assert "const double U = Age / FMath::Max(LifetimeS, 0.01);" in body
    assert "CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, Colours, {}, false);" in body
    header = _read(FX_H)
    assert "FVector RightWorld = FVector::RightVector;" in header
    assert "double LifetimeS = 25.0;" in header
    assert "double VortexOffsetM = 0.0;" in header
    assert "struct FTrailShape" in header


def test_the_semi_span_comes_from_the_nav_lamps_and_the_vortex_core_sits_at_the_fraction():
    text = _read(FX_CPP)
    assert "SemiSpanCm = FMath::Max(SemiSpanCm, FMath::Abs(Lamp.ActorCm.Y));" in text
    assert 'Constant(TEXT("contrail"), TEXT("VortexSpanFraction"), 0.785) * SemiSpanCm' in text
    assert "Trail.VortexOffsetM = CoreYM - NozzleYM;" in text
    # vapour trails keep generation 12's shape: no jet spread, no roll-up, no sink
    advance = text[text.index("void FFlightSimAircraftFX::Advance"):]
    assert "if (!Trail.bVapour)\n\t\t{\n\t\t\tShape.JetSpreadM" in advance
    for name, value in (("JetSpreadM", "10.0"), ("JetMixS", "1.5"), ("VortexRollupS", "12.0"),
                        ("WakeSinkMPerS", "1.5")):
        assert f'Constant(TEXT("contrail"), TEXT("{name}"), {value})' in advance, name


def test_the_persistence_gate_is_the_stated_physics_and_off_without_humidity():
    text = _read(FX_CPP)
    assert "double AircraftFxIceOverWaterSaturation(double TemperatureK)" in text
    assert "constexpr double AircraftFxMagnusWaterB = 17.62;" in text
    assert "constexpr double AircraftFxMagnusWaterC = 243.12;" in text
    assert f"constexpr double AircraftFxMagnusIceB = {look.MAGNUS_ICE_B};" in text
    assert f"constexpr double AircraftFxMagnusIceC = {look.MAGNUS_ICE_C};" in text
    advance = text[text.index("void FFlightSimAircraftFX::Advance"):]
    assert "if (Condensation.HasHumidity())" in advance
    assert "Condensation.RelativeHumidityPct() * AircraftFxIceOverWaterSaturation(TemperatureK)" in advance
    assert 'Constant(TEXT("contrail"), TEXT("PersistenceRhiOnsetPct"), 100.0)' in advance
    assert 'Constant(TEXT("contrail"), TEXT("PersistenceRhiSpanPct"), 20.0)' in advance
    assert 'Constant(TEXT("contrail"), TEXT("PersistentLifetimeS"), 240.0)' in advance
    assert "Sample.LifetimeS = SampleLifetime;" in advance and "Seed.LifetimeS = SampleLifetime;" in advance
    # the condensation module exposes the RH it used; it reads nothing new
    assert "double RelativeHumidityPct() const { return RhNow; }" in _read(COND_H)
    assert "RhNow = bHumidityNow ? Rh : 0.0;" in _read(COND_CPP)
    # recorded
    for key in ("width_model", "wake_rollup", "puffs_on", "lighting", "persistence", "rhi_pct",
                "lifetime_now_s", "persistent_frames"):
        assert f'TEXT("{key}")' in text, key


def test_the_puff_switch_is_parsed_by_both_twins():
    assert ("contrail-puffs=", True) in look.FX_SWITCHES
    assert look.parse_fx_switches("")["contrail-puffs"] is True
    assert look.parse_fx_switches("-contrail-puffs=off")["contrail-puffs"] is False
    text = _read(FX_CPP)
    assert 'AircraftFxSwitch(Params, TEXT("contrail-puffs="), true, SwitchError)' in text
    assert "bContrailPuffs = bAll && bPuffsSwitch;" in text
    assert '? Constant(TEXT("contrail"), TEXT("PuffBreakup"), 0.6) : 0.0;' in text
    assert "SetScalarParameterValue(FName(AircraftFxParamPuff)" in text
    assert "bool bContrailPuffs = true;" in _read(FX_H)


def test_the_engine_symbols_the_lane_uses_are_in_the_api_check():
    api = _read(API)
    for label in ("contrail: TLM_VolumetricDirectional", "contrail: UMaterialExpressionWorldPosition",
                  "contrail: UMaterialExpressionVertexColor", "contrail: FMath Exp double",
                  "contrail: FLinearColor(float, float, float, float)"):
        assert f'aircraft_check "{label}"' in api, label


# -- the twins -----------------------------------------------------------------------

def test_the_width_twin_starts_thin_and_widens_fast_then_slowly():
    w0 = look.contrail_width_m(0.0)
    assert w0 == look.CONTRAIL_DEFAULTS["StartWidthM"]
    # a chase frame's 110 m at 250 m/s (0.44 s): already several metres, not 1.6
    assert 4.0 < look.contrail_width_m(0.44) < 6.0
    # the jet regime saturates: the widening rate over 2..5 s is well under the first 0.44 s's
    early = (look.contrail_width_m(0.44) - w0) / 0.44
    late = (look.contrail_width_m(5.0) - look.contrail_width_m(2.0)) / 3.0
    assert late < 0.4 * early
    ages = [0.0, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, 240.0]
    widths = [look.contrail_width_m(a) for a in ages]
    assert widths == sorted(widths)
    # generation 12's law is the SpreadMPerS term alone
    c = dict(look.CONTRAIL_DEFAULTS, JetSpreadM=0.0)
    assert look.contrail_width_m(10.0, c) == pytest.approx(1.2 + 0.9 * 10.0)


def test_the_wake_twin_rolls_each_plume_to_its_side_and_sinks():
    semi = 32.0  # a 747's ~64 m span
    lat_in, sink = look.contrail_wake_offset_m(1e9, 11.7, semi)
    lat_out, _ = look.contrail_wake_offset_m(1e9, 20.8, semi)
    core = 0.785 * semi
    assert lat_in == pytest.approx(core - 11.7) and lat_out == pytest.approx(core - 20.8)
    # the left engines go left
    lat_left, _ = look.contrail_wake_offset_m(1e9, -11.7, semi)
    assert lat_left == pytest.approx(-(core - 11.7))
    # nothing at birth, half-way by half the roll-up time, monotonic
    assert look.contrail_wake_offset_m(0.0, 11.7, semi) == (0.0, 0.0)
    half, _ = look.contrail_wake_offset_m(6.0, 11.7, semi)
    assert half == pytest.approx(0.5 * (core - 11.7))
    assert sink > 0.0 and look.contrail_wake_offset_m(10.0, 11.7, semi)[1] == pytest.approx(15.0)
    # no measured span: no roll-up
    assert look.contrail_wake_offset_m(100.0, 11.7, 0.0)[0] == 0.0


def test_the_persistence_twin_is_off_without_humidity_and_on_in_ice_supersaturation():
    assert look.ice_over_water_saturation_ratio(223.15) == pytest.approx(1.62, abs=0.02)
    assert look.ice_over_water_saturation_ratio(273.15) == pytest.approx(1.0)
    assert look.contrail_persistence(None, 223.15) == (0.0, 0.0, look.CONTRAIL_DEFAULTS["LifetimeS"])
    assert look.contrail_persistence(float("nan"), 223.15)[1] == 0.0
    # 50 % over water at -50 C is 81 % over ice: no persistence
    rhi, factor, life = look.contrail_persistence(50.0, 223.15)
    assert rhi == pytest.approx(81.0, abs=1.5) and factor == 0.0 and life == 25.0
    # 70 % over water at -50 C is ~113 % over ice: part-way to persistent
    rhi, factor, life = look.contrail_persistence(70.0, 223.15)
    assert 100.0 < rhi < 120.0 and 0.0 < factor < 1.0 and 25.0 < life < 240.0
    # saturated over water: fully persistent
    assert look.contrail_persistence(100.0, 223.15)[1:] == (1.0, 240.0)


def test_every_new_contrail_constant_is_in_the_defaults_with_its_cpp_fallback():
    text = _read(FX_CPP)
    for name in ("JetSpreadM", "JetMixS", "VortexRollupS", "VortexSpanFraction", "WakeSinkMPerS",
                 "PuffBreakup", "PuffCellM", "PersistentLifetimeS", "PersistenceRhiOnsetPct",
                 "PersistenceRhiSpanPct"):
        assert name in look.CONTRAIL_DEFAULTS, name
    found = re.findall(r'Constant\(TEXT\("contrail"\), TEXT\("(\w+)"\), ([\d.]+)\)', text)
    assert {n for n, _ in found} >= {"JetSpreadM", "JetMixS", "VortexRollupS", "VortexSpanFraction",
                                     "WakeSinkMPerS", "PuffBreakup", "PersistentLifetimeS",
                                     "PersistenceRhiOnsetPct", "PersistenceRhiSpanPct"}
    for name, fallback in found:
        assert float(fallback) == look.CONTRAIL_DEFAULTS[name], name
