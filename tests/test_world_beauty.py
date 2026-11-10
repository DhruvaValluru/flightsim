"""The world lane's beauty look (visual overhaul, 2026-11-09): what must hold
without an engine.

* the Python tables (core/scene/world_beauty.py) and the C++ pure blocks
  (FlightSimClouds.cpp, FlightSimGroundDetail.cpp) are the same numbers and the
  same laws: the blocks are COMPILED here with the machine's C++ compiler and
  run against Python;
* the measure quality never reaches the world look (the commandlet's hooks are
  gated on bBeauty / IsBuilt), so Gate 6's renders stay byte-identical;
* every look constant is labelled UNCALIBRATED;
* the material script's parameters, the HLSL inputs and the C++ names agree;
* Cesium is reached only by reflection (no new Cesium symbol is compiled);
* the scatter pins and the fetch script refuse what is not pinned.
"""

import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import world_beauty as wb
from core.scene.rain_field import unit

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
SCATTER_CPP = (SOURCE / "Private" / "FlightSimGroundDetail.cpp").read_text(encoding="utf-8")
TILES_CPP = (SOURCE / "Private" / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
WEATHER_CPP = (SOURCE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
COMMANDLET = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "world"
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end)]


def _compile_and_run(tmp_path, block, main):
    source = tmp_path / "pure.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + main, encoding="utf-8")
    binary = tmp_path / "pure"
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-o", str(binary), str(source)],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()


def _script_dict(name):
    """A literal dict or tuple the material script assigns at top level."""
    import ast
    tree = ast.parse(SCRIPT)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


# -- the Python laws ---------------------------------------------------------------

def test_the_preset_follows_the_card_storm_first():
    assert wb.select_preset(True, 0.0, False, 0.0, 50.0) == "storm"
    assert wb.select_preset(False, 2.0, False, 0.0, 50.0) == "rain"
    assert wb.select_preset(False, 0.0, True, 0.0, 50.0) == "rain"
    assert wb.select_preset(False, 0.0, False, 0.8, 50.0) == "overcast"
    assert wb.select_preset(False, 0.0, False, 0.2, 8.0) == "hazy"
    assert wb.select_preset(False, 0.0, False, 0.2, 0.0) == "clear"   # not stated is not hazy
    assert wb.select_preset(False, 0.0, False, 0.2, 40.0) == "clear"


def test_the_mie_split_counts_the_extinction_once():
    for visibility in (0.5, 3.0, 10.0, 30.0, 100.0):
        for preset in wb.PRESETS:
            row = wb.ATMOSPHERE[preset]
            split = wb.mie_split(visibility, row["mie_share"], row["mie_cap_per_km"])
            beta = 3.912 / visibility
            assert split["beta_per_km"] == pytest.approx(beta)
            # Rayleigh (the atmosphere's own) + Mie + the fog = beta: counted once
            assert (wb.RAYLEIGH_GREEN_PER_KM + split["mie_extinction_per_km"]
                    + split["fog_factor"] * beta) == pytest.approx(beta)
            assert split["mie_extinction_per_km"] <= row["mie_cap_per_km"] + 1e-12
            assert 0.0 <= split["fog_factor"] <= 1.0
            assert split["mie_scattering_per_km"] + split["mie_absorption_per_km"] == pytest.approx(
                split["mie_extinction_per_km"])
    # the engine's own default single-scattering albedo is kept
    assert 0.003996 / (0.003996 + 0.000444) == pytest.approx(wb.MIE_SINGLE_SCATTER_ALBEDO)


def test_the_cloud_shape_follows_cover_and_thickness():
    assert wb.select_cloud(0.3, 1200.0, "clear") == "cumulus"
    assert wb.select_cloud(0.6, 600.0, "clear") == "stratocumulus"
    assert wb.select_cloud(0.9, 3000.0, "overcast") == "overcast"
    assert wb.select_cloud(0.3, 1200.0, "storm") == "nimbostratus"
    assert wb.select_cloud(0.3, 1200.0, "rain") == "nimbostratus"
    for row in wb.CLOUDS.values():
        assert 0.02 <= row["extinction_per_m"] <= 0.1   # water clouds' order, under the tower's 0.19


def test_the_slab_path_and_the_occlusion_estimate():
    assert wb.slab_path_m(0.0, 3000.0, 3000.0, 1000.0, 2000.0) == pytest.approx(1000.0)
    assert wb.slab_path_m(500.0, 800.0, 400.0, 1000.0, 2000.0) == 0.0
    assert wb.slab_path_m(1500.0, 1500.0, 250.0, 1000.0, 2000.0) == 250.0
    assert wb.slab_path_m(2500.0, 1500.0, 1000.0, 1000.0, 2000.0) == pytest.approx(500.0)
    clear = wb.occlusion(500.0, 600.0, 120.0, 1000.0, 2000.0, 0.5, 0.05, 1.0)
    assert clear["transmittance"] == 1.0 and not clear["flagged"]
    inside = wb.occlusion(1500.0, 1500.0, 120.0, 1000.0, 2000.0, 0.5, 0.05, 1.0)
    assert inside["tau"] == pytest.approx(3.0) and inside["flagged"]


def test_the_sky_pulse_is_one_without_a_flash():
    assert wb.sky_pulse_scale(0.0, 3.0) == 1.0
    assert wb.sky_pulse_scale(1.0, 3.0) == 4.0
    assert wb.sky_pulse_scale(5.0, 3.0) == 4.0
    assert wb.sky_pulse_scale(1.0, 0.0) == 1.0
    assert all(wb.ATMOSPHERE[p]["lightning_sky_gain"] == 0.0 for p in wb.PRESETS if p != "storm")


def test_the_tiles_parameters_take_the_wetter_of_card_and_floor():
    dry = wb.tiles_parameters("clear", 0.0)
    assert dry["Wetness"] == 0.0 and dry["PuddleAmount"] == 0.0
    assert set(dry) == set(wb.WORLD_MPC_SCALARS)
    storm = wb.tiles_parameters("storm", 0.2)
    assert storm["Wetness"] == wb.ATMOSPHERE["storm"]["wetness_floor"]
    assert storm["PuddleAmount"] == pytest.approx(storm["Wetness"] * wb.PUDDLE_SHARE_OF_WETNESS)
    assert wb.tiles_parameters("rain", 0.95)["Wetness"] == 0.95


def test_overrides_are_validated_by_name():
    assert wb.validate_overrides({"atmosphere": {"storm": {"mie_share": 0.4}},
                                  "clouds": {"cumulus": {"extinction_per_m": 0.07}},
                                  "constants": {"cloud_extinction_scale": 2.0}}) == []
    problems = wb.validate_overrides({"atmosphere": {"stormy": {}, "clear": {"mie": 1, "mie_share": "x"}},
                                      "constants": {"nope": 1}, "other": {}})
    assert len(problems) == 5


# -- the C++ pure blocks, compiled ----------------------------------------------------

def test_the_cpp_overrides_loader_refuses_what_validate_overrides_refuses():
    """Review fix: a misspelt section or a bool/string value must be refused by
    the host too, never run silently on the defaults."""
    body = CLOUDS_CPP.split("bool FFlightSimWorldBeauty::LoadOverrides", 1)[1].split(
        "bool FFlightSimWorldBeauty::Build", 1)[0]
    for section in wb.OVERRIDE_SECTIONS:
        assert f'TEXT("{section}")' in body
    assert 'TEXT("constants")' in body
    for name in wb.OVERRIDE_CONSTANTS:
        assert f'TEXT("{name}")' in body, name
    assert "unknown section" in body
    assert body.count("!= EJson::Number") == 2
    assert "!= EJson::Object" in body
    assert wb.validate_overrides({"atmospher": {}})
    assert wb.validate_overrides({"constants": {"cloud_extinction_scale": True}})


def test_every_frame_says_whether_the_cloud_occlusion_is_complete():
    """Review fix: clouds the slab model does not cover make the row a lower bound."""
    assert 'TEXT("cloud_occlusion_complete"), UnmodelledClouds == 0' in CLOUDS_CPP
    assert 'UnmodelledClouds = Kept.Num();' in CLOUDS_CPP


@NEEDS_CXX
def test_the_cpp_world_tables_and_laws_are_the_python_ones(tmp_path):
    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    assert "#include" not in block and "FString" not in block and "TEXT(" not in block
    # every selection threshold sits in the cases on both sides
    cases = [(s, r, p, c, v) for s in (0, 1) for r in (0.0, 3.0) for p in (0, 1)
             for c in (0.0, 0.5, 0.7499, 0.75, 0.8) for v in (0.0, 5.0, 14.999, 15.0, 30.0)]
    clouds = [(c, t, p) for c in (0.2, 0.4999, 0.5, 0.55, 0.85, 0.9) for t in (500.0, 900.0, 900.1, 1500.0)
              for p in range(5)]
    layers = [(c, t, p, f) for c in (-1.0, 0.4, 0.9) for t in (500.0, 1200.0) for p in (0, 3) for f in (0, 1)]
    flags = (0.3, 0.5, 0.9)
    wet_cases = [(p, w) for p in range(5) for w in (0.0, 0.2, 0.7, 0.95, 1.5)]
    albedos = [(s, w) for s in wb.GROUND_ALBEDO_SRGB for w in (0.0, 0.6, 1.0)]
    gs = (0.0, 0.3, 0.5, 0.7, 0.75, 0.9, 0.995)
    slabs = [(0.0, 3000.0, 3000.0, 1000.0, 2000.0), (1500.0, 1500.0, 250.0, 1000.0, 2000.0),
             (2500.0, 1500.0, 1000.0, 1000.0, 2000.0), (100.0, 200.0, 50.0, 1000.0, 2000.0),
             (1200.0, 4000.0, 3500.0, 800.0, 3000.0)]
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "for (int p = 0; p < PresetCount; ++p) for (int f = 0; f < AtmosphereFieldCount; ++f)"
            " printf(\"atm %s %s %.17g\\n\", PresetName(p), AtmosphereFieldName(f), AtmosphereDefault(p, f));",
            "for (int c = 0; c < CloudCount; ++c) for (int f = 0; f < CloudFieldCount; ++f)"
            " printf(\"cld %s %s %.17g\\n\", CloudName(c), CloudFieldName(f), CloudDefault(c, f));"]
    for s, r, p, c, v in cases:
        main.append(f"printf(\"pre %s\\n\", PresetName(SelectPreset({'true' if s else 'false'}, {r!r}, "
                    f"{'true' if p else 'false'}, {c!r}, {v!r})));")
    for c, t, p in clouds:
        main.append(f"printf(\"shape %s\\n\", CloudName(SelectCloud({c!r}, {t!r}, {p})));")
    for v in (0.3, 4.0, 12.0, 40.0, 300.0):
        main.append(f"{{ FMieSplit S = MieSplit({v!r}, 0.6, 0.6); printf(\"mie %.17g %.17g %.17g %.17g %.17g\\n\","
                    " S.BetaPerKm, S.MieExtinctionPerKm, S.MieScatteringPerKm, S.MieAbsorptionPerKm, S.FogFactor); }")
    for a, b, length, base, top in slabs:
        for flag in flags:
            main.append(f"{{ FOcclusion O = Occlusion({a!r}, {b!r}, {length!r}, {base!r}, {top!r}, 0.4, 0.05, 1.0, {flag!r});"
                        " printf(\"occ %.17g %.17g %.17g %d\\n\", O.PathM, O.Tau, O.Transmittance, O.bFlagged ? 1 : 0); }")
    for c, t, p, f in layers:
        main.append(f"{{ double Cv = 0.0; int S = LayerCoverAndShape({c!r}, {t!r}, {p}, {'true' if f else 'false'},"
                    " nullptr, &Cv); printf(\"layer %.17g %s\\n\", Cv, CloudName(S)); }")
    for s, w in albedos:
        main.append(f"{{ int R[3]; GroundAlbedoSrgb(GroundSurfaceIndex(\"{s}\"), {w!r}, R);"
                    " printf(\"albedo %d %d %d\\n\", R[0], R[1], R[2]); }")
    main.append("printf(\"albedo_unknown %d\\n\", GroundSurfaceIndex(\"volcanic\"));")
    for g in gs:
        main.append(f"printf(\"fogexp %.17g\\n\", FogDirectionalExponentForG({g!r}));")
    main.append("for (int i = 0; i < StormWordCount; ++i) printf(\"storm %s\\n\", StormWord(i));")
    main.append("printf(\"isstorm %d %d %d\\n\", IsStormWord(\"tornado\") ? 1 : 0, IsStormWord(\"rain\") ? 1 : 0,"
                " IsStormWord(nullptr) ? 1 : 0);")
    main.append("printf(\"tiles %.17g %.17g %.17g %d\\n\", TilesDehazeDefault, TilesSaturationDefault, WetDarkening,"
                " SunPerPixelTransmittance ? 1 : 0);")
    for seed in (0, 7, 123456789):
        main.append(f"{{ double K[3]; CloudSeedOffsetKm({seed}ull, K); printf(\"seed %.17g %.17g %.17g\\n\", K[0], K[1], K[2]); }}")
    for flash, gain in ((0.0, 3.0), (0.5, 3.0), (2.0, 3.0), (1.0, 0.0)):
        main.append(f"printf(\"pulse %.17g\\n\", SkyPulseScale({flash!r}, {gain!r}));")
    for preset, wet in wet_cases:
        main.append(f"printf(\"wet %.17g\\n\", TilesWetness({wet!r}, AtmosphereDefault({preset}, AtmWetnessFloor)));")
    main.append("printf(\"const %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g %.17g\\n\","
                " HazyVisibilityKm, OvercastCover, CloudOvercastCover, StratocumulusMaxThicknessM,"
                " StratocumulusMinCover, FairCover, FairBaseM, FairTopM, CloudSeedSpanKm,"
                " CloudExtinctionScaleDefault, OcclusionFlagTransmittanceDefault, LightningReferenceLuxDefault,"
                " DetailFadeMDefault, DetailScaleMDefault);")
    main.append("printf(\"puddle %.17g\\n\", PuddleShareDefault);")
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, block, "\n".join(main))

    atm = [line.split() for line in lines if line.startswith("atm ")]
    assert [(p, f) for _, p, f, _ in atm] == [(p, f) for p in wb.PRESETS for f in wb.ATMOSPHERE_FIELDS]
    for _, preset, field, value in atm:
        assert float(value) == wb.ATMOSPHERE[preset][field], (preset, field)
    cld = [line.split() for line in lines if line.startswith("cld ")]
    assert [(c, f) for _, c, f, _ in cld] == [(c, f) for c in wb.CLOUD_PRESETS for f in wb.CLOUD_FIELDS]
    for _, cloud, field, value in cld:
        assert float(value) == wb.CLOUDS[cloud][field], (cloud, field)
    got = [line.split()[1] for line in lines if line.startswith("pre ")]
    assert got == [wb.select_preset(bool(s), r, bool(p), c, v) for s, r, p, c, v in cases]
    got = [line.split()[1] for line in lines if line.startswith("shape ")]
    assert got == [wb.select_cloud(c, t, wb.PRESETS[p]) for c, t, p in clouds]
    for v, line in zip((0.3, 4.0, 12.0, 40.0, 300.0), [l for l in lines if l.startswith("mie ")]):
        ref = wb.mie_split(v, 0.6, 0.6)
        vals = list(map(float, line.split()[1:]))
        assert vals == pytest.approx([ref["beta_per_km"], ref["mie_extinction_per_km"],
                                      ref["mie_scattering_per_km"], ref["mie_absorption_per_km"],
                                      ref["fog_factor"]], rel=1e-14, abs=1e-15)
    occ_cases = [(s, f) for s in slabs for f in flags]
    occ_lines = [l for l in lines if l.startswith("occ ")]
    assert len(occ_lines) == len(occ_cases)
    for ((a, b, length, base, top), flag), line in zip(occ_cases, occ_lines):
        ref = wb.occlusion(a, b, length, base, top, 0.4, 0.05, 1.0, flag_transmittance=flag)
        path, tau, t, flagged = line.split()[1:]
        assert float(path) == pytest.approx(ref["path_m"], rel=1e-14, abs=1e-12)
        assert float(tau) == pytest.approx(ref["tau"], rel=1e-14, abs=1e-15)
        assert float(t) == pytest.approx(ref["transmittance"], rel=1e-14)
        assert bool(int(flagged)) == ref["flagged"]
    got = [(float(l.split()[1]), l.split()[2]) for l in lines if l.startswith("layer ")]
    assert got == [wb.layer_cover_and_shape(None if c < 0 else c, t, wb.PRESETS[p], bool(f)) for c, t, p, f in layers]
    got = [tuple(map(int, l.split()[1:])) for l in lines if l.startswith("albedo ")]
    assert got == [wb.ground_albedo_srgb(s, w) for s, w in albedos]
    assert next(l for l in lines if l.startswith("albedo_unknown ")) == "albedo_unknown 0"
    got = [float(l.split()[1]) for l in lines if l.startswith("fogexp ")]
    assert got == pytest.approx([wb.fog_directional_exponent(g) for g in gs], rel=1e-14)
    assert tuple(l.split()[1] for l in lines if l.startswith("storm ")) == wb.STORM_WORDS
    assert next(l for l in lines if l.startswith("isstorm ")) == "isstorm 1 0 0"
    tiles = next(l for l in lines if l.startswith("tiles ")).split()[1:]
    assert list(map(float, tiles[:3])) == [wb.TILES_DEHAZE, wb.TILES_SATURATION, wb.WET_DARKENING]
    assert bool(int(tiles[3])) is wb.SUN_PER_PIXEL_TRANSMITTANCE
    for seed, line in zip((0, 7, 123456789), [l for l in lines if l.startswith("seed ")]):
        assert list(map(float, line.split()[1:])) == pytest.approx(list(wb.cloud_seed_offset_km(seed)), rel=1e-15)
    pulses = [float(l.split()[1]) for l in lines if l.startswith("pulse ")]
    assert pulses == [wb.sky_pulse_scale(f, g) for f, g in ((0.0, 3.0), (0.5, 3.0), (2.0, 3.0), (1.0, 0.0))]
    wets = [float(l.split()[1]) for l in lines if l.startswith("wet ")]
    assert wets == [wb.tiles_parameters(wb.PRESETS[p], w)["Wetness"] for p, w in wet_cases]
    consts = list(map(float, next(l for l in lines if l.startswith("const ")).split()[1:]))
    assert consts == [wb.HAZY_VISIBILITY_KM, wb.OVERCAST_COVER, wb.CLOUD_OVERCAST_COVER,
                      wb.STRATOCUMULUS_MAX_THICKNESS_M, wb.STRATOCUMULUS_MIN_COVER,
                      wb.FAIR_LAYER["cover"], wb.FAIR_LAYER["base_m"], wb.FAIR_LAYER["top_m"],
                      wb.CLOUD_SEED_SPAN_KM, wb.CLOUD_EXTINCTION_SCALE, wb.OCCLUSION_FLAG_TRANSMITTANCE,
                      wb.LIGHTNING_REFERENCE_LUX, wb.WORLD_MPC_SCALARS["DetailFadeM"],
                      wb.WORLD_MPC_SCALARS["DetailScaleM"]]
    assert float(next(l for l in lines if l.startswith("puddle ")).split()[1]) == wb.PUDDLE_SHARE_OF_WETNESS


@NEEDS_CXX
def test_the_cpp_scatter_law_places_what_the_python_places(tmp_path):
    block = _block(SCATTER_CPP, "// FLIGHTSIM-SCATTER-PURE-BEGIN", "// FLIGHTSIM-SCATTER-PURE-END")
    assert "#include" not in block and "FString" not in block
    seed = 424242
    rows = [(0, 2.0, 0.8, 1.25), (3, 25.0, 0.6, 1.4)]
    main = ["using namespace FlightSimScatterPure;", "int main() {"]
    for s, density, lo, hi in rows:
        main.append(f"{{ long long N = (long long)InstanceCount({density!r}, 300.0, 200.0, 100000);"
                    f" printf(\"count %lld\\n\", N);"
                    f" for (long long i = 0; i < N; ++i) {{ FPlacement P = Place({seed}ull, {s}ull, (uint64_t)i, 300.0, 200.0, {lo!r}, {hi!r});"
                    " printf(\"p %.17g %.17g %.17g %.17g\\n\", P.EastM, P.NorthM, P.YawDeg, P.Scale); } }")
    main += ["printf(\"cap %lld\\n\", (long long)InstanceCount(1.0e6, 1000.0, 1000.0, 5000));",
             "printf(\"excl %d %d\\n\", Excluded(10.0, 0.0, 0.0, 0.0, 150.0) ? 1 : 0, Excluded(200.0, 0.0, 0.0, 0.0, 150.0) ? 1 : 0);",
             "printf(\"slope %d %d\\n\", SlopeAccepted(0.9, 32.0) ? 1 : 0, SlopeAccepted(0.8, 32.0) ? 1 : 0);",
             "{ double H[5] = {10.0, 10.5, 11.0, 9.8, 10.2}; double R[3] = {10.0, 14.0, 10.0};"
             " printf(\"step %d %d %d\\n\", StepAccepted(H, 5, 2.5) ? 1 : 0, StepAccepted(R, 3, 2.5) ? 1 : 0, StepAccepted(H, 0, 2.5) ? 1 : 0); }",
             f"printf(\"unit %.17g %.17g\\n\", Unit({seed}ull, 5ull, 2ull), Unit(0ull, 0ull, 0ull));",
             "return 0; }"]
    lines = _compile_and_run(tmp_path, block, "\n".join(main))
    counts = [int(l.split()[1]) for l in lines if l.startswith("count ")]
    assert counts == [wb.instance_count(d, 300.0, 200.0, 100000) for _, d, _, _ in rows]
    placed = [list(map(float, l.split()[1:])) for l in lines if l.startswith("p ")]
    ref = [wb.placement(seed, s, i, 300.0, 200.0, lo, hi)
           for (s, d, lo, hi), n in zip(rows, counts) for i in range(n)]
    assert len(placed) == len(ref) > 50
    for got, want in zip(placed, ref):
        assert got == pytest.approx(list(want), rel=1e-15, abs=1e-12)
    assert next(l for l in lines if l.startswith("cap ")) == "cap 5000"
    assert next(l for l in lines if l.startswith("excl ")) == "excl 1 0"
    assert next(l for l in lines if l.startswith("slope ")) == "slope 1 0"
    assert next(l for l in lines if l.startswith("step ")) == "step 1 0 0"
    u = list(map(float, next(l for l in lines if l.startswith("unit ")).split()[1:]))
    assert u == [unit(seed, 5, 2), unit(0, 0, 0)]


# -- measure stays untouched; the hooks are small ---------------------------------------

def test_the_measure_quality_never_reaches_the_world_look():
    build = [m.start() for m in re.finditer(r"WorldBeauty\.Build\(", COMMANDLET)]
    advance = [m.start() for m in re.finditer(r"WorldBeauty\.Advance\(", COMMANDLET)]
    assert len(build) == 1 and len(advance) == 1
    assert COMMANDLET[build[0] - 40:build[0]].endswith("if (bBeauty && !")
    assert "if (WorldBeauty.IsBuilt())" in COMMANDLET[advance[0] - 60:advance[0]]
    # the hooks are the only world-lane lines in the commandlet
    assert COMMANDLET.lower().count("world lane hook") == 4
    # after the tiles exist (the scatter traces them) and before the label groups
    # (the scatter is in the labels) and the cloud-material check (the beauty cloud
    # material is checked like every other)
    assert COMMANDLET.index("GoogleTiles.Enable(") < build[0]
    assert build[0] < COMMANDLET.index("TMap<int32, int32> StencilCounts;")
    assert build[0] < COMMANDLET.index("FFlightSimWeather::VerifyCloudMaterials(World")
    # per frame: after the weather (its flash) and before any capture
    assert COMMANDLET.index("Weather.Advance(WeatherView);") < advance[0]
    assert advance[0] < COMMANDLET.index("// I6: the velocity pass renders FIRST")


def test_every_look_constant_is_labelled_uncalibrated():
    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    assert block.count("UNCALIBRATED: set by probe render on the render machine") >= 3
    assert "UNCALIBRATED: set by probe render on the render machine" in CLOUDS_CPP.split(
        "WorldCloudViewSampleScale")[0]
    for name in ("cloud_layers", "tiles_base_colour", "tiles_normal", "tiles_roughness"):
        assert "UNCALIBRATED" in (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8"), name
    text = (REPO / "core" / "scene" / "world_beauty.py").read_text(encoding="utf-8")
    assert text.count("UNCALIBRATED") >= 6


def test_cesium_is_reached_only_by_reflection():
    beauty = TILES_CPP[TILES_CPP.index("FFlightSimGoogleTiles::ApplyBeautyLook"):]
    includes = set(re.findall(r'#include "(Cesium[A-Za-z0-9]+\.h)"', TILES_CPP))
    assert includes == {"Cesium3DTileset.h", "CesiumCamera.h", "CesiumCameraManager.h", "CesiumGeoreference.h"}
    assert 'FindFunction(FName(TEXT("SetMaterial")))' in beauty
    assert 'FindFProperty<FObjectProperty>(Class, TEXT("Material"))' in beauty
    assert 'FindFProperty<FBoolProperty>(Class, TEXT("GenerateSmoothNormals"))' in beauty
    assert "UNVERIFIED" in beauty
    # no Cesium member is called by name beyond the ones the existing code uses
    assert not re.search(r"Tiles->(SetMaterial|GenerateSmoothNormals|SetGenerateSmoothNormals)\(", beauty)
    assert "#if WITH_FLIGHTSIM_CESIUM" in beauty
    # the tiles are never turned off from here
    assert "SetActorHiddenInGame" not in beauty and "Requested()" not in beauty


def test_the_weather_hooks_are_beauty_only_and_outside_the_compiled_port():
    port = WEATHER_CPP[WEATHER_CPP.index("uint64 FFlightSimWeather::SplitMix64"):
                       WEATHER_CPP.index("bool FFlightSimWeather::ParseFlash")]
    assert "ApplyBeautyRainReadability" not in port
    assert "LastFlashLuxValue = FlashLux;" in WEATHER_CPP
    assert CLOUDS_CPP.count("Weather.ApplyBeautyRainReadability(") == 1


# -- the materials, the shaders and the C++ agree ---------------------------------------

def test_the_collection_is_the_python_contract():
    assert _script_dict("WORLD_COLLECTION_SCALARS") == wb.WORLD_MPC_SCALARS
    assert _script_dict("WORLD_COLLECTION") == wb.WORLD_MPC == "MPC_FlightSimWorld"
    for name in wb.WORLD_MPC_SCALARS:
        assert f'TEXT("{name}")' in CLOUDS_CPP, name
    assert "/Game/FlightSim/MPC_FlightSimWorld.MPC_FlightSimWorld" in CLOUDS_CPP


def test_the_cloud_material_parameters_are_the_ones_the_cpp_sets():
    scalars = _script_dict("WORLD_CLOUD_SCALARS")
    vectors = _script_dict("WORLD_CLOUD_VECTORS")
    inputs = _script_dict("WORLD_CLOUD_INPUTS")
    set_scalars = set(re.findall(r'State\.Material->SetScalarParameterValue\(TEXT\("([A-Za-z]+)"\)', CLOUDS_CPP))
    set_vectors = set(re.findall(r'(?:State\.|Layer\.)Material->SetVectorParameterValue\(TEXT\("([A-Za-z]+)"\)',
                                 CLOUDS_CPP))
    assert set_scalars == set(scalars)
    assert set_vectors == set(vectors)
    assert set(inputs) == set(scalars) | set(vectors) | {"WorldPos", "NormAlt"}
    hlsl = (SHADERS / "cloud_layers.hlsl").read_text(encoding="utf-8")
    for name in inputs:
        assert re.search(rf"//\s+{name}\s", hlsl), name
    # the defaults are the cumulus row's (a material with nothing set draws cumulus)
    cumulus = wb.CLOUDS["cumulus"]
    assert scalars["Coverage"] == cumulus["default_cover"]
    assert scalars["ExtinctionPerM"] == cumulus["extinction_per_m"]
    assert scalars["ShapeScaleKm"] == cumulus["shape_scale_km"]
    # flagged for the volumetric cloud, or the engine asserts (docs/WEATHER.md)
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    assert "material.set_editor_property(STORM_USAGE_PROPERTY, True)" in create
    assert "MD_VOLUME" in create and "storm_scattering(" in create
    assert '"NormAltitudeInLayer"' in create
    # round 2: the new shader reaches a machine that built round 1 (stamped, stale rebuilt)
    assert int(_script_dict("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"]) >= 2
    assert create.index('world_stamp(material, "M_FlightSimCloudLayers")') < create.index("finish(material")
    beauty = SCRIPT[SCRIPT.index("def _world_beauty_material"):SCRIPT.index("def world_shader")]
    assert "world_graph_stale(name) or rebuild_requested(name)" in beauty


def test_the_tiles_shaders_read_what_the_script_wires():
    inputs = _script_dict("WORLD_TILES_INPUTS")
    shared = None
    for name, pins in inputs.items():
        hlsl = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        for pin in pins:
            assert re.search(rf"//\s+{pin}\s", hlsl), (name, pin)
        noise = hlsl[hlsl.index("// shared: world noise"):hlsl.index("// end shared")]
        shared = noise if shared is None else shared
        assert noise == shared, f"{name}: the shared noise differs"
        assert "static const" not in hlsl and "float flat" not in hlsl
    # tiles-delight: AlbedoLow is a texture sample, its knee a material scalar (not the collection's)
    local = {"AlbedoLow"} | set(_script_dict("WORLD_TILES_DELIGHT_SCALARS"))
    for pin in {p for pins in inputs.values() for p in pins} - {"Albedo", "WorldPos", "CameraPos", "NormalWS"} - local:
        assert pin in wb.WORLD_MPC_SCALARS, pin


def test_the_material_script_calls_its_world_creators_in_order():
    ours = ("create_world_collection", "create_world_cloud_layers", "create_world_tiles_beauty")
    calls = [c for c in re.findall(r"^(create_world_[a-z_]+)\(\)$", SCRIPT, re.M) if c in ours]
    assert calls == ["create_world_collection", "create_world_cloud_layers", "create_world_tiles_beauty"]
    assert SCRIPT.index("# == WORLD LANE") < SCRIPT.index("# == END WORLD LANE") < SCRIPT.index("_FAILED = []")


def test_the_bridge_check_lists_the_world_symbols():
    world = CHECK[CHECK.index("# -- world lane"):CHECK.index("# -- plugin dependencies")]
    for symbol in ("SetMieScatteringScale", "SetVolumetricFog", "bCastShadowsOnAtmosphere",
                   "SetbUsePerSampleAtmosphericLightTransmittance", "GetParameterCollectionInstance",
                   "LineTraceSingleByChannel", "UpdateInstanceTransform", "FindFProperty", "ProcessEvent",
                   "UMaterialExpressionCloudSampleAttribute", "GetCloudSampleNormAltitudeInLayer"):
        assert symbol in world, symbol


# -- the scatter sidecar, the pins and the fetch script -----------------------------------

def test_the_pins_are_cc0_with_the_roots_verified():
    pins = wb.load_pins()
    assert pins["format"] == "flightsim.scatter_pins"
    used = {s["id"] for biome in wb.BIOMES.values() for s in biome["species"]}
    assert used <= set(pins["assets"])
    for asset_id, pin in pins["assets"].items():
        assert pin["licence"] == "CC0-1.0", asset_id
        assert pin["root"]["url"].startswith("https://dl.polyhaven.org/"), asset_id
        assert re.fullmatch(r"[0-9a-f]{64}", pin["root"]["sha256"]), asset_id
        assert re.fullmatch(r"[0-9a-f]{32}", pin["root"]["md5"]), asset_id
        assert all(re.fullmatch(r"[0-9a-f]{32}", f["md5"]) for f in pin["includes"].values())
    # 2026-11-09 pin audit: every file under 50 MB was fetched, md5-checked and
    # sha256-pinned; three tree meshes (fir 478 MB, jacaranda 208 MB, pine
    # 949 MB) were not, carry an UNVERIFIED status saying why, and are drawn as
    # nothing until the fetch script runs.
    complete = {a for a, pin in pins["assets"].items() if wb.pin_complete(pin)}
    assert complete == {"shrub_02", "rock_moss_set_01", "grass_medium_01", "namaqualand_boulder_02",
                        "wild_rooibos_bush", "quiver_tree_01", "searsia_lucida"}
    for asset_id, pin in pins["assets"].items():
        for file_pin in pin["includes"].values():
            if file_pin.get("sha256") is None:
                assert file_pin["sha256_status"].startswith("UNVERIFIED: "), asset_id
            else:
                assert re.fullmatch(r"[0-9a-f]{64}", file_pin["sha256"]), asset_id
                assert "sha256_status" not in file_pin, asset_id


def test_the_sidecar_draws_nothing_until_pinned():
    sidecar = wb.scatter_sidecar("forest", 7)
    assert sidecar["format"] == "flightsim.ground_scatter" and sidecar["version"] == 1
    assert sidecar["visual_only"] is True
    pinned = {s["id"]: s["pinned"] for s in sidecar["species"]}
    assert pinned["fir_tree_01"] is False and pinned["jacaranda_tree"] is False   # not fetched
    assert pinned["shrub_02"] is True
    assert all(s["licence"] == "CC0-1.0" and s["source_url"] for s in sidecar["species"])
    # the C++ reads every key the sidecar writes
    for key in ("max_slope_deg", "step_reject_m", "probe_offset_m", "sink_m", "resnap_radius_m",
                "trace_up_m", "trace_down_m", "centre_east_m", "half_north_m", "radius_m",
                "density_per_ha", "scale_min", "scale_max", "cull_end_m", "max_instances", "pinned",
                "sha256", "licence", "source_url", "mesh"):
        assert f'TEXT("{key}")' in SCATTER_CPP, key
    assert 'ScatterFormat = TEXT("flightsim.ground_scatter")' in SCATTER_CPP
    assert sum(s["max_instances"] >= 0 for s in sidecar["species"]) == len(sidecar["species"])


def test_a_complete_pin_is_drawn_and_placements_are_reproducible():
    pins = wb.load_pins()
    pin = json.loads(json.dumps(pins["assets"]["shrub_02"]))
    for f in pin["includes"].values():
        f["sha256"] = "a" * 64
    assert wb.pin_complete(pin)
    pins["assets"]["shrub_02"] = pin
    sidecar = wb.scatter_sidecar("forest", 11, pins=pins, region={"half_east_m": 200.0, "half_north_m": 200.0})
    index = [s["id"] for s in sidecar["species"]].index("shrub_02")
    assert sidecar["species"][index]["pinned"]
    first = wb.placements(sidecar, index)
    assert first == wb.placements(sidecar, index)
    assert all(math.hypot(e, n) >= sidecar["exclusion"]["radius_m"] for e, n, _, _ in first)
    other = wb.placements(wb.scatter_sidecar("forest", 12, pins=pins,
                                             region={"half_east_m": 200.0, "half_north_m": 200.0}), index)
    assert first != other


def test_the_fetch_script_verifies_and_pins(tmp_path):
    from scripts import fetch_scatter_assets as fetch

    blobs = {"https://x/root.gltf": b"{}", "https://x/a.bin": b"bin", "https://x/t.jpg": b"jpg"}
    pin = {"licence": "CC0-1.0",
           "root": {"path": "m.gltf", "url": "https://x/root.gltf", "md5": hashlib.md5(b"{}").hexdigest(),
                    "sha256": hashlib.sha256(b"{}").hexdigest(), "size": 2},
           "includes": {"m.bin": {"url": "https://x/a.bin", "md5": hashlib.md5(b"bin").hexdigest(),
                                  "sha256": None, "size": 3},
                        "textures/t.jpg": {"url": "https://x/t.jpg", "md5": hashlib.md5(b"jpg").hexdigest(),
                                           "sha256": None, "size": 3}},
           "total_bytes": 8}
    pins_path = tmp_path / "pins.json"
    pins_path.write_text(json.dumps({"assets": {"m": pin}}), encoding="utf-8")
    assert fetch.main(["--write-pins"], fetch=blobs.__getitem__, pins_path=pins_path,
                      out_dir=tmp_path / "out") == 0
    written = json.loads(pins_path.read_text(encoding="utf-8"))["assets"]["m"]
    assert written["includes"]["m.bin"]["sha256"] == hashlib.sha256(b"bin").hexdigest()
    assert (tmp_path / "out" / "m" / "textures" / "t.jpg").read_bytes() == b"jpg"
    assert wb.pin_complete(written)

    bad = json.loads(json.dumps(pin))
    bad["includes"]["m.bin"]["md5"] = "0" * 32
    with pytest.raises(fetch.ScatterAssetError, match="scatter.md5"):
        fetch.fetch_asset("m", bad, tmp_path / "o2", blobs.__getitem__)
    changed = json.loads(json.dumps(written))
    changed["includes"]["m.bin"]["sha256"] = "f" * 64
    with pytest.raises(fetch.ScatterAssetError, match="scatter.sha256"):
        fetch.fetch_asset("m", changed, tmp_path / "o3", blobs.__getitem__)
    nc = json.loads(json.dumps(pin))
    nc["licence"] = "CC-BY-NC-4.0"
    with pytest.raises(fetch.ScatterAssetError, match="scatter.licence"):
        fetch.fetch_asset("m", nc, tmp_path / "o4", blobs.__getitem__)
    escape = json.loads(json.dumps(pin))
    escape["includes"] = {"../evil.bin": escape["includes"]["m.bin"]}
    with pytest.raises(fetch.ScatterAssetError, match="scatter.path"):
        fetch.fetch_asset("m", escape, tmp_path / "o5", blobs.__getitem__)


def test_the_sidecar_cli_writes_a_readable_file(tmp_path):
    out = tmp_path / "scatter.json"
    assert wb.main(["--biome", "desert", "--seed", "3", "--half-m", "500", "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["biome"] == "desert" and doc["region"]["half_east_m"] == 500.0
    assert wb.sidecar_sha256(doc) == hashlib.sha256(wb.dumps(doc).encode("utf-8")).hexdigest()


# -- fix pass (2026-11-09): one source of truth per shared quantity --------------------

WEATHERLOOK_CPP = (SOURCE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
VISUAL_SCENE_H = (SOURCE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")


def test_the_storm_words_are_one_list_tornado_included():
    from core.scene import beauty_look, weather_look
    assert wb.STORM_WORDS == tuple(weather_look.STORMS) == tuple(beauty_look.STORM_EVENTS)
    assert "tornado" in wb.STORM_WORDS and wb.is_storm_word("tornado") and not wb.is_storm_word(None)
    card = {"weather_look": {"storm": "tornado"}}
    assert wb.card_preset(card) == "storm"
    # the C++ preset test reads the list, never the one word
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build"):]
    assert "IsStormWord(TCHAR_TO_ANSI(*StormWordValue)) || Weather.DrawsCell()" in build
    assert 'WorldString(WeatherLook, TEXT("storm")) == TEXT("thunderstorm") ||' not in build


def test_one_storm_and_one_lightning_clock():
    """With the storm weather's cell drawn, the weather look's shafts, bolt and
    schedule stand down."""
    assert "bool bSkipStormLook = false;" in VISUAL_SCENE_H
    assert 'Storm == TEXT("thunderstorm") && Options.bSkipStormLook' in WEATHERLOOK_CPP
    assert "SceneOptions.bSkipStormLook = SceneOptions.bSkipRainParticles &&" in COMMANDLET
    assert 'bLookLightning = StormWordValue == TEXT("thunderstorm") && !Weather.DrawsCell();' in CLOUDS_CPP


def test_the_world_inputs_survive_a_w3_look_block():
    card = {
        "look": {"night": False, "precipitation": {"rate_mmh": 3.0}, "cloud_drift": {"mps": 4.0, "from_deg": 270}},
        "randomization": {"look": {"visibility_km": 9.0, "precipitation": "rain", "precipitation_rate_mmh": 3.0,
                                   "wetness": 0.4,
                                   "clouds": [{"cover": 0.6, "base_m": 900.0, "top_m": 1700.0}]}},
        "weather_look": {"surface": "forest", "seed": 5},
    }
    inputs = wb.card_inputs(card)
    assert inputs["visibility_km"] == card["randomization"]["look"]["visibility_km"]
    assert inputs["card_cover"] == card["randomization"]["look"]["clouds"][0]["cover"]
    assert inputs["precipitation_rain"] and inputs["rain_rate_mmh"] == 3.0 and inputs["wetness"] == 0.4
    assert inputs["surface"] == "forest" and inputs["seed"] == 5
    assert wb.card_preset(card) == "rain"
    night_only = {"look": {"night": True},
                  "randomization": {"look": {"visibility_km": 8.0,
                                             "clouds": [{"cover": 0.8, "base_m": 600.0, "top_m": 1500.0}]}}}
    assert wb.card_preset(night_only) == "overcast"
    night_only["randomization"]["look"]["clouds"][0]["cover"] = 0.3
    assert wb.card_preset(night_only) == "hazy"
    # the host reads key by key, randomization inside the per-key fallback
    body = CLOUDS_CPP[CLOUDS_CPP.index("TSharedPtr<FJsonValue> WorldLookValue"):]
    body = body[:body.index("\n\t}\n")]
    assert 'TEXT("randomization")' in body and "Value->Type == Type" in body
    assert "if (!Look.IsValid())" not in CLOUDS_CPP


def test_the_selection_boundaries_are_pinned():
    assert wb.select_preset(False, 0.0, False, 0.75, 50.0) == "overcast"
    assert wb.select_preset(False, 0.0, False, 0.7499, 50.0) == "clear"
    assert wb.select_preset(False, 0.0, False, 0.0, 15.0) == "clear"
    assert wb.select_preset(False, 0.0, False, 0.0, 14.999) == "hazy"
    assert wb.select_cloud(0.85, 3000.0, "clear") == "overcast"
    assert wb.select_cloud(0.5, 900.0, "clear") == "stratocumulus"
    assert wb.select_cloud(0.5, 900.1, "clear") == "cumulus"
    assert wb.select_cloud(0.4999, 900.0, "clear") == "cumulus"


def test_the_layer_cover_law():
    assert wb.layer_cover_and_shape(None, 1200.0, "clear", False) == (0.35, "cumulus")
    assert wb.layer_cover_and_shape(None, 1200.0, "rain", False) == (0.98, "nimbostratus")
    assert wb.layer_cover_and_shape(0.9, 1200.0, "clear", False) == (0.9, "overcast")
    assert wb.layer_cover_and_shape(None, 1200.0, "clear", True) == (wb.FAIR_LAYER["cover"], "cumulus")
    assert ("State.Shape = LayerCoverAndShape(CardCover, State.TopM - State.BaseM, Preset, bFair, "
            "CloudValues.GetData(),") in CLOUDS_CPP


def test_the_frame_row_uses_the_overridden_constants():
    advance = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::Advance"):]
    assert "CloudExtinctionScale, OcclusionFlagTransmittance)" in advance
    assert "CldExtinctionPerM]" in advance
    assert "CameraCm.Z / WorldCmPerMetre" in advance and "AircraftCm.Z / WorldCmPerMetre" in advance


def test_apply_tiles_maps_the_python_parameters():
    body = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyTiles"):
                      CLOUDS_CPP.index("void FFlightSimWorldBeauty::Advance")]
    mapping = dict(re.findall(r'\{TEXT\("(\w+)"\), ([^}]+)\}', body))
    assert mapping == {"Wetness": "Wetness", "PuddleAmount": "Wetness * PuddleShare", "Dehaze": "TilesDehaze",
                       "Saturation": "TilesSaturation", "DetailStrength": "Row[AtmTilesDetailStrength]",
                       "DetailFadeM": "DetailFadeM", "DetailScaleM": "DetailScaleM",
                       "DelightAmount": "FlightSimTilesDelight::AmountFor(Preset)",
                       "DelightBlueGate": "FlightSimTilesDelight::DelightBlueGate"}
    assert set(mapping) == set(wb.WORLD_MPC_SCALARS)
    # the ground state is set only when the tiles really draw with the beauty material
    assert 'MaterialRoute == TEXT("UFunction SetMaterial") || MaterialRoute == TEXT("UPROPERTY Material")' in body
    assert "bTilesMaterial ? LoadObject<UMaterialParameterCollection>" in body
    # the tileset's grade is one value for every weather
    for preset in wb.PRESETS:
        p = wb.tiles_parameters(preset, 0.0)
        assert p["Dehaze"] == wb.TILES_DEHAZE and p["Saturation"] == wb.TILES_SATURATION


def test_the_drawn_cloud_cover_is_the_stated_cover():
    """The quantile cut: the drawn share of cloud (at a height every shape's
    profile leaves whole, after the erosion) is within 15 % of the stated cover
    for every shape at the covers it is drawn with. The noise's moments and the
    shaping constants are the shader's."""
    import random
    rng = random.Random(11)
    samples = [wb.cloud_shape(rng.uniform(0, 300), rng.uniform(0, 300), rng.uniform(0, 300), 7)
               for _ in range(6000)]
    mean = sum(samples) / len(samples)
    sd = (sum((v - mean) ** 2 for v in samples) / len(samples)) ** 0.5
    assert mean == pytest.approx(wb.CLOUD_FBM_MEAN, abs=0.01)
    assert sd == pytest.approx(wb.CLOUD_FBM_SIGMA, abs=0.006)
    hlsl = (SHADERS / "cloud_layers.hlsl").read_text(encoding="utf-8")
    assert f"const float FBM_MEAN = {wb.CLOUD_FBM_MEAN};" in hlsl
    assert f"const float FBM_SIGMA = {wb.CLOUD_FBM_SIGMA};" in hlsl
    assert f"const float TOP_CUT_SIGMAS = {wb.CLOUD_TOP_CUT_SIGMAS};" in hlsl
    assert f"const float EROSION_CUT_SHARE = {wb.CLOUD_EROSION_CUT_SHARE};" in hlsl
    assert f"const float WISP_HEIGHT = {wb.CLOUD_WISP_HEIGHT};" in hlsl
    assert "4.91 * (pow(p, 0.14) - pow(1.0 - p, 0.14))" in hlsl
    assert "return density * base * ExtinctionPerM * ExtinctionScale;" in hlsl
    for shape, covers in (("cumulus", (0.2, 0.35, 0.5, 0.7)), ("stratocumulus", (0.5, 0.7)),
                          ("nimbostratus", (0.5, 0.7)), ("overcast", (0.95,))):
        row = wb.CLOUDS[shape]
        # 0.25: above every row's bottom_softness, below every row's top rounding
        assert row["bottom_softness"] <= 0.25 <= 1.0 - row["top_rounding"]
        for cover in covers:
            n = 1500
            hits = sum(wb.cloud_density((rng.uniform(0, 500), rng.uniform(0, 500), rng.uniform(1, 3)), 0.25,
                                        cover, row) > 0.0 for _ in range(n))
            assert hits / n == pytest.approx(cover, rel=0.15), (shape, cover, hits / n)


def test_the_cloud_tops_round_and_the_bases_stay_flat():
    """The top rounds by the cut, not by a density fade: the drawn share
    shrinks towards the top (domes) while the base keeps its cover (a flat
    base faded over bottom_softness only)."""
    import random
    row = wb.CLOUDS["cumulus"]

    def share(h, seed):
        rng = random.Random(seed)
        n = 500
        return sum(wb.cloud_density((rng.uniform(0, 200), rng.uniform(0, 200), 1.0), h, 0.35, row) > 0.0
                   for _ in range(n)) / n

    low, mid, high = share(0.1, 3), share(0.3, 3), share(0.9, 3)
    assert low == pytest.approx(mid, abs=0.06)
    assert high < 0.5 * mid
    assert wb.cloud_density((1.0, 1.0, 1.0), 1.0, 0.35, row) == 0.0


@NEEDS_CXX
def test_the_cloud_shader_noise_is_the_pythons(tmp_path):
    """FWorldCloud (cloud_layers.hlsl) compiled as C++ with HLSL's float3,
    asuint and intrinsics: its Shape and Detail are cloud_shape and
    cloud_detail to single precision."""
    hlsl = (SHADERS / "cloud_layers.hlsl").read_text(encoding="utf-8")
    struct = hlsl[hlsl.index("struct FWorldCloud"):hlsl.index("\n};\n") + 4]
    shims = r"""
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
using uint = uint32_t;
struct float3 { float x, y, z; float3() : x(0), y(0), z(0) {}
    float3(float a, float b, float c) : x(a), y(b), z(c) {} };
static float3 operator+(float3 a, float3 b) { return float3(a.x + b.x, a.y + b.y, a.z + b.z); }
static float3 operator-(float3 a, float3 b) { return float3(a.x - b.x, a.y - b.y, a.z - b.z); }
static float3 operator*(float3 a, float s) { return float3(a.x * s, a.y * s, a.z * s); }
static float3 operator/(float3 a, float s) { return float3(a.x / s, a.y / s, a.z / s); }
static float3 floor(float3 a) { return float3(std::floor(a.x), std::floor(a.y), std::floor(a.z)); }
static float dot(float3 a, float3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static float min(float a, float b) { return a < b ? a : b; }
static float max(float a, float b) { return a > b ? a : b; }
static float clamp(float v, float a, float b) { return min(max(v, a), b); }
static float saturate(float v) { return clamp(v, 0.0f, 1.0f); }
static float lerp(float a, float b, float t) { return a + (b - a) * t; }
static uint asuint(int v) { uint u; std::memcpy(&u, &v, 4); return u; }
"""
    points = [(0.3, 0.7, 0.1), (12.25, -3.5, 7.75), (-41.3, 18.9, -2.2), (517.6, 902.1, 333.3)]
    main = "int main() { FWorldCloud C;\n" + "".join(
        f"printf(\"%.9g %.9g\\n\", (double)C.Shape(float3({x}f, {y}f, {z}f), 7u), "
        f"(double)C.Detail(float3({x}f, {y}f, {z}f), 13u));\n" for x, y, z in points) + "return 0; }\n"
    (tmp_path / "cloud.cpp").write_text(shims + struct + "\n" + main, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-o", str(tmp_path / "cloud"), str(tmp_path / "cloud.cpp")],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(tmp_path / "cloud")], check=True, capture_output=True, text=True).stdout.split()
    for i, (x, y, z) in enumerate(points):
        fx, fy, fz = (float(_f32(v)) for v in (x, y, z))
        assert float(out[2 * i]) == pytest.approx(wb.cloud_shape(fx, fy, fz, 7), abs=2e-4), (x, y, z)
        assert float(out[2 * i + 1]) == pytest.approx(wb.cloud_detail(fx, fy, fz, 13), abs=2e-4), (x, y, z)


def _f32(v):
    import struct
    return struct.unpack("f", struct.pack("f", v))[0]


def test_the_dehaze_never_clips_and_every_shader_shares_the_wet_law():
    for a in (0.0, 0.002, 0.01, 0.05, 0.3, 1.0):
        out = wb.tiles_dehaze((a, a, a))
        assert all(0.0 <= c <= a + 1e-12 for c in out)            # never brighter, never negative
        if a > 0.0:
            assert all(c >= wb.TILES_DEHAZE_TOE * a - 1e-15 for c in out)   # a shadow never clips
    assert wb.tiles_dehaze((1.0, 1.0, 1.0)) == pytest.approx((1.0, 1.0, 1.0))
    base = (SHADERS / "tiles_base_colour.hlsl").read_text(encoding="utf-8")
    r, g, b = wb.TILES_HAZE_RGB
    assert f"const float3 HAZE_RGB = float3({r:.3f}, {g:.3f}, {b:.3f});" in base
    assert f"const float DEHAZE_TOE = {wb.TILES_DEHAZE_TOE};" in base
    assert "float3 c = (a - h * a / max(a + k, 1e-6)) / (1.0 - h / (1.0 + k));" in base
    shaders = {name: (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
               for name in ("tiles_base_colour", "tiles_roughness", "scatter_base_colour", "scatter_roughness")}
    pins = {"WET_DARKENING": wb.WET_DARKENING, "PUDDLE_DARKENING": wb.PUDDLE_DARKENING,
            "ROUGHNESS_DRY": wb.ROUGHNESS_DRY, "ROUGHNESS_WET": wb.ROUGHNESS_WET,
            "ROUGHNESS_PUDDLE": wb.ROUGHNESS_PUDDLE}
    seen = set()
    for name, text in shaders.items():
        for const, value in re.findall(r"const float (\w+) = ([0-9.]+);", text):
            if const in pins:
                assert float(value) == pins[const], (name, const)
                seen.add((name, const))
    assert ("scatter_base_colour", "WET_DARKENING") in seen and ("scatter_roughness", "ROUGHNESS_WET") in seen
    assert ("tiles_base_colour", "WET_DARKENING") in seen and ("tiles_roughness", "ROUGHNESS_WET") in seen


def test_the_scatter_reads_the_tiles_ground_state():
    inputs = _script_dict("WORLD_SCATTER_INPUTS")
    for name, pins in inputs.items():
        hlsl = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        for pin in pins:
            assert re.search(rf"//\s+{pin}\s", hlsl), (name, pin)
    assert {"Wetness", "Saturation"} <= {p for pins in inputs.values() for p in pins}
    assert "M_FlightSimScatter" in _script_dict("WORLD_BEAUTY_MATERIALS")
    create = SCRIPT[SCRIPT.index("def create_world_scatter"):SCRIPT.index("# == END WORLD LANE")]
    assert "world_collection_parameter(material, lib, name" in create
    assert "MaterialExpressionPerInstanceFadeAmount" in create and "BLEND_MASKED" in create
    assert re.search(r"^create_world_scatter\(\)$", SCRIPT, re.M)
    assert wb.SCATTER_MATERIAL == "/Game/FlightSim/M_FlightSimScatter.M_FlightSimScatter"
    assert f'TEXT("{wb.SCATTER_MATERIAL}")' in SCATTER_CPP
    sidecar = wb.scatter_sidecar("forest", 3)
    assert sidecar["cull_start_share"] == 0.7 and sidecar["material"] == wb.SCATTER_MATERIAL
    assert all(s["resnap_radius_m"] == s["cull_end_m"] for s in sidecar["species"])
    for key in ("cull_start_share", "resnap_radius_m", "biome"):
        assert f'TEXT("{key}")' in SCATTER_CPP, key
    assert "SetCullDistances(static_cast<int32>(FMath::Min(CullEndCm * CullStartShare" in SCATTER_CPP


def test_the_scatter_is_in_the_labels_and_has_no_collision():
    assert "SetCollisionEnabled(ECollisionEnabled::NoCollision)" in SCATTER_CPP
    assert "BeautyOnlyActors" not in SCATTER_CPP
    assert re.search(r"if \(bVegetation\)\s*\{\s*Holder->Tags\.Add\(FName\(FlightSimWorld::VegetationTag\)\)",
                     SCATTER_CPP)
    assert "Id == FlightSimWorld::VegetationObjectId" in SCATTER_CPP


def test_the_scatter_biome_is_the_card_surface():
    assert wb.scatter_biome_for("forest") == "forest" and wb.scatter_biome_for("snow") is None
    assert "ground_scatter.biome: " in SCATTER_CPP
    catalog = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
    assert re.search(r"^ground_scatter\.biome:$", catalog, re.M)
    assert "carries no scatter species (forest, desert)" in SCATTER_CPP


def test_the_atmosphere_counts_the_haze_once_with_one_phase():
    assert all(wb.ATMOSPHERE[p]["aerial_perspective_scale"] == 1.0 for p in wb.PRESETS)
    assert wb.fog_directional_exponent(0.75) == pytest.approx(2.0)
    assert wb.fog_directional_exponent(0.3) == wb.FOG_EXPONENT_MIN
    body = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyAtmosphere"):
                      CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyClouds")]
    assert "Fog->SetDirectionalInscatteringExponent(static_cast<float>(FogExponent));" in body
    assert "WorldAlbedo(Surface, GroundWetness)" in body
    assert 'static_assert(SunPerPixelTransmittance, ' in body
    ini = (REPO / "ue" / "Config" / "DefaultEngine.ini").read_text(encoding="utf-8")
    assert "r.SupportExpFogMatchesVolumetricFog" not in ini   # the measure renders' fog stays as it was
    # the ground albedo is the surface's, darkened by the tiles' own wet law
    assert wb.ground_albedo_srgb("desert", 0.0) == wb.GROUND_ALBEDO_SRGB["desert"]
    assert all(w < d for w, d in zip(wb.ground_albedo_srgb("desert", 1.0), wb.GROUND_ALBEDO_SRGB["desert"]))
    assert wb.ground_albedo_srgb("volcanic", 0.0) == wb.GROUND_ALBEDO_SRGB["default"]


def test_the_detail_normal_is_micro_relief():
    for preset in wb.PRESETS:
        assert wb.ATMOSPHERE[preset]["tiles_detail_strength"] <= 0.15
    assert wb.WORLD_MPC_SCALARS["DetailFadeM"] <= 500.0
