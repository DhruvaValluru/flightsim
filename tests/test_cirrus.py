"""Sky step 6 (the owner's X-Plane-12 brief, 2026-11-15): the beauty-only cirrus
sheet. What must hold without an engine:

* the C++ pure laws (FlightSimClouds.cpp Cirrus*: the altitude law, the cover
  law, the streak bearing, the look table) are the Python ones
  (core/scene/cirrus.py), compiled with g++ and compared;
* cirrus.hlsl's noise members are cloud_layers.hlsl's FWorldCloud text for text,
  its field is the Python replica to single precision (g++), its quantile
  constants are the replica's measured moments, and the cut's drawn share is
  the cover;
* the material script's parameters, the HLSL inputs and the C++ names agree;
  the material is unlit translucent with no custom-depth or velocity write;
* the sheet is beauty only and label safe (BeautyOnlyActors, no custom depth,
  no shadow, no collision), built after the distant sheet, above the camera;
* the switch is parsed, refused by name, registered and catalogued; the measure
  path is untouched; the docs say UNMEASURED and name the Windows command.
"""

import ast
import re
import shutil
import statistics
import subprocess
from pathlib import Path

import pytest

from core import config_surface
from core.scene import cirrus as ci
from core.scene import world_beauty as wb
from core.sky.clouds import plan_cloud_block

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
SKY_CPP = (SOURCE / "Private" / "FlightSimSky.cpp").read_text(encoding="utf-8")
SKY_H = (SOURCE / "Public" / "FlightSimSky.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
CATALOG = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "world"
CIRRUS_HLSL = (SHADERS / "cirrus.hlsl").read_text(encoding="utf-8")
LAYERS_HLSL = (SHADERS / "cloud_layers.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end)]


def _body(text, name, nxt):
    return text[text.index(name):text.index(nxt)]


def _script_value(name):
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


PURE = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
APPLY_CIRRUS = _body(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyCirrus(", "void FFlightSimWorldBeauty::ApplyTiles(")
BUILD = _body(CLOUDS_CPP, "bool FFlightSimWorldBeauty::Build(", "// -- tiles-delight")
ADVANCE = _body(CLOUDS_CPP, "void FFlightSimWorldBeauty::Advance(",
                "TSharedPtr<FJsonObject> FFlightSimWorldBeauty::CloudOcclusionRecord")
CREATE = _body(SCRIPT, "def create_world_cirrus", "def create_sky_hdri")


def _cpp_constant(name):
    found = re.search(r"constexpr (?:double|int) " + name + r" = (-?[0-9.]+);", PURE)
    assert found, name
    return float(found.group(1))


# -- the Python laws -------------------------------------------------------------------------

def test_the_altitude_law_keeps_the_sheet_above_the_camera():
    for camera in (0.0, 500.0, 3000.0, 8500.0, 9000.0, 10000.0, 11500.0, 12500.0, 13000.0, 15000.0):
        sheet = ci.cirrus_sheet(camera)
        assert sheet["altitude_m"] >= camera or sheet["fade"] == 0.0, camera
        assert ci.CIRRUS_BASE_M <= sheet["altitude_m"] <= ci.CIRRUS_MAX_M
        assert 0.0 <= sheet["fade"] <= 1.0
    assert ci.cirrus_sheet(500.0) == {"altitude_m": 10000.0, "fade": 1.0}
    assert ci.cirrus_sheet(10000.0) == {"altitude_m": 11500.0, "fade": 1.0}   # scene 13's 747
    assert ci.cirrus_sheet(12250.0)["fade"] == pytest.approx(0.5)
    assert ci.cirrus_sheet(13000.0)["fade"] == 0.0
    # the clearance is more than the owner's 1 km rule, and the base is a real cirrus height
    assert ci.CIRRUS_CLEARANCE_M >= 1000.0 and 8000.0 <= ci.CIRRUS_BASE_M <= 13000.0 and ci.CIRRUS_MAX_M > ci.CIRRUS_BASE_M


def test_the_cover_law_in_order():
    d = ci.CIRRUS_DEFAULT_COVER
    # off wins over everything
    assert ci.cirrus_cover("off", True, True, 0.8, "clear") == (0.0, "off")
    # a rain or storm deck covers the sky
    for preset in ("rain", "storm"):
        assert ci.cirrus_cover("on", False, True, 0.8, preset) == (0.0, "preset")
        assert ci.cirrus_cover("on", True, False, 0.0, preset) == (0.0, "preset")
    # -cloud-type=cirrus: the data's cover when it has one, else the default
    assert ci.cirrus_cover("on", True, True, 0.6, "clear") == (0.6, "plan")
    assert ci.cirrus_cover("on", True, True, 0.0, "clear") == (d, "switch")
    assert ci.cirrus_cover("on", True, False, 0.0, "hazy") == (d, "switch")
    # a plan from data draws its number, 0 included (a clear upper sky stays clear)
    assert ci.cirrus_cover("on", False, True, 0.0, "clear") == (0.0, "plan")
    assert ci.cirrus_cover("on", False, True, 0.27, "overcast") == (0.27, "plan")
    assert ci.cirrus_cover("on", False, True, 1.7, "clear") == (1.0, "plan")
    # no data (a default plan, or no plan): the stated default
    assert ci.cirrus_cover("on", False, False, 0.0, "clear") == (d, "default")
    assert ci.cirrus_cover("", False, False, 0.0, "hazy") == (d, "default")
    assert set(s for s in ci.CIRRUS_COVER_SOURCES) == {"off", "preset", "switch", "plan", "default"}
    with pytest.raises(ValueError, match="world_beauty.cirrus"):
        ci.cirrus_cover("auto", False, False, 0.0, "clear")
    with pytest.raises(ValueError, match="unknown preset"):
        ci.cirrus_cover("on", False, False, 0.0, "foggy")
    assert 0.0 < ci.CIRRUS_MIN_DRAWN_COVER < d < 1.0


def test_the_switch_words_and_the_refusal():
    assert ci.CIRRUS_SWITCH == "-look-cirrus" and ci.CIRRUS_SWITCH_WORDS == ("on", "off")
    assert ci.cirrus_mode(None) == "on" and ci.cirrus_mode("") == "on" and ci.cirrus_mode("off") == "off"
    with pytest.raises(ValueError, match=r"world_beauty.cirrus: -look-cirrus=auto is not on or off"):
        ci.cirrus_mode("auto")


def test_the_streak_bearing_and_the_drift():
    # the card's drift bearing when it drifts (one axis, so any bearing 0..360 stands)
    assert ci.cirrus_streak_dir_deg(5, 3.0, 250.0) == 250.0
    assert ci.cirrus_streak_dir_deg(5, 3.0, -30.0) == 330.0
    assert ci.cirrus_streak_dir_deg(5, 3.0, 725.0) == 5.0
    # seeded when still: deterministic, in range, and not the noise offset's uniform
    a = ci.cirrus_streak_dir_deg(42, 0.0, 250.0)
    assert a == ci.cirrus_streak_dir_deg(42, 0.0, 10.0) and 0.0 <= a < 360.0
    assert a != ci.cirrus_streak_dir_deg(43, 0.0, 250.0)
    assert a != wb.cloud_seed_offset_km(42)[0] / wb.CLOUD_SEED_SPAN_KM * 360.0
    assert ci.cirrus_drift_mps(4.0) == 4.0 * ci.CIRRUS_WIND_GAIN and ci.cirrus_drift_mps(-1.0) == 0.0
    assert ci.CIRRUS_WIND_GAIN >= 1.0


# -- the field -------------------------------------------------------------------------------

def _grid(n=120, span=60.0):
    for i in range(n):
        for j in range(n):
            yield -span + 2.0 * span * i / n + 0.0137, -span + 2.0 * span * j / n + 0.0291


def test_the_field_moments_are_the_pinned_ones_and_the_cut_draws_the_cover():
    values = [ci.cirrus_streaks(qa, qc) for qa, qc in _grid()]
    assert statistics.fmean(values) == pytest.approx(ci.CIRRUS_FBM_MEAN, abs=0.01)
    assert statistics.pstdev(values) == pytest.approx(ci.CIRRUS_FBM_SIGMA, abs=0.006)
    assert 0.0 <= min(values) and max(values) <= 1.0
    for cover in (0.2, 0.35, 0.5, 0.7, 0.9):
        thr = ci.cirrus_threshold(cover)
        share = sum(v > thr for v in values) / len(values)
        assert share == pytest.approx(cover, abs=0.03), cover
    assert ci.cirrus_threshold(0.0) > ci.cirrus_threshold(0.5) > ci.cirrus_threshold(1.0)
    fibres = [ci.cirrus_fibres(qa, qc) for qa, qc in _grid(40)]
    assert 0.0 <= min(fibres) and max(fibres) <= 1.0 and statistics.fmean(fibres) == pytest.approx(0.5, abs=0.03)
    ends = [ci.cirrus_ends(qa, qc) for qa, qc in _grid(40)]
    assert statistics.fmean(ends) == pytest.approx(0.0, abs=0.03) and ci.CIRRUS_LOOK["FeatherWidth"] < statistics.pstdev(ends)


def test_the_thickness_is_bounded_deterministic_and_seeded():
    pts = [(x * 3.7, y * 2.3) for x in range(-6, 7) for y in range(-6, 7)]
    thick = [ci.cirrus_thickness(x, y, 0.5, 250.0) for x, y in pts]
    assert all(0.0 <= t <= 1.0 for t in thick) and any(t > 0.0 for t in thick) and any(t == 0.0 for t in thick)
    assert thick == [ci.cirrus_thickness(x, y, 0.5, 250.0) for x, y in pts]   # same inputs, same bytes
    # another bearing, another cover and another seed each move it
    assert thick != [ci.cirrus_thickness(x, y, 0.5, 70.0) for x, y in pts]
    assert thick != [ci.cirrus_thickness(x, y, 0.3, 250.0) for x, y in pts]
    assert thick != [ci.cirrus_thickness(x, y, 0.5, 250.0, seed=18) for x, y in pts]
    # more cover never draws less at a point
    for x, y in pts[::7]:
        a, b = ci.cirrus_thickness(x, y, 0.3, 250.0), ci.cirrus_thickness(x, y, 0.8, 250.0)
        assert b >= a - 1e-12
    # the frame: a bearing and its opposite are one axis up to sign; along is stretched by the aspect
    qa, qc = ci.cirrus_frame(10.0, 0.0, 90.0, 5.0, 8.0)
    assert (qa, qc) == pytest.approx((10.0 / 40.0, 0.0), abs=1e-9)
    qa2, qc2 = ci.cirrus_frame(0.0, 10.0, 0.0, 5.0, 8.0)
    assert (qa2, qc2) == pytest.approx((0.25, 0.0), abs=1e-9)
    # opacity: capped, rising with thickness and with the slant; the phase peaks forward and is capped
    assert ci.cirrus_opacity(0.0, 1.0) == 0.0
    assert ci.cirrus_opacity(1.0, 1.0) < ci.cirrus_opacity(1.0, 0.2) <= ci.CIRRUS_LOOK["MaxOpacity"]
    assert ci.cirrus_opacity(0.5, 1.0) == pytest.approx(1.0 - pow(2.718281828459045, -0.5 * ci.CIRRUS_LOOK["OpticalDepth"]))
    assert ci.cirrus_phase(1.0) > ci.cirrus_phase(0.0) > ci.cirrus_phase(-1.0) > 0.0
    assert ci.cirrus_phase(1.0) == pytest.approx((1.0 - ci.CIRRUS_LOOK["ForwardShare"])
                                                 + ci.CIRRUS_LOOK["ForwardShare"] * ci.CIRRUS_LOOK["ForwardCap"])


# -- the C++ pure block is the Python ------------------------------------------------------------

def test_the_cpp_constants_and_the_look_table_are_the_pythons():
    assert _cpp_constant("CirrusBaseM") == ci.CIRRUS_BASE_M
    assert _cpp_constant("CirrusClearanceM") == ci.CIRRUS_CLEARANCE_M
    assert _cpp_constant("CirrusMaxM") == ci.CIRRUS_MAX_M
    assert _cpp_constant("CirrusRadiusKm") == ci.CIRRUS_RADIUS_KM
    assert _cpp_constant("CirrusSortPriority") == ci.CIRRUS_SORT_PRIORITY
    assert _cpp_constant("CirrusDefaultCover") == ci.CIRRUS_DEFAULT_COVER
    assert _cpp_constant("CirrusMinDrawnCover") == ci.CIRRUS_MIN_DRAWN_COVER
    assert _cpp_constant("CirrusWindGain") == ci.CIRRUS_WIND_GAIN
    assert _cpp_constant("CirrusLookCount") == len(ci.CIRRUS_LOOK)
    names = re.search(r"static const char\* const Names\[CirrusLookCount\] = \{([^}]*)\};", PURE, re.S).group(1)
    assert re.findall(r'"([A-Za-z]+)"', names) == list(ci.CIRRUS_LOOK)
    values = re.search(r"static const double Values\[CirrusLookCount\] = \{([^}]*)\};", PURE, re.S).group(1)
    assert [float(v) for v in values.replace("\n", " ").split(",")] == list(ci.CIRRUS_LOOK.values())
    sources = re.search(r"static const char\* const Names\[5\] = \{([^}]*)\};", PURE).group(1)
    assert tuple(re.findall(r'"([a-z]+)"', sources)) == ci.CIRRUS_COVER_SOURCES
    # UNCALIBRATED is said where the numbers are
    cirrus_block = _block(PURE, "// Sky step 6 (the owner's X-Plane-12 brief", "inline double CirrusDriftMps")
    assert "UNCALIBRATED" in cirrus_block and "VISUAL ONLY" in cirrus_block
    assert "FString" not in cirrus_block and "TEXT(" not in cirrus_block


@NEEDS_CXX
def test_the_cpp_cirrus_laws_are_the_python_ones(tmp_path):
    cameras = (0.0, 500.0, 3000.0, 8500.0, 9000.0, 10000.0, 11500.0, 12250.0, 12500.0, 13000.0, 15000.0)
    covers = [(off, sw, data, plan, preset)
              for off in (0, 1) for sw in (0, 1) for data in (0, 1)
              for plan in (0.0, 0.27, 0.6, 1.7) for preset in range(len(wb.PRESETS))]
    bearings = [(seed, mps, deg) for seed in (0, 7, 42, 43, 123456789)
                for mps in (0.0, 3.0) for deg in (250.0, -30.0, 725.0, 0.0)]
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "for (int f = 0; f < CirrusLookCount; ++f) printf(\"look %s %.17g\\n\", CirrusLookName(f), CirrusLook(f));",
            "printf(\"const %.17g %.17g %.17g %.17g %d %.17g %.17g %.17g\\n\", CirrusBaseM, CirrusClearanceM, CirrusMaxM,"
            " CirrusRadiusKm, CirrusSortPriority, CirrusDefaultCover, CirrusMinDrawnCover, CirrusWindGain);"]
    for c in cameras:
        main.append(f"{{ FCirrusSheet S = CirrusSheetAltitudeM({c!r}); printf(\"sheet %.17g %.17g\\n\", S.AltitudeM, S.Fade); }}")
    for off, sw, data, plan, preset in covers:
        main.append(f"{{ int Src = -1; double C = CirrusCover({'true' if off else 'false'}, {'true' if sw else 'false'}, "
                    f"{'true' if data else 'false'}, {plan!r}, {preset}, &Src); "
                    f"printf(\"cover %.17g %s\\n\", C, CirrusCoverSourceName(Src)); }}")
    for seed, mps, deg in bearings:
        main.append(f"printf(\"dir %.17g\\n\", CirrusStreakDirDeg({seed}ull, {mps!r}, {deg!r}));")
    for mps in (0.0, 4.0, -1.0):
        main.append(f"printf(\"drift %.17g\\n\", CirrusDriftMps({mps!r}));")
    main.append("return 0; }")
    source = tmp_path / "cirrus.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + PURE + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "cirrus"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "cirrus")], check=True, capture_output=True, text=True).stdout.splitlines()
    look = [line.split() for line in lines if line.startswith("look ")]
    assert [name for _, name, _ in look] == list(ci.CIRRUS_LOOK)
    assert {name: float(v) for _, name, v in look} == ci.CIRRUS_LOOK
    const = next(line for line in lines if line.startswith("const ")).split()[1:]
    assert [float(v) for v in const] == [ci.CIRRUS_BASE_M, ci.CIRRUS_CLEARANCE_M, ci.CIRRUS_MAX_M, ci.CIRRUS_RADIUS_KM,
                                         ci.CIRRUS_SORT_PRIORITY, ci.CIRRUS_DEFAULT_COVER, ci.CIRRUS_MIN_DRAWN_COVER,
                                         ci.CIRRUS_WIND_GAIN]
    sheets = [l.split()[1:] for l in lines if l.startswith("sheet ")]
    for c, (alt, fade) in zip(cameras, sheets):
        ref = ci.cirrus_sheet(c)
        assert float(alt) == ref["altitude_m"] and float(fade) == pytest.approx(ref["fade"], rel=1e-15), c
    got = [l.split()[1:] for l in lines if l.startswith("cover ")]
    assert len(got) == len(covers)
    for (off, sw, data, plan, preset), (cover, src) in zip(covers, got):
        ref = ci.cirrus_cover("off" if off else "on", bool(sw), bool(data), plan, wb.PRESETS[preset])
        assert (float(cover), src) == ref, (off, sw, data, plan, preset)
    dirs = [float(l.split()[1]) for l in lines if l.startswith("dir ")]
    assert dirs == pytest.approx([ci.cirrus_streak_dir_deg(s, m, d) for s, m, d in bearings], rel=1e-12)
    assert [float(l.split()[1]) for l in lines if l.startswith("drift ")] == [ci.cirrus_drift_mps(m) for m in (0.0, 4.0, -1.0)]


# -- the shader ---------------------------------------------------------------------------------

def test_the_shader_noise_members_are_fworldclouds_text_for_text():
    struct = _block(CIRRUS_HLSL, "struct FCirrusNoise\n{\n", "\t// end shared")
    world = _block(LAYERS_HLSL, "struct FWorldCloud\n{\n", "\n};\n")
    members = re.split(r"\n(?=\t(?://|uint|float) )", struct.strip("\n"))
    assert len(members) >= 6
    for member in members:
        assert member.strip("\n") in world, member.splitlines()[0]
    for name in ("Probit(", "Pcg(", "Hash3(", "Fade(", "Grad(", "Perlin2("):
        assert name in struct, name
    assert "Worley(" not in CIRRUS_HLSL   # cirrus has no cells: gradient noise only
    assert "static const" not in CIRRUS_HLSL and "Texture" not in CIRRUS_HLSL
    assert "UNCALIBRATED" in CIRRUS_HLSL and "UNMEASURED" in CIRRUS_HLSL and "VISUAL ONLY" in CIRRUS_HLSL


def test_the_shader_constants_and_cut_are_the_replicas():
    assert f"const float FBM_MEAN = {ci.CIRRUS_FBM_MEAN};" in CIRRUS_HLSL
    assert f"const float FBM_SIGMA = {ci.CIRRUS_FBM_SIGMA};" in CIRRUS_HLSL
    assert f"const uint NOISE_SEED = {ci.CIRRUS_NOISE_SEED}u;" in CIRRUS_HLSL
    assert "float thr = FBM_MEAN + FBM_SIGMA * N.Probit(1.0 - cover);" in CIRRUS_HLSL
    assert "float soft = FBM_SIGMA * max(EdgeSigmas, 0.1);" in CIRRUS_HLSL
    assert "thick *= lerp(1.0 - saturate(FibreStrength), 1.0, N.Fibres(qa, qc, NOISE_SEED));" in CIRRUS_HLSL
    assert "thick *= smoothstep(0.0, max(FeatherWidth, 1e-3), abs(N.Ends(qa, qc, NOISE_SEED)));" in CIRRUS_HLSL
    assert "float opacity = min(saturate(MaxOpacity), 1.0 - exp(-tau));" in CIRRUS_HLSL
    assert "float2 dir = float2(sin(ang), cos(ang));" in CIRRUS_HLSL   # a compass bearing, engine X east / Y north
    assert "return float4(L, a);" in CIRRUS_HLSL
    # the field's constants, HLSL and Python (one place each)
    for literal in ("qa * 0.7 + 3.3, qc * 0.7 + 1.1, seed + 701u", "qa * 0.7 + 8.9, qc * 0.7 + 6.2, seed + 719u",
                    "0.35 * wa", "a + 1.3, c + 7.1, seed + 101u", "a * 2.1 + 5.7, c * 2.1 + 2.9, seed + 113u",
                    "a * 4.3 + 9.1, c * 4.3 + 4.4, seed + 127u", "qa * 1.5 + 2.2, qc * 6.0 + 3.7, seed + 211u",
                    "qa * 3.0 + 7.5, qc * 12.0 + 1.9, seed + 223u", "qa * 0.3 + 4.1, qc * 1.0 + 2.6, seed + 307u"):
        assert literal in CIRRUS_HLSL, literal
    assert CIRRUS_HLSL.count("Perlin2(") == 1 + 5 + 2 + 1   # the definition, Streaks, Fibres, Ends: 32 hashes


@NEEDS_CXX
def test_the_shader_field_is_the_pythons(tmp_path):
    """FCirrusNoise (cirrus.hlsl) compiled as C++ with HLSL's uint, asuint and
    intrinsics: Streaks, Fibres and Ends are cirrus_streaks, cirrus_fibres and
    cirrus_ends to single precision."""
    struct = CIRRUS_HLSL[CIRRUS_HLSL.index("struct FCirrusNoise"):CIRRUS_HLSL.index("\n};\n") + 4]
    shims = r"""
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
using uint = uint32_t;
static float min(float a, float b) { return a < b ? a : b; }
static float max(float a, float b) { return a > b ? a : b; }
static float clamp(float v, float a, float b) { return min(max(v, a), b); }
static float saturate(float v) { return clamp(v, 0.0f, 1.0f); }
static float lerp(float a, float b, float t) { return a + (b - a) * t; }
static uint asuint(int v) { uint u; std::memcpy(&u, &v, 4); return u; }
"""
    points = [(0.3, 0.7), (12.25, -3.5), (-41.3, 18.9), (517.6, 902.1), (-0.01, 59.99)]
    main = "int main() { FCirrusNoise N;\n" + "".join(
        f"printf(\"%.9g %.9g %.9g\\n\", (double)N.Streaks({a}f, {c}f, 17u), (double)N.Fibres({a}f, {c}f, 17u), "
        f"(double)N.Ends({a}f, {c}f, 17u));\n" for a, c in points) + "return 0; }\n"
    (tmp_path / "cirrus.cpp").write_text(shims + struct + "\n" + main, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-o", str(tmp_path / "cirrus"), str(tmp_path / "cirrus.cpp")],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(tmp_path / "cirrus")], check=True, capture_output=True, text=True).stdout.split()
    import struct as st
    for i, (a, c) in enumerate(points):
        fa, fc = (st.unpack("f", st.pack("f", v))[0] for v in (a, c))
        assert float(out[3 * i]) == pytest.approx(ci.cirrus_streaks(fa, fc), abs=2e-4), (a, c)
        assert float(out[3 * i + 1]) == pytest.approx(ci.cirrus_fibres(fa, fc), abs=2e-4), (a, c)
        assert float(out[3 * i + 2]) == pytest.approx(ci.cirrus_ends(fa, fc), abs=2e-4), (a, c)


# -- the material, the shader and the C++ agree ---------------------------------------------------

def test_the_shader_inputs_are_the_scripts_and_the_cpp_sets_them():
    scalars = _script_value("WORLD_CIRRUS_SCALARS")
    vectors = _script_value("WORLD_CIRRUS_VECTORS")
    engine = _script_value("WORLD_DISTANT_ENGINE_INPUTS")
    body = CIRRUS_HLSL.split("FCirrusNoise N;")[1]
    for name in tuple(engine) + tuple(scalars) + tuple(vectors):
        assert re.search(rf"//\s+{name}\s", CIRRUS_HLSL), name
        assert re.search(rf"\b{name}\b", body), f"{name} unused in the body"
    assert "WORLD_CIRRUS_INPUTS = WORLD_DISTANT_ENGINE_INPUTS + tuple(WORLD_CIRRUS_SCALARS) + WORLD_CIRRUS_VECTORS" in SCRIPT
    literal = set(re.findall(r'Material->SetScalarParameterValue\(TEXT\("([A-Za-z]+)"\)', APPLY_CIRRUS))
    assert "CirrusLookName(F)" in APPLY_CIRRUS
    assert literal | set(ci.CIRRUS_LOOK) == set(scalars)
    assert set(re.findall(r'Material->SetVectorParameterValue\(TEXT\("([A-Za-z]+)"\)', APPLY_CIRRUS)) == set(vectors)
    # the script's defaults are the Python table's
    assert scalars == ci.material_scalars()
    assert {k: scalars[k] for k in ci.CIRRUS_LOOK} == ci.CIRRUS_LOOK
    assert scalars["Coverage"] == ci.CIRRUS_DEFAULT_COVER and scalars["RadiusKm"] == ci.CIRRUS_RADIUS_KM
    # Advance sets the per-frame ones and records the altitude
    assert 'CirrusSheet.Material->SetScalarParameterValue(TEXT("SheetFade")' in ADVANCE
    assert 'CirrusSheet.Material->SetVectorParameterValue(TEXT("WindOffsetM")' in ADVANCE
    assert "CirrusSheet.Actor->SetActorLocation(FVector(CameraCm.X, CameraCm.Y, Sheet.AltitudeM * WorldCmPerMetre));" in ADVANCE
    assert "CirrusSheetAltitudeM(CameraCm.Z / WorldCmPerMetre)" in ADVANCE
    assert "CloudDriftOffsetMetres(\n\t\t\t\tCirrusDriftMps(DriftMps), DriftFromDeg, TimeSeconds)" in ADVANCE
    for key in ("cirrus_altitude_m", "cirrus_fade"):
        assert f'Frame->SetNumberField(TEXT("{key}")' in ADVANCE, key


def test_the_material_is_unlit_translucent_and_label_safe():
    assert '_world_beauty_material("M_FlightSimCirrus")' in CREATE
    assert "MSM_UNLIT" in CREATE and "BLEND_TRANSLUCENT" in CREATE
    for flag, value in (("two_sided", True), ("use_translucency_vertex_fog", True), ("compute_fog_per_pixel", True),
                        ("apply_cloud_fogging", True), ("allow_translucent_custom_depth_writes", False),
                        ("output_translucent_velocity", False)):
        assert f'set_editor_property("{flag}", {value})' in CREATE, flag
    for node in ("MaterialExpressionSkyAtmosphereLightDirection", "MaterialExpressionSkyAtmosphereLightIlluminance",
                 "MaterialExpressionSkyAtmosphereDistantLightScatteredLuminance"):
        assert node in CREATE, node
    assert 'world_custom(material, lib, "cirrus", unreal.CustomMaterialOutputType.CMOT_FLOAT4' in CREATE
    assert "MP_EMISSIVE_COLOR" in CREATE and "MP_OPACITY" in CREATE
    assert "MP_BASE_COLOR" not in CREATE and "MD_VOLUME" not in CREATE
    assert CREATE.index('world_stamp(material, "M_FlightSimCirrus")') < CREATE.index("finish(material")
    assert "M_FlightSimCirrus" in _script_value("WORLD_BEAUTY_MATERIALS")
    assert _script_value("WORLD_GENERATIONS")["M_FlightSimCirrus"] == "1"
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCirrus"] == "1"
    # the distant sheet's stamps did not move: no shader of theirs changed
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimDistantClouds"] == "5"
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"] == "8"   # sky step 1's wisp (claude/hl-sky)
    calls = re.findall(r"^(create_world_distant_clouds|create_world_cirrus|create_sky_hdri)\(\)", SCRIPT, re.M)
    assert calls == ["create_world_distant_clouds", "create_world_cirrus", "create_sky_hdri"]
    assert (REPO / "assets" / "shaders" / "world" / "cirrus.hlsl").is_file()


def test_the_cpp_sheet_is_beauty_only_label_safe_and_above_the_flight():
    assert "Mesh->SetRenderCustomDepth(false);" in APPLY_CIRRUS
    assert "Mesh->SetCastShadow(false);" in APPLY_CIRRUS
    assert "Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);" in APPLY_CIRRUS
    assert "Mesh->SetTranslucentSortPriority(CirrusSortPriority);" in APPLY_CIRRUS
    assert "Scene.BeautyOnlyActors.Add(Actor);" in APPLY_CIRRUS
    assert "BuildCurvedDisc(Mesh, CirrusRadiusKm);" in APPLY_CIRRUS
    assert "LoadObject<UMaterialInterface>(nullptr, WorldCirrusMaterialPath)" in APPLY_CIRRUS
    assert 'TEXT("/Game/FlightSim/M_FlightSimCirrus.M_FlightSimCirrus")' in CLOUDS_CPP
    # the cover law, the switch and the type switch feed it; nothing drawn below the floor or without the material
    assert "CirrusCover(CirrusSwitch == TEXT(\"off\"), bSwitchCirrus, bFromData, PlanCirrus, Preset, &Source)" in APPLY_CIRRUS
    assert 'const bool bSwitchCirrus = CloudTypeSwitch == TEXT("cirrus");' in APPLY_CIRRUS
    assert "SkyPlanRef->bCloudCoverFromData" in APPLY_CIRRUS and "SkyPlanRef->CloudCirrusCoverage" in APPLY_CIRRUS
    assert "if (Cover < CirrusMinDrawnCover)" in APPLY_CIRRUS
    assert "M_FlightSimCirrus did not load (run scripts/ue_create_materials.py)" in APPLY_CIRRUS
    # recorded, labelled, uncalibrated, unmeasured
    for key in ("switch", "labels", "visual_only", "calibration", "measured", "coverage", "coverage_source",
                "plan_cover_from_data", "cover_law", "altitude_law", "streak_dir_deg", "drift_mps", "look",
                "seed_offset_km", "material", "lighting", "drawn"):
        assert f'TEXT("{key}")' in APPLY_CIRRUS, key
    assert 'Record->SetObjectField(TEXT("cirrus"), Out);' in APPLY_CIRRUS
    assert "UNCALIBRATED: set by probe render on the render machine" in APPLY_CIRRUS and "UNMEASURED" in APPLY_CIRRUS
    # the disc helper: the distant sheet's rings, segments and droop; the distant body itself is untouched
    helper = _body(CLOUDS_CPP, "void BuildCurvedDisc(UProceduralMeshComponent* Mesh, double RadiusKm)", "double WorldNumber(")
    assert "DistantRingRadiusKm(Ring, DistantRings, RadiusKm)" in helper and "DistantDroopM(RingKm)" in helper
    assert "CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);" in helper
    distant = _body(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyDistantClouds(", "bool FFlightSimWorldBeauty::ApplySkyHdri(")
    assert "Cirrus" not in distant
    # Build: parsed with the other look switches, refused by name, applied after the distant sheet and before the HDRI probe
    assert 'FParse::Value(*Switches, TEXT("look-cirrus="), CirrusSwitch);' in BUILD
    assert 'if (CirrusSwitch != TEXT("on") && CirrusSwitch != TEXT("off"))' in BUILD
    assert 'TEXT("world_beauty.cirrus: -look-cirrus=%s is not on or off")' in BUILD
    assert BUILD.index("ApplyDistantClouds(World, Scene, Weather, DistantMode, Seed);") < BUILD.index(
        "ApplyCirrus(World, Scene, Seed);") < BUILD.index("if (!ApplySkyHdri(Scene, SkyHdriName, Params, Error))")
    # the header declares the state, the switch and the method
    assert "struct FCirrusSheetState" in CLOUDS_H and "void ApplyCirrus(" in CLOUDS_H
    assert 'FString CirrusSwitch = TEXT("on");' in CLOUDS_H


def test_the_plan_loader_says_whether_the_cover_came_from_data_and_the_measure_path_is_untouched():
    assert "bool bCloudCoverFromData = false;" in SKY_H
    load = _body(SKY_CPP, "FFlightSimSkyPlan::Load(", "FFlightSimSky::Build(")
    assert 'TryGetObjectField(TEXT("cover_inputs"), CoverInputs)' in load
    build = SKY_CPP[SKY_CPP.index("FFlightSimSky::Build("):]
    assert "Cirrus" not in build and "CoverFromData" not in build
    # the plan writes cover_inputs as an object only from data (core/sky/clouds.py)
    kw = dict(storm=False, weather_date="2024-01-15", instant_utc="2024-01-15T12:00:00Z", lat=40.0, lon=-74.0,
              altitude_msl_m=3000.0, seed=7)
    with_data = plan_cloud_block(cloud_cover={"low": 0.0, "mid": 0.0, "high": 0.45, "total": 0.45}, **kw)
    assert isinstance(with_data["cover_inputs"], dict) and with_data["cirrus_coverage"] == 0.45
    assert with_data["cloud_type"] == "cirrus"
    without = plan_cloud_block(**kw)
    assert without["cover_inputs"] is None and without["cirrus_coverage"] == 0.0
    # with data the host draws the data (a clear upper sky stays clear); without, the default
    assert ci.cirrus_cover("on", False, True, with_data["cirrus_coverage"], "clear") == (0.45, "plan")
    assert ci.cirrus_cover("on", False, True, 0.0, "clear") == (0.0, "plan")
    assert ci.cirrus_cover("on", False, False, without["cirrus_coverage"], "clear") == (ci.CIRRUS_DEFAULT_COVER, "default")


def test_the_switch_is_registered_catalogued_and_documented():
    note = config_surface.by_key("render_switches").note
    assert "-look-cirrus=on|off" in note and "CIRRUS_SWITCH_WORDS" in note
    assert "\nworld_beauty.cirrus:\n" in CATALOG
    assert 'TEXT("world_beauty.cirrus: ' in CLOUDS_CPP
    assert "Sky step 6" in CHECK and "ApplyCirrus" in CHECK
    vfp = (REPO / "docs" / "VISUAL_FIDELITY_PLAN.md").read_text(encoding="utf-8")
    entry = vfp[vfp.index("### Sky step 6"):]
    assert "UNMEASURED" in entry and "UNCALIBRATED" in entry and "VISUAL ONLY" in entry
    assert "-look-cirrus=off" in entry and "visual_fix_round.ps1" in entry and "FLIGHTSIM_SKY=physical" in entry
    assert "BeautyOnlyActors" in entry and "c641a8c4" in entry
    design = (REPO / "docs" / "visual" / "XPLANE_SKY_DESIGN.md").read_text(encoding="utf-8")
    assert "Built (sky step 6" in design
    # procedural only: no new third-party row
    third = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    assert "cirrus" not in third.lower()
