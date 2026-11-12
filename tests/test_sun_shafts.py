"""Sun shafts and sky occlusion (visual overhaul, module sun-shafts-sky-occlusion,
2026-11-09): what must hold without an engine.

* the C++ table (FlightSimSunShafts.cpp, FLIGHTSIM-SUNSHAFTS-PURE block) and the
  Python one (core/scene/sun_shafts.py) are the same numbers, row for row, and
  the same cvar lists (parsed; compiled too where a C++ compiler exists);
* all five world presets are present, a storm darkens the ground with full sky
  AO and no sun-disc bloom, clear and hazy carry the strong atmosphere shadow;
* the interactive tier writes no fog-grid cvar;
* the measure quality cannot reach Apply: the hook is inside
  FFlightSimWorldBeauty::Build, which the commandlet calls only under bBeauty;
* the label captures' show flags are untouched, the effect is value-only;
* every engine symbol and cvar is in scripts/check_bridge_api.sh;
* every constant is labelled UNCALIBRATED.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import sun_shafts as ss
from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
SHAFTS_CPP = (SOURCE / "Private" / "FlightSimSunShafts.cpp").read_text(encoding="utf-8")
SHAFTS_H = (SOURCE / "Public" / "FlightSimSunShafts.h").read_text(encoding="utf-8")
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
COMMANDLET = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
PROBE_LOG = (REPO / "docs" / "visual" / "PROBE_LOG.md").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")

BEGIN = "// FLIGHTSIM-SUNSHAFTS-PURE-BEGIN"
END = "// FLIGHTSIM-SUNSHAFTS-PURE-END"


def _pure():
    return SHAFTS_CPP[SHAFTS_CPP.index(BEGIN) + len(BEGIN):SHAFTS_CPP.index(END)]


def _camel(field):
    return "Field" + "".join(part.capitalize() for part in field.split("_"))


def _cpp_rows():
    rows = {}
    for name, body in re.findall(r"/\* (\w+) \*/\s*\{([^}]*)\}", _pure()):
        rows[name] = [float(v) for v in body.split(",") if v.strip()]
    return rows


def _cpp_cvars(array):
    body = re.search(array + r"\[\] = \{(.*?)\n\t\};", _pure(), re.S).group(1)
    return {name: float(value) for name, value in re.findall(r'\{"([^"]+)", ([-0-9.e]+)\}', body)}


# -- the table ---------------------------------------------------------------------

def test_all_five_presets_in_world_order():
    assert ss.PRESETS == wb.PRESETS == ("clear", "hazy", "overcast", "rain", "storm")
    assert tuple(ss.SHAFT_PRESETS) == ss.PRESETS
    assert tuple(_cpp_rows()) == ss.PRESETS
    for preset in ss.PRESETS:
        assert tuple(ss.SHAFT_PRESETS[preset]) == ss.FIELDS, preset


def test_the_cpp_field_enum_is_the_python_column_order():
    enum = dict((n, int(i)) for n, i in re.findall(r"(Field\w+) = (\d+)", _pure()))
    assert enum.pop("FieldCount") == len(ss.FIELDS)
    assert enum == {_camel(f): i for i, f in enumerate(ss.FIELDS)}


def test_every_cpp_row_is_the_python_row():
    rows = _cpp_rows()
    for preset in ss.PRESETS:
        assert rows[preset] == [ss.SHAFT_PRESETS[preset][f] for f in ss.FIELDS], preset


def test_storm_and_overcast_are_full_sky_ao_with_no_sun_disc_bloom():
    for preset in ("storm", "overcast"):
        row = ss.SHAFT_PRESETS[preset]
        assert row["sky_ao_strength"] == 1.0
        assert row["shaft_bloom_scale"] <= 0.02
    assert ss.SHAFT_PRESETS["storm"]["shaft_bloom_scale"] == 0.0
    assert ss.parameters("storm", "still")["sun"]["light_shaft_bloom"] is False
    assert ss.SHAFT_PRESETS["rain"]["sky_ao_strength"] == 1.0


def test_clear_and_hazy_carry_the_crepuscular_rays():
    for preset in ("clear", "hazy"):
        row = ss.SHAFT_PRESETS[preset]
        assert row["cloud_shadow_on_atmosphere"] == 1.0
        assert 0.15 <= row["shaft_bloom_scale"] <= 0.3
        assert row["sky_ao_strength"] < 1.0
        assert ss.parameters(preset, "interactive")["sun"]["light_shaft_bloom"] is True


def test_values_stay_inside_the_engine_ranges():
    for preset, row in ss.SHAFT_PRESETS.items():
        assert 0.0 <= row["shaft_occlusion_darkness"] <= 1.0, preset
        assert 0.0 <= row["cloud_shadow_on_atmosphere"] <= 1.0
        assert 0.0 <= row["cloud_shadow_on_surface"] <= 1.0
        assert 0.0 <= row["sky_ao_strength"] <= 1.0
        assert row["cloud_shadow_extent_km"] >= 1.0 and row["sky_ao_extent_km"] >= 1.0   # ClampMin 1
        for f in ("cloud_shadow_map_res_scale", "cloud_shadow_ray_sample_scale", "sky_ao_map_res_scale"):
            assert 0.25 <= row[f] <= 8.0, (preset, f)                                     # ClampMin 0.25
        assert 0.0 <= row["sky_ao_aperture_scale"] <= 1.0
        assert row["vfog_grid_px"] >= 1 and row["vfog_grid_z"] >= 1
        assert row["vfog_grid_px"] < 16 and row["vfog_grid_z"] > 64     # finer than the engine's 16 / 64


# -- the cvars ---------------------------------------------------------------------

def test_the_cpp_cvar_lists_are_the_python_lists():
    assert _cpp_cvars("StillCvars") == ss.STILL_CVARS
    assert list(_cpp_cvars("StillCvars")) == list(ss.STILL_CVARS)
    assert _cpp_cvars("InteractiveCvars") == ss.INTERACTIVE_CVARS
    fog = dict(re.findall(r'constexpr const char\* (FogGrid\w+Cvar) = "([^"]+)";', _pure()))
    assert set(fog.values()) == set(ss.VFOG_GRID_CVARS.values())


def test_every_cvar_in_the_cpp_is_in_the_python_lists():
    named = set(re.findall(r'"(r\.[A-Za-z0-9_.]+)"', SHAFTS_CPP))
    known = set(ss.STILL_CVARS) | set(ss.INTERACTIVE_CVARS) | set(ss.VFOG_GRID_CVARS.values())
    assert named and named <= known, named - known
    assert not named & set(ss.DROPPED_CVARS)


def test_the_interactive_tier_sets_no_fog_grid_cvar():
    for preset in ss.PRESETS:
        names = set(ss.parameters(preset, "interactive")["cvars"])
        assert not any(n.startswith("r.VolumetricFog.") for n in names), preset
        still = ss.parameters(preset, "still")["cvars"]
        assert still["r.VolumetricFog.GridPixelSize"] == ss.SHAFT_PRESETS[preset]["vfog_grid_px"]
        assert still["r.VolumetricFog.GridSizeZ"] == ss.SHAFT_PRESETS[preset]["vfog_grid_z"]
    # the C++: the fog grid only on the still branch
    apply = SHAFTS_CPP[SHAFTS_CPP.index("void FFlightSimSunShafts::Apply"):SHAFTS_CPP.index("void FFlightSimSunShafts::Restore")]
    still_branch = apply[apply.index("if (bStill)"):apply.index("else", apply.index("if (bStill)"))]
    assert "FogGridPixelCvar" in still_branch and "FogGridZCvar" in still_branch
    assert apply.count("FogGridPixelCvar") == 1 and apply.count("FogGridZCvar") == 1
    for name in ss.INTERACTIVE_CVARS:
        assert not name.startswith("r.VolumetricFog.")


def test_unknown_inputs_are_refused_in_python():
    with pytest.raises(ValueError):
        ss.parameters("sunny", "still")
    with pytest.raises(ValueError):
        ss.parameters("clear", "fast")


def test_the_cvars_are_saved_and_put_back():
    assert "Saved.Add({Name, Before});" in SHAFTS_CPP
    restore = SHAFTS_CPP[SHAFTS_CPP.index("void FFlightSimSunShafts::Restore"):]
    assert "Variable->Set(*Saved[i].Before, ECVF_SetByCode);" in restore
    assert "Saved.Reset();" in restore
    world_restore = CLOUDS_CPP[CLOUDS_CPP.index("void FFlightSimWorldBeauty::RestoreCvars()"):]
    world_restore = world_restore[:world_restore.index("\n}\n")]
    assert "SunShafts.Restore();" in world_restore   # clouds-sky round 2 restores its own cvar beside it
    teardown = COMMANDLET[COMMANDLET.rindex("WorldBeauty.RestoreCvars();"):]
    assert teardown.index("Scenario.Teardown();") < 200


# -- the record --------------------------------------------------------------------

def test_the_record_is_value_only_and_uncalibrated():
    for preset in ss.PRESETS:
        for tier in ss.TIERS:
            rec = ss.parameters(preset, tier)
            assert rec["pixel_moving"] is False
            assert rec["basis"] == "value-only: radiance, no surface moves"
            assert rec["calibration"] == "UNCALIBRATED"
            assert rec["show_flags"] == {"light_shafts": True, "volumetric_fog": True}
            for key in ("preset", "tier", "sun", "sky_light", "cvars", "show_flags"):
                assert key in rec
    assert 'SetBoolField(TEXT("pixel_moving"), false)' in SHAFTS_CPP
    assert 'TEXT("value-only: radiance, no surface moves")' in SHAFTS_CPP
    assert "UNCALIBRATED" in SHAFTS_CPP and "UNCALIBRATED" in ss.__doc__
    for key in ("sun", "sky_light", "cvars", "show_flags", "preset", "tier"):
        assert f'TEXT("{key}")' in SHAFTS_CPP, key


def test_not_a_pixel_moving_effect():
    from core.capture.beauty_look import PIXEL_MOVING_KEYS
    for key in ("sun_shafts", "light_shafts", "sky_ao", "cloud_shadow"):
        assert key not in PIXEL_MOVING_KEYS, key


def test_a_missing_sun_or_sky_light_is_skipped_not_refused():
    assert 'TEXT("skipped: the scene has no directional sun")' in SHAFTS_CPP
    assert 'TEXT("skipped: the scene has no sky light")' in SHAFTS_CPP
    assert "skipped: %s is not registered" in SHAFTS_CPP
    assert "return false" not in SHAFTS_CPP.split("bool FFlightSimSunShafts::ResolveStillTier")[1].split("void FFlightSimSunShafts::Apply")[1]


# -- the hooks: beauty only --------------------------------------------------------

def test_the_hook_sits_after_the_tiles_inside_build():
    build = CLOUDS_CPP[CLOUDS_CPP.index("bool FFlightSimWorldBeauty::Build("):CLOUDS_CPP.index("void FFlightSimWorldBeauty::ApplyAtmosphere(")]
    tiles = build.index("ApplyTiles(World, Tiles, CardWetness, SunElevationDeg);")
    hook = build.index("SunShafts.Apply(World, Scene, Preset, SunShafts.ResolveStillTier(Params), SunShaftsOut);")
    assert tiles < hook < tiles + 400
    assert 'Record->SetObjectField(TEXT("sun_shafts"), SunShaftsOut);' in build
    assert "FFlightSimSunShafts SunShafts;" in CLOUDS_H
    assert '#include "FlightSimSunShafts.h"' in CLOUDS_H


def test_measure_quality_cannot_reach_apply():
    # Apply is called from one place: FFlightSimWorldBeauty::Build ...
    assert len(re.findall(r"SunShafts\.Apply\(", CLOUDS_CPP)) == 1
    assert "SunShafts" not in COMMANDLET.replace("sun-shafts-sky-occlusion", "")
    # ... which the commandlet calls only with bBeauty first in the condition.
    calls = re.findall(r"if \(([^\n]*)WorldBeauty\.Build\(", COMMANDLET)
    assert calls and all(c.startswith("bBeauty && !") for c in calls), calls
    assert 'const bool bBeauty = Quality == TEXT("beauty") || bPathTrace;' in COMMANDLET


def test_show_flags_are_set_on_the_beauty_capture_only():
    lines = [i for i, line in enumerate(COMMANDLET.splitlines()) if "ShowFlags.SetLightShafts(true)" in line]
    assert len(lines) == 1
    text = COMMANDLET.splitlines()
    assert text[lines[0]].strip() == "Capture->ShowFlags.SetLightShafts(true);"
    assert text[lines[0] + 1].strip() == "Capture->ShowFlags.SetVolumetricFog(true);"
    # inside the bVisual && bBeauty block (after the beauty block opens, before its TSR step)
    at = COMMANDLET.index("Capture->ShowFlags.SetLightShafts(true);")
    opened = COMMANDLET.rindex("if (bVisual && bBeauty)", 0, at)
    assert "BeautyPath = MakeShared<FJsonObject>();" in COMMANDLET[opened:at]
    # the label rule still turns volumetric fog off on every label capture
    configure = COMMANDLET[COMMANDLET.index("auto ConfigureLabelCapture"):COMMANDLET.index("auto MakeDepthCapture")]
    assert "Label->ShowFlags.SetVolumetricFog(false);" in configure
    # the sun's light-shaft bloom adds into SceneColor whenever a view's
    # LightShafts flag is set (default on), so every label capture and the
    # radiometric calibration capture turn it off
    assert "Label->ShowFlags.SetLightShafts(false);" in configure
    assert "CalibrationCapture->ShowFlags.SetLightShafts(false);" in COMMANDLET
    assert 'BeautyFlags->SetBoolField(TEXT("light_shafts"), Capture->ShowFlags.LightShafts != 0);' in COMMANDLET


def test_the_tier_resolution_follows_accumulation():
    tier = SHAFTS_CPP[SHAFTS_CPP.index("bool FFlightSimSunShafts::ResolveStillTier"):SHAFTS_CPP.index("void FFlightSimSunShafts::Apply")]
    for flag in ('TEXT("sun-shafts-tier=")', 'TEXT("FLIGHTSIM_SUN_SHAFTS_TIER")', 'TEXT("still-samples=")',
                 'TEXT("accumulate=")', 'TEXT("pathtrace")'):
        assert flag in tier, flag


# -- the engine surface ------------------------------------------------------------

def test_the_bridge_check_lists_every_symbol_and_cvar():
    block = CHECK[CHECK.index("# -- sun-shafts-sky-occlusion"):CHECK.index("# -- end sun-shafts-sky-occlusion")]
    for symbol in ("SetEnableLightShaftOcclusion", "SetOcclusionMaskDarkness", "SetOcclusionDepthRange",
                   "SetEnableLightShaftBloom", "SetBloomScale", "SetBloomThreshold", "SetBloomMaxBrightness",
                   "CloudShadowOnAtmosphereStrength", "CloudShadowOnSurfaceStrength", "CloudShadowExtent",
                   "CloudShadowMapResolutionScale", "CloudShadowRaySampleCountScale", "bCloudAmbientOcclusion",
                   "CloudAmbientOcclusionStrength", "CloudAmbientOcclusionExtent",
                   "CloudAmbientOcclusionMapResolutionScale", "CloudAmbientOcclusionApertureScale",
                   "MarkRenderStateDirty", "LightShafts,", "VolumetricFog,", "bRealTimeCapture"):
        assert symbol in block, symbol
    checked = set(re.findall(r"^sunshafts_cvar (\S+) ", block, re.M))
    named = set(re.findall(r'"(r\.[A-Za-z0-9_.]+)"', SHAFTS_CPP))
    assert named == checked
    for symbol in re.findall(r"SunLight->(Set\w+)\(", SHAFTS_CPP):
        assert symbol in block, symbol
    for field in re.findall(r"(?:SunLight|Sky)->(Cloud\w+) =", SHAFTS_CPP):
        assert field in block, field


def test_file_unique_names_for_unity_builds():
    assert "namespace {" not in SHAFTS_CPP and "namespace\n{" not in SHAFTS_CPP
    assert "FlightSimSunShaftsPure" in SHAFTS_CPP
    assert "class FLIGHTSIMBRIDGE_API FFlightSimSunShafts" in SHAFTS_H


def test_the_probe_log_names_the_probes():
    section = PROBE_LOG[PROBE_LOG.index("## sun-shafts-sky-occlusion"):]
    for item in ("SceneCapture2D", "HighQualityAerialPerspective", "TimeSlice", "Matterhorn", "Yosemite",
                 "UNCALIBRATED"):
        assert item in section, item


@NEEDS_CXX
def test_the_pure_block_compiles_and_prints_the_python_table(tmp_path):
    main = (
        "int main() {\n"
        "  using namespace FlightSimSunShaftsPure;\n"
        "  for (int p = 0; p < PresetCount; ++p) {\n"
        "    std::printf(\"%s\", PresetName(p));\n"
        "    for (int f = 0; f < FieldCount; ++f) std::printf(\" %.17g\", Value(p, f));\n"
        "    std::printf(\"\\n\");\n"
        "  }\n"
        "  for (int i = 0; i < StillCvarCount; ++i) std::printf(\"still %s %.17g\\n\", StillCvars[i].Name, StillCvars[i].Value);\n"
        "  for (int i = 0; i < InteractiveCvarCount; ++i) std::printf(\"interactive %s %.17g\\n\", InteractiveCvars[i].Name, InteractiveCvars[i].Value);\n"
        "  std::printf(\"fog %s %s\\n\", FogGridPixelCvar, FogGridZCvar);\n"
        "  std::printf(\"clamped %s %.17g\\n\", PresetName(9), Value(9, 0));\n"
        "  return 0;\n"
        "}\n"
    )
    source = tmp_path / "pure.cpp"
    source.write_text("#include <cstdio>\n" + _pure() + "\n" + main, encoding="utf-8")
    binary = tmp_path / "pure"
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-o", str(binary), str(source)],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout.splitlines()
    for p, preset in enumerate(ss.PRESETS):
        name, *values = out[p].split()
        assert name == preset
        assert [float(v) for v in values] == [ss.SHAFT_PRESETS[preset][f] for f in ss.FIELDS]
    still = {l.split()[1]: float(l.split()[2]) for l in out if l.startswith("still ")}
    interactive = {l.split()[1]: float(l.split()[2]) for l in out if l.startswith("interactive ")}
    assert still == ss.STILL_CVARS and interactive == ss.INTERACTIVE_CVARS
    fog = [l for l in out if l.startswith("fog ")][0].split()[1:]
    assert fog == [ss.VFOG_GRID_CVARS["vfog_grid_px"], ss.VFOG_GRID_CVARS["vfog_grid_z"]]
    assert [l for l in out if l.startswith("clamped ")][0] == "clamped clear 0.40000000000000002"
