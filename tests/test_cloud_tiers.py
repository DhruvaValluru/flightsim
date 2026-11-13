"""Round 52 (2026-11-11): round 51's beauty cumulus (#04 desert A-4, #12 cockpit
over the Grand Canyon, #13 747 over the ocean) were sliced into flat horizontal
tiers with straight edges.

Cause, in two halves:
1. the engine's SHADOW march is unjittered (VolumetricCloud.usf
   ShadowJitterNorm = 0.5, "Disabled jittering"), and on the constrained GPU it
   is 10 quadratic samples over 6 km whose every segment is opaque at cloud
   extinction: the sun's light at a point is a product of on/off steps at FIXED
   offsets towards the sun, identical in every capture (TSR has nothing to
   average): hard facets and lines;
2. the weather field is a plane pattern (3D billow 0.08 of it, none past 20 km)
   cut by a height-only threshold, so every cell is an extrusion with vertical
   walls; with (1) the walls light in flat tiers.
Fix (no march sample added): M_FlightSimCloudLayers treats a shadow sample (the
engine's ShadowSampleDistance > 0) as its segment's footprint (dithered by a
hash of its position, soft edge widened, erosion noise read at its mean once
wider than it), and the field's warp grows with height (SideBulge: the sides
lean and bulge). ``-look-cloud-tiers=off`` (FLIGHTSIM_RENDER_SWITCHES) puts
round 51's clouds back.

What must hold without an engine:
* the cause's premise (the march law, segment by segment) and the footprint
  law (C++ == Python, compiled here);
* the shader body, compiled as C++, is the Python twin's density, view and
  shadow samples alike, and a view sample or the switch off is round 51's
  computation exactly;
* the filter turns the sun's on/off steps into a ramp (Python twin, averaged
  over the dither as TSR averages the captures); the bulge leans the walls and
  keeps the cover;
* the material wires the engine's ShadowSampleDistance, its generations are
  bumped, the bridge sets the parameters and refuses an unknown switch word;
* the march cost is unchanged (no sample added; the constrained row is ef361bd6's).
"""

import math
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
HLSL = (REPO / "assets" / "shaders" / "world" / "cloud_layers.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _script_value(name):
    import ast
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _engine_segments(shadow_km, samples):
    """VolumetricCloud.usf's quadratic shadow march (5.7): segment i spans
    [((i-1)/N)^2, (i/N)^2] x L and is sampled at ShadowJitterNorm = 0.5 of it."""
    out = []
    prev = 0.0
    for i in range(1, int(samples) + 1):
        cur = (i / samples) ** 2
        out.append((shadow_km * (prev + 0.5 * (cur - prev)), shadow_km * (cur - prev)))
        prev = cur
    return out


# -- the cause ----------------------------------------------------------------------

def test_the_constrained_shadow_march_is_on_off_steps_at_cloud_extinction():
    """Every segment of the constrained row's shadow march is opaque inside a
    cumulus (optical depth >= 3): a shadow sample in cloud is black, out of it
    clear, so the sun's light is a product of steps at fixed offsets."""
    row = wb.cloud_march(True)
    assert row["shadow_samples"] == 10.0 and wb.CLOUD_SHADOW_CONSTRAINED_KM == 6.0
    segments = _engine_segments(wb.CLOUD_SHADOW_CONSTRAINED_KM, row["shadow_samples"])
    depths = [wb.CLOUDS["cumulus"]["extinction_per_m"] * length * 1000.0 for _, length in segments]
    assert min(depths) >= 3.0 and max(depths) > 50.0
    # the engine pins the shadow jitter off; the bridge's API check pins that line
    check = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
    assert "const float ShadowJitterNorm = 0.5f;" in check


def test_the_footprint_is_the_quadratic_segment():
    """ShadowFootprintKm x sqrt(d) is the segment the engine's sample at d
    stands for (2 sqrt(L d) / N), within 10 % past the first segment."""
    for shadow_km, samples in ((6.0, 10.0), (4.0, 60.0), (1.0, 60.0)):
        per = wb.cloud_shadow_footprint_per_sqrt_km(shadow_km, samples)
        assert per == pytest.approx(2.0 * math.sqrt(shadow_km) / samples)
        for i, (d, length) in enumerate(_engine_segments(shadow_km, samples)):
            if i == 0:
                assert per * math.sqrt(d) == pytest.approx(length, rel=0.5)
            else:
                assert per * math.sqrt(d) == pytest.approx(length, rel=0.10)
    assert wb.cloud_shadow_footprint_per_sqrt_km(6.0, 10.0, filter_on=False) == 0.0
    assert wb.cloud_shadow_footprint_per_sqrt_km(0.0, 10.0) == 0.0
    assert wb.cloud_shadow_footprint_per_sqrt_km(6.0, 0.0) == 0.0


def test_a_view_sample_and_the_switch_off_are_round_51():
    rng = random.Random(5)
    row = wb.CLOUDS["cumulus"]
    for _ in range(300):
        km = (rng.uniform(0, 300), rng.uniform(0, 300), rng.uniform(1, 4))
        h = rng.uniform(0.0, 1.0)
        dither = (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5))
        dist = 0.0 if rng.random() < 0.5 else rng.uniform(0, 30)
        assert wb.cloud_density(km, h, 0.35, row, dist) == wb.cloud_density(km, h, 0.35, row, dist, 0.0, dither, 1.2)


def _sun_transmittance(x, y, h, row, cover, base_km, thickness_km, sun, footprint_per, dither_rng, white=False):
    """The engine's quadratic march (constrained row) from (x, y, h) towards the
    sun. The dither is the shader's: one seed a ray (the pixel's interleaved
    gradient noise in a capture; a uniform draw here), stratified by R3 over the
    sample's index; ``white`` draws round 52's independent uniforms instead."""
    od = 0.0
    ext = row["extinction_per_m"]
    u0 = dither_rng.random() if dither_rng is not None else 0.0
    for d, length in _engine_segments(wb.CLOUD_SHADOW_CONSTRAINED_KM, 10.0):
        p = (x + sun[0] * d, y + sun[1] * d, base_km + h * thickness_km + sun[2] * d)
        hp = (p[2] - base_km) / thickness_km
        if hp <= 0.0 or hp >= 1.0:
            break
        foot = footprint_per * math.sqrt(d)
        if foot <= 0.0:
            dither = (0.0, 0.0, 0.0)
        elif white:
            dither = tuple(dither_rng.uniform(-0.5, 0.5) for _ in range(3))
        else:
            dither = wb.cloud_shadow_dither(u0, wb.cloud_shadow_sample_index(d, footprint_per))
        od += wb.cloud_density(p, hp, cover, row, 25.0, foot, dither, thickness_km) * ext * length * 1000.0
    return math.exp(-od)


def test_the_filter_turns_the_suns_steps_into_a_ramp():
    """The sun's transmittance 10 m apart in height at 200 points inside a
    cumulus layer (sun 20 deg up): round 51's jumps by up to a quarter of the
    light between two points one tier apart; the filtered one, averaged over
    the dither as TSR averages the captures (the same 32 draws at both heights:
    the step, not the grain), never jumps by more than half that, and the mean
    light stays within a quarter (a softer, not a flat-lit or a black cloud)."""
    row = wb.CLOUDS["cumulus"]
    cover, base_km, thickness_km = 0.35, 3.0, 2.0
    el, az = math.radians(20.0), math.radians(20.0)
    sun = (math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el))
    per = wb.cloud_shadow_footprint_per_sqrt_km(wb.CLOUD_SHADOW_CONSTRAINED_KM, 10.0)
    rng = random.Random(9)
    points = []
    while len(points) < 200:
        x, y, h = rng.uniform(0, 200), rng.uniform(0, 200), rng.uniform(0.05, 0.9)
        if wb.cloud_density((x, y, base_km + thickness_km * h), h, cover, row, 25.0) > 0.0:
            points.append((x, y, h))
    dh = 0.010 / thickness_km

    def sun_t(x, y, h, footprint_per, seed):
        if footprint_per == 0.0:
            return _sun_transmittance(x, y, h, row, cover, base_km, thickness_km, sun, 0.0, None)
        draws = random.Random(seed)
        return sum(_sun_transmittance(x, y, h, row, cover, base_km, thickness_km, sun, footprint_per, draws)
                   for _ in range(32)) / 32.0

    old_jumps, new_jumps, old_mean, new_mean = [], [], 0.0, 0.0
    for i, (x, y, h) in enumerate(points):
        old_a, old_b = sun_t(x, y, h, 0.0, i), sun_t(x, y, h + dh, 0.0, i)
        new_a, new_b = sun_t(x, y, h, per, i), sun_t(x, y, h + dh, per, i)
        old_jumps.append(abs(old_b - old_a))
        new_jumps.append(abs(new_b - new_a))
        old_mean += old_a / len(points)
        new_mean += new_a / len(points)
    assert max(old_jumps) > 0.2                          # round 51: a hard tier edge
    assert max(new_jumps) < 0.5 * max(old_jumps)         # round 52: a ramp
    assert sum(j > 0.1 for j in new_jumps) < sum(j > 0.1 for j in old_jumps)
    assert new_mean == pytest.approx(old_mean, rel=0.25)


def test_a_thick_cells_base_stays_dark():
    """The dither reaches up to two footprints (over 2 km for the last shadow
    sample): it must not let the sun leak into a thick cell's base. At 10 % of
    the layer under 150 cells that are cloud to mid-layer, round 51's base gets
    no sun and the filtered one, averaged over the dither, under 2 %."""
    row = wb.CLOUDS["cumulus"]
    el, az = math.radians(20.0), math.radians(20.0)
    sun = (math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el))
    per = wb.cloud_shadow_footprint_per_sqrt_km(wb.CLOUD_SHADOW_CONSTRAINED_KM, 10.0)
    rng = random.Random(12)
    bases = []
    while len(bases) < 150:
        x, y = rng.uniform(0, 200), rng.uniform(0, 200)
        if all(wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.35, row, 25.0) > 0.5 for h in (0.1, 0.3, 0.45)):
            bases.append((x, y))
    old = sum(_sun_transmittance(x, y, 0.1, row, 0.35, 3.0, 2.0, sun, 0.0, None) for x, y in bases) / len(bases)
    draws = random.Random(4)
    new = sum(sum(_sun_transmittance(x, y, 0.1, row, 0.35, 3.0, 2.0, sun, per, draws) for _ in range(8)) / 8.0
              for x, y in bases) / len(bases)
    assert old < 0.02 and new < 0.02


def test_the_erosion_mean_is_the_noises():
    """A shadow sample wider than the erosion noise reads its mean: the
    shader's DETAIL_MEAN is cloud_detail's, measured here."""
    rng = random.Random(1)
    values = [wb.cloud_detail(rng.uniform(0, 300), rng.uniform(0, 300), rng.uniform(0, 300), 13)
              for _ in range(8000)]
    assert sum(values) / len(values) == pytest.approx(wb.CLOUD_DETAIL_MEAN, abs=0.01)
    assert f"const float DETAIL_MEAN = {wb.CLOUD_DETAIL_MEAN};" in HLSL


def test_the_bulge_leans_the_walls_and_keeps_the_cover():
    """Round 51's far field (no billow past 20 km) is an extrusion: below the
    rounding, whether a column is cloud does not change with height (vertical
    walls). With the bulge the outline moves with height, it is 0 at mid-layer
    (the distant sheet's slice) and the drawn cover is still the stated one."""
    row = wb.CLOUDS["cumulus"]
    rng = random.Random(31)
    points = [(rng.uniform(0, 300), rng.uniform(0, 300)) for _ in range(1500)]

    def inside(x, y, h, bulge):
        return wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.35, row, 30.0, side_bulge=bulge) > 0.0

    old_changes = sum(inside(x, y, 0.1, 0.0) != inside(x, y, 0.22, 0.0) for x, y in points)
    new_changes = sum(inside(x, y, 0.1, wb.CLOUD_SIDE_BULGE) != inside(x, y, 0.22, wb.CLOUD_SIDE_BULGE)
                      for x, y in points)
    assert old_changes == 0                       # vertical walls
    assert new_changes >= 0.01 * len(points)      # the outline moves with height
    assert wb.cloud_side_bulge(wb.CLOUD_SIDE_BULGE, 0.5) == 0.0
    assert wb.cloud_side_bulge(0.0, 0.1) == 0.0
    for h in (0.1, 0.2):
        share = sum(inside(x, y, h, wb.CLOUD_SIDE_BULGE) for x, y in points) / len(points)
        base = sum(inside(x, y, h, 0.0) for x, y in points) / len(points)
        assert share == pytest.approx(base, rel=0.15)
    # the shared noise: ShapeLod is ShapeLodBulge at 0, in both shaders (text-equal struct)
    assert "return ShapeLodBulge(p, far, 0.0, seed);" in HLSL
    assert "float qx = p.x + (0.45 + bulge) * wx;" in HLSL


def test_the_dither_is_stratified_and_less_grainy():
    """Round 61 (r58's grain): one seed a ray, stratified by R3 over the shadow
    samples, at 1 footprint: the per-capture spread of the sun's light (the
    grain TSR must average away) is well under round 52's white 2-footprint
    dither, the tiers stay gone (the 10 m jump stays under half of round 51's)
    and the mean light is round 51's within 10 %."""
    row = wb.CLOUDS["cumulus"]
    el, az = math.radians(20.0), math.radians(20.0)
    sun = (math.cos(el) * math.sin(az), -math.cos(el) * math.cos(az), math.sin(el))
    per = wb.cloud_shadow_footprint_per_sqrt_km(wb.CLOUD_SHADOW_CONSTRAINED_KM, 10.0)
    rng = random.Random(9)
    points = []
    while len(points) < 120:
        x, y, h = rng.uniform(0, 200), rng.uniform(0, 200), rng.uniform(0.05, 0.9)
        if wb.cloud_density((x, y, 3.0 + 2.0 * h), h, 0.35, row, 25.0) > 0.0:
            points.append((x, y, h))

    def stats(white, dither):
        saved = wb.CLOUD_SHADOW_DITHER
        wb.CLOUD_SHADOW_DITHER = dither
        try:
            spread, mean, jump = 0.0, 0.0, 0.0
            for i, (x, y, h) in enumerate(points):
                a = [_sun_transmittance(x, y, h, row, 0.35, 3.0, 2.0, sun, per, random.Random(i * 7 + k), white)
                     for k in range(16)]
                b = [_sun_transmittance(x, y, h + 0.005, row, 0.35, 3.0, 2.0, sun, per, random.Random(i * 7 + k), white)
                     for k in range(16)]
                m = sum(a) / 16.0
                spread += (sum((v - m) ** 2 for v in a) / 16.0) ** 0.5 / len(points)
                mean += m / len(points)
                jump = max(jump, abs(sum(b) / 16.0 - m))
            return spread, mean, jump
        finally:
            wb.CLOUD_SHADOW_DITHER = saved

    old_mean = sum(_sun_transmittance(x, y, h, row, 0.35, 3.0, 2.0, sun, 0.0, None) for x, y, h in points) / len(points)
    old_jump = max(abs(_sun_transmittance(x, y, h + 0.005, row, 0.35, 3.0, 2.0, sun, 0.0, None)
                       - _sun_transmittance(x, y, h, row, 0.35, 3.0, 2.0, sun, 0.0, None)) for x, y, h in points)
    r52_spread, _, _ = stats(True, 2.0)
    spread, mean, jump = stats(False, wb.CLOUD_SHADOW_DITHER)
    assert spread < 0.6 * r52_spread
    assert jump < 0.5 * old_jump
    assert mean == pytest.approx(old_mean, rel=0.10)


def test_the_dither_seed_is_interleaved_gradient_noise():
    """The seed TSR resolves: in [0, 1), every 4 x 4 block of pixels spans most
    of the range (neighbours differ: no clumps of one value), and the same pixel
    moves from capture to capture."""
    for frame in range(8):
        values = [[wb.cloud_shadow_ign(x + 0.5, y + 0.5, frame) for x in range(64)] for y in range(64)]
        assert all(0.0 <= v < 1.0 for row in values for v in row)
        for by in range(0, 64, 4):
            for bx in range(0, 64, 4):
                block = [values[by + j][bx + i] for j in range(4) for i in range(4)]
                assert max(block) - min(block) > 0.6
    seq = [wb.cloud_shadow_ign(100.5, 50.5, f) for f in range(8)]
    assert len({round(v, 4) for v in seq}) == 8
    # stratified: the ten samples of one ray spread over each axis
    for u0 in (0.0, 0.37, 0.91):
        d = [wb.cloud_shadow_dither(u0, float(i)) for i in range(10)]
        for axis in range(3):
            assert max(v[axis] for v in d) - min(v[axis] for v in d) > 0.6


def test_the_march_fades_out_under_the_distant_sheet():
    """Round 61 (r58's distant band of block columns): where the sheet is drawn
    the march fades out over the sheet's own fade-in (a cross-fade, 1 - the
    sheet's smoothstep), not under it; with the switch off, or no sheet, no fade."""
    start = wb.distant_handover_km(wb.DISTANT_NEAR_FIELD_KM)
    fade = wb.cloud_far_fade_km_for(True, wb.DISTANT_FADE_KM)
    assert fade == wb.DISTANT_FADE_KM and wb.cloud_far_fade_km_for(False, wb.DISTANT_FADE_KM) == 0.0
    assert wb.cloud_far_fade(start - 1.0, start, fade) == 1.0
    assert wb.cloud_far_fade(start + fade, start, fade) == 0.0
    for d in (start + 1.0, start + 4.0, start + 7.0):
        sheet = wb._smoothstep(start, start + fade, d)
        assert wb.cloud_far_fade(d, start, fade) + sheet == pytest.approx(1.0)
    assert wb.cloud_far_fade(start + 4.0, start, 0.0) == 1.0
    # the sheet's fade-in is by the same distance law (distant_clouds.hlsl)
    distant = (REPO / "assets" / "shaders" / "world" / "distant_clouds.hlsl").read_text(encoding="utf-8")
    assert "float fadeIn = smoothstep(HandoverKm, HandoverKm + max(FadeKm, 1e-3), distKm);" in distant
    assert "length(WorldPos - CameraPos) / 100000.0" in HLSL
    # the bridge: 0 on every layer until the sheet is drawn, then the sheet's numbers
    apply = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyClouds("):
                       CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyDistantClouds(")]
    assert 'State.Material->SetScalarParameterValue(TEXT("FarFadeKm"), 0.0f);' in apply
    distant_cpp = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyDistantClouds("):]
    assert "const double FarFadeKm = CloudFarFadeKmFor(CloudTiersSwitch == TEXT(\"on\"), DistantFadeKm);" in distant_cpp
    assert 'Layer.Material->SetScalarParameterValue(TEXT("FarFadeStartKm"), static_cast<float>(HandoverKm));' in distant_cpp
    assert 'Layer.Material->SetScalarParameterValue(TEXT("FarFadeKm"), static_cast<float>(FarFadeKm));' in distant_cpp
    scalars = _script_value("WORLD_CLOUD_SCALARS")
    assert scalars["FarFadeStartKm"] == 0.0 and scalars["FarFadeKm"] == 0.0
    assert int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"]) >= 6
    assert int(_script_value("WORLD_GENERATIONS")["M_FlightSimCloudLayers"]) >= 7


# -- the shader is the twin ----------------------------------------------------------

_SHIMS = r"""
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
using uint = uint32_t;
struct float3 { float x, y, z; float3() : x(0), y(0), z(0) {}
    float3(float a, float b, float c) : x(a), y(b), z(c) {}
    float3& operator+=(float3 o) { x += o.x; y += o.y; z += o.z; return *this; } };
static float3 operator+(float3 a, float3 b) { return float3(a.x + b.x, a.y + b.y, a.z + b.z); }
static float3 operator-(float3 a, float3 b) { return float3(a.x - b.x, a.y - b.y, a.z - b.z); }
static float3 operator-(float3 a, double s) { return float3(a.x - (float)s, a.y - (float)s, a.z - (float)s); }
static float3 operator*(float3 a, float s) { return float3(a.x * s, a.y * s, a.z * s); }
static float3 operator/(float3 a, double s) { return float3(a.x / (float)s, a.y / (float)s, a.z / (float)s); }
static float3 floor(float3 a) { return float3(std::floor(a.x), std::floor(a.y), std::floor(a.z)); }
static float dot(float3 a, float3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static float length(float3 a) { return std::sqrt(dot(a, a)); }
static float min(float a, float b) { return a < b ? a : b; }
static float max(float a, float b) { return a > b ? a : b; }
static float clamp(float v, float a, float b) { return min(max(v, a), b); }
static float saturate(float v) { return clamp(v, 0.0f, 1.0f); }
static float lerp(float a, float b, float t) { return a + (b - a) * t; }
static float smoothstep(float a, float b, float x) { float t = saturate((x - a) / (b - a)); return t * t * (3.0f - 2.0f * t); }
static uint asuint(int v) { uint u; std::memcpy(&u, &v, 4); return u; }
static int asint(float v) { int i; std::memcpy(&i, &v, 4); return i; }
static float frac(float v) { return v - std::floor(v); }
static float3 frac(float3 a) { return float3(frac(a.x), frac(a.y), frac(a.z)); }
static float3 operator+(float s, float3 a) { return float3(s + a.x, s + a.y, s + a.z); }
struct FShimPosition { float x, y, z, w; };
struct FShimParameters { FShimPosition SvPosition; };
struct FShimView { uint StateFrameIndexMod8; };
static FShimParameters Parameters;
static FShimView View;
"""

_INPUTS = ("WorldPos", "NormAlt", "CameraPos", "Coverage", "ExtinctionPerM", "ExtinctionScale", "ShapeScaleKm",
           "DetailScaleKm", "DetailErosion", "BottomSoftness", "TopRounding", "CoverageContrast", "SeedOffsetKm",
           "WindOffsetM", "ShadowDist", "ShadowFootprintKm", "LayerThicknessKm", "SideBulge",
           "FarFadeStartKm", "FarFadeKm", "HeightDensity")
_VECTORS = ("WorldPos", "CameraPos", "SeedOffsetKm", "WindOffsetM")


def _shader_as_cpp():
    head, body = HLSL.split("\nFWorldCloud C;\n", 1)
    body = "FWorldCloud C;\n" + body.replace("[branch]\n", "")
    params = ", ".join(("float3 " if n in _VECTORS else "float ") + n for n in _INPUTS)
    return _SHIMS + head + "\nstatic float Extinction(" + params + ")\n{\n" + body + "\n}\n"


@NEEDS_CXX
def test_the_shader_body_is_the_python_twin(tmp_path):
    """cloud_layers.hlsl's whole body compiled as C++: view samples, shadow
    samples with the filter on (the dither is the Python twin's interleaved
    gradient noise of the same pixel and capture, stratified by the sample's
    index) and off, the far fade on and off, against
    core/scene/world_beauty.cloud_density x cloud_far_fade; and a shadow sample
    with the switch off is a view sample, bit for bit."""
    assert _script_value("WORLD_CLOUD_INPUTS") == _INPUTS
    row = wb.CLOUDS["cumulus"]
    rng = random.Random(17)
    cases = []
    for i in range(160):
        pos = (rng.uniform(-3e6, 3e6), rng.uniform(-3e6, 3e6), rng.uniform(2.9e5, 5.0e5))
        cam = (rng.uniform(-1e5, 1e5), rng.uniform(-1e5, 1e5), 2.0e5)
        h = rng.uniform(0.02, 0.98)
        shadow_cm = 0.0 if i % 3 == 0 else rng.uniform(1e3, 6e5)
        footprint = 0.0 if i % 3 == 1 else wb.cloud_shadow_footprint_per_sqrt_km(6.0, 10.0)
        bulge = 0.0 if i % 4 == 0 else wb.CLOUD_SIDE_BULGE
        fade = 0.0 if i % 5 == 0 else wb.DISTANT_FADE_KM
        pixel = (rng.randrange(0, 1920) + 0.5, rng.randrange(0, 1080) + 0.5, rng.randrange(0, 8))
        hd = 0.0 if i % 2 == 0 else wb.CLOUD_BILLOW_HEIGHT_DENSITY   # round 82
        cases.append((pos, cam, h, shadow_cm, footprint, bulge, fade, pixel, hd))
    seed = (123.4, 456.7, 7.0)

    def call(pos, cam, h, shadow_cm, footprint, bulge, fade, pixel, hd=0.0):
        args = [f"float3({pos[0]!r}f, {pos[1]!r}f, {pos[2]!r}f)", f"{h!r}f",
                f"float3({cam[0]!r}f, {cam[1]!r}f, {cam[2]!r}f)", "0.35f", f"{row['extinction_per_m']!r}f", "1.0f",
                f"{row['shape_scale_km']!r}f", f"{row['detail_scale_km']!r}f", f"{row['detail_erosion']!r}f",
                f"{row['bottom_softness']!r}f", f"{row['top_rounding']!r}f", f"{row['coverage_contrast']!r}f",
                f"float3({seed[0]!r}f, {seed[1]!r}f, {seed[2]!r}f)", "float3(0.0f, 0.0f, 0.0f)",
                f"{shadow_cm!r}f", f"{footprint!r}f", "2.0f", f"{bulge!r}f", "24.0f", f"{fade!r}f", f"{hd!r}f"]
        return ("(Parameters.SvPosition.x = {0!r}f, Parameters.SvPosition.y = {1!r}f, "
                "View.StateFrameIndexMod8 = {2}u, Extinction(".format(*pixel) + ", ".join(args) + "))")

    main = ["int main() {"]
    for c in cases:
        main.append(f'printf("%.9g\\n", (double){call(*c)});')
        # the switch off (footprint, bulge, fade 0) on a shadow sample == the view sample, bit for bit
        pos, cam, h, shadow_cm, _, _, _, pixel, hd = c
        main.append(f'printf("%d\\n", {call(pos, cam, h, shadow_cm, 0.0, 0.0, 0.0, pixel, hd)} == '
                    f'{call(pos, cam, h, 0.0, 0.0, 0.0, 0.0, (0.5, 0.5, 0), hd)});')
    main.append("return 0; }")
    (tmp_path / "body.cpp").write_text(_shader_as_cpp() + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O0", "-o", str(tmp_path / "body"), str(tmp_path / "body.cpp")],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(tmp_path / "body")], check=True, capture_output=True, text=True).stdout.split()
    import struct
    f32 = lambda v: struct.unpack("f", struct.pack("f", v))[0]
    exercised = 0
    for i, (pos, cam, h, shadow_cm, footprint, bulge, fade, pixel, hd) in enumerate(cases):
        assert out[2 * i + 1] == "1", i
        p = tuple(f32(v) for v in pos)
        km = tuple(c / 100.0 / 1000.0 + s for c, s in zip(p, (f32(v) for v in seed)))
        dist_km = math.dist(p, tuple(f32(v) for v in cam)) / 100000.0
        foot = f32(footprint) * math.sqrt(max(f32(shadow_cm), 0.0) / 100000.0)
        dither = (wb.cloud_shadow_dither(wb.cloud_shadow_ign(*pixel),
                                         wb.cloud_shadow_sample_index(f32(shadow_cm) / 100000.0, f32(footprint)))
                  if foot > 0.0 else (0.0, 0.0, 0.0))
        want = (wb.cloud_density(km, f32(h), 0.35, row, dist_km, foot, dither, 2.0, f32(bulge), f32(hd)) * row["extinction_per_m"]
                * wb.cloud_far_fade(dist_km, 24.0, fade))
        got = float(out[2 * i])
        assert got == pytest.approx(want, abs=2e-3 * row["extinction_per_m"] + 1e-7), (i, pos, h, shadow_cm, footprint, bulge)
        exercised += foot > 0.0 and want > 0.0
    assert exercised >= 5   # filtered shadow samples inside cloud were compared


def test_the_shader_constants_are_the_pythons():
    assert f"const float SHADOW_DITHER = {wb.CLOUD_SHADOW_DITHER};" in HLSL
    assert f"const float SHADOW_SOFTEN = {wb.CLOUD_SHADOW_SOFTEN};" in HLSL
    for axis, value in zip("XYZ", wb.CLOUD_SHADOW_R3):
        assert f"const float R3_{axis} = {value};" in HLSL
    # the dither's seed is the engine's pixel and capture, not a hash of the position
    assert "Parameters.SvPosition.x + 5.588238 * (float)View.StateFrameIndexMod8" in HLSL
    assert "asint(WorldPos" not in HLSL
    assert "if (FarFadeKm > 0.0)" in HLSL
    assert "return density * base * body * ExtinctionPerM * ExtinctionScale * fadeOut;" in HLSL
    # a view sample (ShadowDist 0) and the switch off (footprint 0) take no new branch
    assert "float footKm = ShadowFootprintKm * sqrt(max(ShadowDist, 0.0) / 100000.0);" in HLSL
    assert "if (footKm > 0.0)" in HLSL
    assert "UNCALIBRATED (world_beauty.CLOUD_SHADOW_DITHER / CLOUD_SHADOW_SOFTEN)" in HLSL
    assert f"const float BULGE_TURN = {wb.CLOUD_BULGE_TURN};" in HLSL
    assert "float bulge = SideBulge * sin(BULGE_TURN * (h - 0.5));" in HLSL
    for name in ("ShadowDist", "ShadowFootprintKm", "LayerThicknessKm", "SideBulge", "FarFadeStartKm", "FarFadeKm"):
        assert re.search(rf"//\s+{name}\s", HLSL), name


# -- the material, the bridge and the switch ------------------------------------------

def test_the_material_wires_the_engines_shadow_sample_distance_and_is_rebuilt():
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    # one Cloud Sample Attributes node, two of its outputs (the engine's pin names,
    # MaterialExpressions.cpp UMaterialExpressionCloudSampleAttribute)
    assert create.count("unreal.MaterialExpressionCloudSampleAttribute") == 1
    assert 'inputs["NormAlt"] = (attributes, "NormAltitudeInLayer")' in create
    assert 'inputs["ShadowDist"] = (attributes, "ShadowSampleDistance")' in create
    scalars = _script_value("WORLD_CLOUD_SCALARS")
    assert scalars["ShadowFootprintKm"] == 0.0          # unset = round 51's march
    assert scalars["LayerThicknessKm"] > 0.0
    assert scalars["SideBulge"] == 0.0                  # unset = round 51's vertical walls
    assert int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"]) >= 5
    assert int(_script_value("WORLD_GENERATIONS")["M_FlightSimCloudLayers"]) >= 6
    # the distant sheet's shared noise text changed (ShapeLodBulge): rebuilt too
    assert int(_script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimDistantClouds"]) >= 4
    assert int(_script_value("WORLD_GENERATIONS")["M_FlightSimDistantClouds"]) >= 4
    check = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
    assert 'Outputs.Add(FExpressionOutput(TEXT(\\"ShadowSampleDistance\\")));' in check \
        or "Outputs.Add(FExpressionOutput(TEXT(\"ShadowSampleDistance\")));" in check


@NEEDS_CXX
def test_the_bridges_footprint_law_is_the_pythons(tmp_path):
    begin, end = "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END"
    block = CLOUDS_CPP[CLOUDS_CPP.index(begin) + len(begin):CLOUDS_CPP.index(end)]
    cases = [(6.0, 10.0, 1), (6.0, 10.0, 0), (4.0, 60.0, 1), (1.0, 60.0, 1), (0.0, 10.0, 1), (6.0, 0.0, 1)]
    main = ["using namespace FlightSimWorldPure;", "int main() {"]
    main += [f'printf("%.17g\\n", CloudShadowFootprintPerSqrtKm({k!r}, {n!r}, {"true" if on else "false"}));'
             for k, n, on in cases]
    main += ['printf("%.17g\\n", CloudSideBulgeFor(true));', 'printf("%.17g\\n", CloudSideBulgeFor(false));']
    main += ['printf("%.17g\\n", CloudFarFadeKmFor(true, DistantFadeKm));',
             'printf("%.17g\\n", CloudFarFadeKmFor(false, DistantFadeKm));',
             'printf("%.17g\\n", CloudFarFadeKmFor(true, 0.0));']
    main.append("return 0; }")
    source = tmp_path / "foot.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-Wno-unused-function", "-o", str(tmp_path / "foot"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "foot")], check=True, capture_output=True, text=True).stdout.split()
    assert [float(v) for v in lines] == [wb.cloud_shadow_footprint_per_sqrt_km(k, n, bool(on)) for k, n, on in cases] + [
        wb.cloud_side_bulge_for(True), wb.cloud_side_bulge_for(False),
        wb.cloud_far_fade_km_for(True, wb.DISTANT_FADE_KM), wb.cloud_far_fade_km_for(False, wb.DISTANT_FADE_KM),
        wb.cloud_far_fade_km_for(True, 0.0)]


def test_the_bridge_sets_the_footprint_under_the_switch():
    assert wb.CLOUD_TIERS_SWITCH == "-look-cloud-tiers"
    assert 'const double SideBulge = CloudSideBulgeFor(CloudTiersSwitch == TEXT("on"));' in CLOUDS_CPP
    assert 'State.Material->SetScalarParameterValue(TEXT("SideBulge"), static_cast<float>(SideBulge));' in CLOUDS_CPP
    assert 'Layer->SetNumberField(TEXT("side_bulge_cells"), SideBulge);' in CLOUDS_CPP
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build("):]
    # read from the command line and FLIGHTSIM_RENDER_SWITCHES, on by default
    switches = build[:build.index('FParse::Value(*Switches, TEXT("look-cloud-tiers="), CloudTiersSwitch);')]
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in switches
    assert 'CloudTiersSwitch = TEXT("on");' in build
    assert 'FString CloudTiersSwitch = TEXT("on");' in CLOUDS_H
    # another word refuses by name
    assert "world_beauty.clouds: -look-cloud-tiers=%s is not on or off" in build
    # per layer: the footprint (0 when off) and the thickness, recorded
    assert ("CloudShadowFootprintPerSqrtKm(ShadowTracingKm, ShadowSamples, CloudTiersSwitch == TEXT(\"on\"))"
            in CLOUDS_CPP)
    assert 'State.Material->SetScalarParameterValue(TEXT("ShadowFootprintKm"), static_cast<float>(ShadowFootprint));' \
        in CLOUDS_CPP
    assert 'State.Material->SetScalarParameterValue(TEXT("LayerThicknessKm"),' in CLOUDS_CPP
    assert 'Layer->SetNumberField(TEXT("shadow_footprint_km_per_sqrt_km"), ShadowFootprint);' in CLOUDS_CPP
    assert 'MarchOut->SetStringField(TEXT("cloud_tiers"), CloudTiersSwitch);' in CLOUDS_CPP


def test_no_march_sample_is_added():
    """The fix is in the material: the constrained row stays ef361bd6's march
    (the #09 storm already hangs the Intel iGPU), the shadow length stays 6 km."""
    row = wb.cloud_march(True)
    assert (row["view_samples_max"], row["shadow_samples"], row["tracing_max_distance_km"]) == (192.0, 10.0, 80.0)
    assert "{2.0, 1.0, 80.0},   // constrained: 192 view, 10 shadow samples (ef361bd6)" in CLOUDS_CPP
    assert "constexpr double CloudShadowConstrainedKm = 6.0;" in CLOUDS_CPP
    # no cvar or sample-count setter is new: the only march setters are the round-2 ones
    assert CLOUDS_CPP.count("SetShadowViewSampleCountScale(") == 1
    assert CLOUDS_CPP.count("SetViewSampleCountScale(") == 1
    # and a filtered shadow sample wider than the erosion noise reads its mean (fewer hashes)
    assert "float detail = DETAIL_MEAN;" in HLSL and "if (footKm < max(DetailScaleKm, 1e-3))" in HLSL
