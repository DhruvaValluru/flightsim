"""Sky step 3 (the owner's X-Plane-12 brief, 2026-11-14): march and sky quality,
tiered, recorded, restored. Under ``-quality=beauty`` FFlightSimWorldBeauty::
ApplyClouds resolves a march TIER from ``-cloud-march=auto|constrained|discrete|
probe`` (auto = the GPU class, as before: FlightSimWorldPure::CloudMarchFor), sets
the tier's cloud component march (CloudMarch: view / shadow sample-count scales,
trace) and the tier's thirteen renderer cvars (CloudCvar / CloudCvarName: the
cloud march's sample caps and distances, the shadow map and sky AO, the sky
atmosphere's aerial-perspective LUT size and the LUT sample counts), each saved
once (SaveWorldCvar / WorldCvarsBefore), recorded [before, read back] under
look_applied.world_beauty.clouds.march.cvars, and put back by RestoreCvars at the
commandlet's teardown. The constrained row is EXACTLY what the render laptop
already draws with (the engine's registration default, or the Cinematic
scalability group's value where that group speaks), so the default render on the
Intel iGPU changes nothing and r87's pinned history stands; the discrete row is
the offline quality for a discrete GPU (none in the project); the probe row is the
constrained class's opt-in raise. These tests pin the C++, the Python twins in
core/scene/world_beauty.py, the engine source, the switch registry, the one-owner
ledger and the docs to one another. UNMEASURED: nothing here was rendered; the
exact Windows commands are in docs/VISUAL_FIDELITY_PLAN.md "Sky step 3"."""
import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import config_surface
from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
PUBLIC = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public"
CPP = PRIVATE / "FlightSimClouds.cpp"
HEADER = PUBLIC / "FlightSimClouds.h"
COMMANDLET = PRIVATE / "FlightSimRenderCommandlet.cpp"
SUN_SHAFTS = PRIVATE / "FlightSimSunShafts.cpp"
HERO = PRIVATE / "FlightSimHeroLighting.cpp"
CHECK = ROOT / "scripts/check_bridge_api.sh"
CATALOG = ROOT / "core/messages/catalog.yaml"
VFP = ROOT / "docs/VISUAL_FIDELITY_PLAN.md"
DESIGN = ROOT / "docs/visual/XPLANE_SKY_DESIGN.md"
# The engine SOURCE on this Mac, read only (never launched; conftest points UE_ROOT
# at a nonexistent path on purpose, so this is the pinned path, as in
# test_cloud_jitter_blue_noise.py). FLIGHTSIM_UE_SOURCE overrides it.
UE_SOURCE = Path(os.environ.get("FLIGHTSIM_UE_SOURCE", "/Users/Shared/Epic Games/UE_5.7"))
RENDERER = UE_SOURCE / "Engine/Source/Runtime/Renderer/Private"
SCALABILITY = UE_SOURCE / "Engine/Config/BaseScalability.ini"

NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")
NEEDS_ENGINE = pytest.mark.skipif(not SCALABILITY.is_file(), reason="no UE 5.7 source on this machine")

TIERS = ("discrete", "integrated", "probe")   # the C++ MarchName order


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(text: str, begin: str, end: str) -> str:
    start = text.index(begin) + len(begin)
    return text[start:text.index(end, start)]


def _compile_and_run(tmp_path, block, main):
    source = tmp_path / "pure.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + main, encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "pure"), str(source)],
                   check=True, capture_output=True, text=True)
    return subprocess.run([str(tmp_path / "pure")], check=True, capture_output=True, text=True).stdout.splitlines()


# -- the pure laws: C++ == Python ----------------------------------------------------

@NEEDS_CXX
def test_the_tiers_the_cvar_table_and_the_switch_law_are_the_python_ones(tmp_path):
    """MarchName / CloudMarch (three rows), CloudCvarFieldName / CloudCvarName /
    CloudCvar (three rows by thirteen fields), MarchSwitchWord and CloudMarchFor
    compiled with g++ and compared with world_beauty's twins, value for value."""
    block = _block(_read(CPP), "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            'printf("counts %d %d %d %d\\n", MarchCount, MarchFieldCount, CloudCvarFieldCount, MarchSwitchWordCount);',
            "for (int m = 0; m < MarchCount; ++m) for (int f = 0; f < MarchFieldCount; ++f)"
            ' printf("march %s %s %.17g\\n", MarchName(m), MarchFieldName(f), CloudMarch(m, f));',
            "for (int f = 0; f < CloudCvarFieldCount; ++f)"
            ' printf("name %s %s\\n", CloudCvarFieldName(f), CloudCvarName(f));',
            "for (int m = 0; m < MarchCount; ++m) for (int f = 0; f < CloudCvarFieldCount; ++f)"
            ' printf("cvar %s %s %.17g\\n", MarchName(m), CloudCvarFieldName(f), CloudCvar(m, f));',
            'for (int w = 0; w < MarchSwitchWordCount; ++w) printf("word %s\\n", MarchSwitchWord(w));']
    for word in list(wb.CLOUD_MARCH_SWITCH_WORDS) + ["fast", ""]:
        for constrained in (0, 1):
            main.append(f'printf("for {word or "-"} {constrained} %d\\n", CloudMarchFor("{word}", {constrained}));')
    main.append('printf("for null 1 %d\\n", CloudMarchFor(nullptr, true));')
    main.append('printf("oob %.17g %.17g %s %s\\n", CloudMarch(3, 0), CloudCvar(0, 13), CloudCvarName(-1), MarchName(7));')
    main.append("return 0; }")
    lines = _compile_and_run(tmp_path, block, "\n".join(main))
    counts = [int(v) for v in next(l for l in lines if l.startswith("counts ")).split()[1:]]
    assert counts == [len(TIERS), len(wb.CLOUD_MARCH_FIELDS), len(wb.CLOUD_CVAR_FIELDS), len(wb.CLOUD_MARCH_SWITCH_WORDS)]
    march = [l.split() for l in lines if l.startswith("march ")]
    assert [(m, f) for _, m, f, _ in march] == [(m, f) for m in TIERS for f in wb.CLOUD_MARCH_FIELDS]
    assert tuple(wb.CLOUD_MARCH) == TIERS
    for _, m, f, value in march:
        assert float(value) == wb.CLOUD_MARCH[m][f], (m, f)
    names = [l.split() for l in lines if l.startswith("name ")]
    assert [f for _, f, _ in names] == list(wb.CLOUD_CVAR_FIELDS)
    assert {f: n for _, f, n in names} == wb.CLOUD_CVAR_NAMES
    cvars = [l.split() for l in lines if l.startswith("cvar ")]
    assert [(m, f) for _, m, f, _ in cvars] == [(m, f) for m in TIERS for f in wb.CLOUD_CVAR_FIELDS]
    assert tuple(wb.CLOUD_CVARS) == TIERS
    for _, m, f, value in cvars:
        assert float(value) == wb.CLOUD_CVARS[m][f], (m, f)
    assert [l.split()[1] for l in lines if l.startswith("word ")] == list(wb.CLOUD_MARCH_SWITCH_WORDS)
    for l in lines:
        if l.startswith("for "):
            _, word, constrained, index = l.split()
            py = wb.cloud_march_for(None if word in ("null",) else ("" if word == "-" else word), constrained == "1")
            assert int(index) == (-1 if py is None else TIERS.index(py)), (word, constrained)
    assert next(l for l in lines if l.startswith("oob ")) == "oob 0 0  discrete"


def test_the_switch_law_in_python():
    """auto follows the GPU class; a named tier is taken on any GPU; another word is None."""
    assert wb.cloud_march_for("auto", True) == "integrated" and wb.cloud_march_for("auto", False) == "discrete"
    assert wb.cloud_march_for(None, True) == "integrated"
    for word in ("constrained", "discrete", "probe"):
        expected = "integrated" if word == "constrained" else word
        assert wb.cloud_march_for(word, True) == wb.cloud_march_for(word, False) == expected
    assert wb.cloud_march_for("fast", False) is None and wb.cloud_march_for("", True) is None
    assert wb.CLOUD_MARCH_SWITCH == "-cloud-march"
    assert wb.CLOUD_MARCH_SWITCH_WORDS == ("auto", "constrained", "discrete", "probe")


# -- the rows ----------------------------------------------------------------------------

def test_the_constrained_row_is_what_the_laptop_already_draws_with():
    """The render laptop (Intel iGPU, D3D11 SM5) is the constrained class. Its
    march row is ef361bd6's (192 / 10 / 80, the r87 pin) and its cvar row repeats
    the value already in force on every beauty render: the Cinematic scalability
    group's where it speaks (the render path applies that group after this lane,
    at scalability priority, which cannot lower a code-priority set), the engine's
    registration default elsewhere. Setting it is a recorded no-op."""
    row = wb.cloud_march(True)
    assert (row["view_samples_max"], row["shadow_samples"], row["tracing_max_distance_km"]) == (192.0, 10.0, 80.0)
    assert wb.CLOUD_MARCH["integrated"] == {"view_sample_count_scale": 2.0, "shadow_sample_count_scale": 1.0,
                                            "tracing_max_distance_km": 80.0}
    assert wb.cloud_march_tier("integrated") == wb.cloud_march(True)
    assert wb.CLOUD_CVARS["integrated"] == wb.cloud_cvars_in_force()
    assert set(wb.CINEMATIC_SKY_CVARS) < set(wb.CLOUD_CVAR_FIELDS)
    for field in wb.CLOUD_CVAR_FIELDS:
        expected = wb.CINEMATIC_SKY_CVARS.get(field, wb.ENGINE_CLOUD_CVAR_DEFAULTS[field])
        assert wb.CLOUD_CVARS["integrated"][field] == expected, field
    # the three the Cinematic group raises above the registration default
    assert wb.CINEMATIC_SKY_CVARS == {"ap_lut_depth_resolution": 32.0, "transmittance_lut_samples": 30.0,
                                      "multiscatter_lut_samples": 20.0}
    for field, value in wb.CINEMATIC_SKY_CVARS.items():
        assert value > wb.ENGINE_CLOUD_CVAR_DEFAULTS[field], field
    # the C++ row carries the same literal
    text = _read(CPP)
    assert "{768.0, 80.0, 15.0, 2.0, 128.0, 2048.0, 10.0, 96.0, 32.0, 32.0, 30.0, 20.0, 150.0},   // constrained: in force today" in text
    assert "{2.0, 1.0, 80.0},   // constrained" in text


def test_the_probe_row_is_the_constrained_row_with_a_shorter_sample_distance_and_more_samples():
    """probe = the constrained cvar row with r.VolumetricCloud.DistanceToSampleMaxCount
    8 km (the engine spreads the sample cap over that distance: a short in-layer
    path gets up to twice the samples), plus the probe march row 288 / 20 / 80,
    under the engine's caps; reachable only by -cloud-march=probe."""
    probe, integrated = wb.CLOUD_CVARS["probe"], wb.CLOUD_CVARS["integrated"]
    assert {f for f in wb.CLOUD_CVAR_FIELDS if probe[f] != integrated[f]} == {"distance_to_sample_max_km"}
    assert probe["distance_to_sample_max_km"] == 8.0 < integrated["distance_to_sample_max_km"] == 15.0
    row = wb.cloud_march_tier("probe")
    assert (row["view_samples_max"], row["shadow_samples"], row["tracing_max_distance_km"]) == (288.0, 20.0, 80.0)
    base = wb.cloud_march_tier("integrated")
    assert row["view_samples_max"] > base["view_samples_max"] and row["shadow_samples"] > base["shadow_samples"]
    assert row["view_samples_max"] <= wb.ENGINE_CLOUD_VIEW_SAMPLE_CAP
    assert row["shadow_samples"] <= wb.ENGINE_CLOUD_SHADOW_SAMPLE_CAP
    # the probe never reaches the laptop on its own: auto is the class
    assert wb.cloud_march_for("auto", True) == "integrated"


def test_the_discrete_row_is_the_offline_quality():
    """Every discrete field is at least the constrained one (at most, where a lower
    value means more samples), the march hits the engine's caps exactly (768 view,
    80 shadow samples) and never exceeds them, the shadow map and sky AO rise, the
    aerial-perspective LUT is longer, deeper and wider. UNMEASURED: no discrete GPU."""
    discrete, integrated = wb.CLOUD_CVARS["discrete"], wb.CLOUD_CVARS["integrated"]
    for field in wb.CLOUD_CVAR_FIELDS:
        if field in wb.CLOUD_CVAR_LOWER_IS_MORE:
            assert discrete[field] <= integrated[field], field
        else:
            assert discrete[field] >= integrated[field], field
    assert {f for f in wb.CLOUD_CVAR_FIELDS if discrete[f] != integrated[f]} == {
        "distance_to_sample_max_km", "shadowmap_ray_sample_max", "shadowmap_max_resolution", "skyao_trace_samples",
        "ap_lut_depth_km", "ap_lut_depth_resolution", "ap_lut_width", "transmittance_lut_samples",
        "multiscatter_lut_samples", "sky_distance_to_sample_max_km"}
    row = wb.cloud_march(False)
    assert (row["view_samples_max"], row["shadow_samples"]) == (wb.ENGINE_CLOUD_VIEW_SAMPLE_CAP,
                                                                 wb.ENGINE_CLOUD_SHADOW_SAMPLE_CAP)
    assert discrete["view_ray_sample_max"] == wb.ENGINE_CLOUD_VIEW_SAMPLE_CAP
    assert discrete["shadow_ray_sample_max"] == wb.ENGINE_CLOUD_SHADOW_SAMPLE_CAP
    assert discrete["ap_lut_depth_km"] / discrete["ap_lut_depth_resolution"] < (
        integrated["ap_lut_depth_km"] / integrated["ap_lut_depth_resolution"])   # finer slices, farther


@NEEDS_ENGINE
def test_the_engine_source_registers_each_cvar_at_the_pinned_default_and_cinematic_raises_three():
    """UE 5.7's VolumetricCloudRendering.cpp / SkyAtmosphereRendering.cpp register
    every name in CLOUD_CVAR_NAMES with ENGINE_CLOUD_CVAR_DEFAULTS' value, and
    BaseScalability.ini's [EffectsQuality@Cine] group sets exactly the three
    CINEMATIC_SKY_CVARS of them (and none of the others)."""
    sources = {"r.VolumetricCloud": _read(RENDERER / "VolumetricCloudRendering.cpp"),
               "r.SkyAtmosphere": _read(RENDERER / "SkyAtmosphereRendering.cpp")}
    for field, name in wb.CLOUD_CVAR_NAMES.items():
        text = sources[name.split(".", 2)[0] + "." + name.split(".", 2)[1]]
        match = re.search(r'TEXT\("' + re.escape(name) + r'"\),\s*([0-9.]+)f?,', text)
        assert match is not None, name
        assert float(match.group(1)) == wb.ENGINE_CLOUD_CVAR_DEFAULTS[field], name
    ini = configparser.RawConfigParser(strict=False, delimiters=("=",), inline_comment_prefixes=(";",))
    ini.optionxform = str
    ini.read_string(_read(SCALABILITY))
    cine = ini["EffectsQuality@Cine"]
    for field, name in wb.CLOUD_CVAR_NAMES.items():
        if field in wb.CINEMATIC_SKY_CVARS:
            assert float(cine[name]) == wb.CINEMATIC_SKY_CVARS[field], name
        else:
            assert name not in cine, name
    assert "ECVF_SetByCode" in _read(UE_SOURCE / "Engine/Source/Runtime/Core/Private/HAL/ConsoleManager.cpp")


@NEEDS_ENGINE
def test_the_sample_distance_also_governs_the_sky_light_capture():
    """Repair round 1 (the must-fix): r.VolumetricCloud.DistanceToSampleMaxCount is
    not confined to the main view. UE 5.7 VolumetricCloudRendering.cpp sets
    CloudGlobalShaderParams.InvDistanceToSampleCountMax ONCE, from that cvar, for
    every trace, and its bIsReflectionRendering block re-derives only SampleCountMax
    and ShadowSampleCountMax (from ReflectionViewSampleCountScale and the
    commandlet's r.VolumetricCloud.ReflectionRaySampleMaxCount caps), never the
    distance; VolumetricCloud.usf then takes StepCount = max(SampleCountMin,
    SampleCountMax x saturate(path x InvDistanceToSampleCountMax)). So the probe
    tier's 8 km lengthens the sky-light capture's march too (up to 15/8 x per short
    in-layer path), in the submission that hung r87 (887a0006). The first record said
    the capture was 'not this table's'; this pins the engine fact behind the fix."""
    text = _read(RENDERER / "VolumetricCloudRendering.cpp")
    sets = re.findall(r"CloudGlobalShaderParams\.InvDistanceToSampleCountMax\s*=\s*([^;]+);", text)
    assert len(sets) == 1, sets
    assert "CVarVolumetricCloudDistanceToSampleMaxCount.GetValueOnAnyThread()" in sets[0]
    assert text.count("InvDistanceToSampleCountMax") == 1   # set once, never re-derived
    block = _block(text, "if (CloudRC.bIsReflectionRendering",
                   "VolumetricCloudParams.EnableAerialPerspectiveSampling")
    assert "VolumetricCloudParams.VolumetricCloud.SampleCountMax =" in block
    assert "VolumetricCloudParams.VolumetricCloud.ShadowSampleCountMax =" in block
    assert "ReflectionViewSampleCountScale" in block
    assert "CVarVolumetricCloudReflectionRaySampleMaxCount" in block
    assert "CVarVolumetricCloudShadowReflectionRaySampleMaxCount" in block
    assert "InvDistanceToSampleCountMax" not in block
    assert "DistanceToSampleMaxCount" not in block
    assert "CloudRC.bIsReflectionRendering = ViewInfo.bIsReflectionCapture;" in text   # the sky-light capture
    usf = _read(UE_SOURCE / "Engine/Shaders/Private/VolumetricCloud.usf")
    assert ("max(RenderVolumetricCloudParameters.SampleCountMin, RenderVolumetricCloudParameters.SampleCountMax"
            " * saturate((TMax - TMin) * RenderVolumetricCloudParameters.InvDistanceToSampleCountMax))") in usf
    # the commandlet's reflection caps are the caps the engine block reads, nothing more
    commandlet = _read(COMMANDLET)
    assert 'TEXT("r.VolumetricCloud.ReflectionRaySampleMaxCount")' in commandlet
    assert 'TEXT("r.VolumetricCloud.Shadow.ReflectionRaySampleMaxCount")' in commandlet


def test_the_record_and_the_docs_say_the_probe_lengthens_the_sky_light_capture():
    """Repair round 1: the record strings (cvars_basis, render_path_owned_basis), the
    CloudCvar comment, world_beauty's CLOUD_CVARS comment and the two docs all state
    that r.VolumetricCloud.DistanceToSampleMaxCount governs the sky-light capture's
    step count too, and none claims the capture is outside the table."""
    cpp = _read(CPP)
    table_comment = _block(cpp, "// Sky step 3: the renderer cvars each tier sets", "constexpr int CloudCvarFieldCount")
    assert "sky-light capture" in table_comment and "InvDistanceToSampleCountMax" in table_comment
    assert "15/8" in table_comment and "887a0006" in table_comment
    cvars_basis = _block(cpp, 'TEXT("cvars_basis"),', 'TEXT("render_path_owned"')
    assert "sky-light capture" in cvars_basis and "InvDistanceToSampleCountMax" in cvars_basis
    assert "887a0006" in cvars_basis and "pass or fail" in cvars_basis
    owned_basis = _block(cpp, 'TEXT("render_path_owned_basis"),', 'Out->SetObjectField(TEXT("march")')
    assert "do NOT isolate" in owned_basis and "InvDistanceToSampleCountMax" in owned_basis
    assert "not this table's" not in cpp
    py = _read(ROOT / "core/scene/world_beauty.py")
    py_comment = _block(py, "#: The rows (C++ CloudCvar).", "CLOUD_CVARS: Dict")
    assert "sky-light capture" in py_comment and "InvDistanceToSampleCountMax" in py_comment
    assert "887a0006" in py_comment
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 3"):]
    assert "InvDistanceToSampleCountMax" in entry and "bIsReflectionRendering" in entry
    assert "also lengthens the sky-light capture's march" in entry
    assert "stay the commandlet's" not in entry
    design = _read(DESIGN)
    built = design[design.index("Built (sky step 3"):]
    assert "Repair round 1" in built and "InvDistanceToSampleCountMax" in built
    check = _read(CHECK)
    assert '"CloudGlobalShaderParams.InvDistanceToSampleCountMax"' in check
    assert "ReflectionViewSampleCountScale," in check
    assert "CloudRC.bIsReflectionRendering = ViewInfo.bIsReflectionCapture;" in check


# -- one owner per cvar ------------------------------------------------------------------

def test_every_world_cvar_has_one_owner():
    """No name in the world lane's table (or its fog-on-all-pixel cvar) is set by the
    sun-shafts lane, the hero-lighting lane or the render commandlet; the render
    path's names the world record lists are exactly the commandlet's sky and cloud
    SetBeautyCvar names, and the world lane never sets one of them."""
    world = set(wb.CLOUD_CVAR_NAMES.values()) | {"r.VolumetricCloud.ApplyFogOnAllPixel"}
    assert len(world) == len(wb.CLOUD_CVAR_FIELDS) + 1
    shafts = set(re.findall(r'\{"(r\.[\w.]+)",\s*[\d.]+\}', _read(SUN_SHAFTS)))
    shafts |= set(re.findall(r'Cvar = "(r\.[\w.]+)";', _read(SUN_SHAFTS)))
    assert shafts, "the sun-shafts cvar tables were not found"
    hero = set(re.findall(r'HeroLightingCvar\(TEXT\("(r\.[\w.]+)"\)', _read(HERO)))
    assert hero
    commandlet_text = _read(COMMANDLET)
    beauty = set(re.findall(r'SetBeautyCvar\(TEXT\("([\w.]+)"\)', commandlet_text))
    assert beauty
    for other, lane in ((shafts, "sun shafts"), (hero, "hero lighting"), (beauty, "render path")):
        assert not (world & other), (lane, sorted(world & other))
    # the render path's sky and cloud names, as the world record lists them
    render_path = {n for n in beauty if n.startswith(("r.SkyAtmosphere", "r.VolumetricCloud", "r.VolumetricRenderTarget"))}
    assert render_path == set(wb.RENDER_PATH_CVARS)
    cpp = _read(CPP)
    listed = re.findall(r'TEXT\("([\w.]+)"\)', _block(cpp, "WorldRenderPathCvars[] = {", "};"))
    assert listed == list(wb.RENDER_PATH_CVARS)
    for name in wb.RENDER_PATH_CVARS:
        assert f'SetWorldCvar(TEXT("{name}")' not in cpp, name
    # the sky capture's own caps stay the commandlet's
    assert "r.VolumetricCloud.ReflectionRaySampleMaxCount" not in world
    assert 'TEXT("r.VolumetricCloud.ReflectionRaySampleMaxCount")' in commandlet_text


# -- the host --------------------------------------------------------------------------------

def test_the_host_resolves_the_tier_sets_saves_restores_and_records():
    """ApplyClouds resolves the tier through CloudMarchFor (the GPU class is still
    read: test_world_beauty's constrained pin), sets every table cvar through
    SetWorldCvar, saves the fog-on-all-pixel cvar through the same array (its
    literal stays within 200 chars of the integrated-GPU guard), records the tier,
    the switch, every [before, read back] pair, the skipped names and the render
    path's names; RestoreCvars walks the array in reverse and the commandlet's
    teardown calls it; the old single-cvar string is gone."""
    cpp = _read(CPP)
    header = _read(HEADER)
    assert "const bool bIntegratedGpu = CloudConstrainedGpu();" in cpp
    assert "const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bIntegratedGpu);" in cpp
    assert "const int32 March = MarchChosen >= 0 ? MarchChosen : (bIntegratedGpu ? MarchIntegrated : MarchDiscrete);" in cpp
    assert "SetWorldCvar(*Name, CloudCvar(March, F), CvarRow, CvarsSkipped);" in cpp
    assert cpp.count("for (int32 F = 0; F < CloudCvarFieldCount; ++F)") == 2
    assert "SaveWorldCvar(WorldCloudFogAllPixelCvar, FogAll);" in cpp
    fog = cpp.index("if (!bIntegratedGpu)")
    assert cpp.index("FogAll->Set(1, ECVF_SetByCode);", fog) - fog < 200
    # the helper: find, skip if unregistered, save once, set at code priority, record the pair
    helper = _block(cpp, "void FFlightSimWorldBeauty::SetWorldCvar(", "void FFlightSimWorldBeauty::ApplyAtmosphere(")
    assert "IConsoleManager::Get().FindConsoleVariable(Name)" in helper
    assert 'TEXT("skipped: %s is not registered")' in helper
    assert "const FString Before = SaveWorldCvar(Name, Variable);" in helper
    assert "Variable->Set(*FString::SanitizeFloat(Value, 0), ECVF_SetByCode);" in helper
    assert "Row->SetArrayField(Name, Pair);" in helper
    save = _block(cpp, "FString FFlightSimWorldBeauty::SaveWorldCvar(", "void FFlightSimWorldBeauty::SetWorldCvar(")
    assert "if (Entry.Name == Name)" in save and "WorldCvarsBefore.Add({FString(Name), Variable->GetString()});" in save
    # restore: reverse walk, then empty
    restore = _block(cpp, "void FFlightSimWorldBeauty::RestoreCvars()", "FString FFlightSimWorldBeauty::SaveWorldCvar(")
    assert "SunShafts.Restore();" in restore
    assert "for (int32 I = WorldCvarsBefore.Num() - 1; I >= 0; --I)" in restore
    assert "Variable->Set(*WorldCvarsBefore[I].Before, ECVF_SetByCode);" in restore
    assert "WorldCvarsBefore.Reset();" in restore
    assert "CloudFogAllPixelBefore" not in cpp and "CloudFogAllPixelBefore" not in header
    assert "TArray<FSavedCvar> WorldCvarsBefore;" in header
    assert "FString SaveWorldCvar(const TCHAR* Name, IConsoleVariable* Variable);" in header
    assert 'FString CloudMarchSwitch = TEXT("auto");' in header
    assert "WorldBeauty.RestoreCvars();" in _read(COMMANDLET)
    # the record
    march = _block(cpp, 'MarchOut->SetStringField(TEXT("path"), ANSI_TO_TCHAR(MarchName(March)));',
                   'Out->SetObjectField(TEXT("march"), MarchOut);')
    for key in ("tier", "switch", "tier_basis", "cvars", "cvars_skipped", "cvar_fields", "cvars_basis",
                "render_path_owned", "render_path_owned_basis"):
        assert f'TEXT("{key}")' in march, key
    assert "UNMEASURED" in march and "UNCALIBRATED" in march
    # the distant sheet reads the same tier
    distant = _block(cpp, "void FFlightSimWorldBeauty::ApplyDistantClouds(", "bool FFlightSimWorldBeauty::ApplySkyHdri(")
    assert "const int32 MarchChosen = CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), bConstrained);" in distant
    assert 'Trace->SetStringField(TEXT("march_tier"), ANSI_TO_TCHAR(MarchName(March)));' in distant
    assert "DistanceToSampleMaxCount, 15 km)" not in cpp   # the basis names the tier's field now


def test_the_switch_is_parsed_refused_registered_and_catalogued():
    cpp = _read(CPP)
    assert 'CloudMarchSwitch = TEXT("auto");' in cpp
    assert 'FParse::Value(*Switches, TEXT("cloud-march="), CloudMarchSwitch);' in cpp
    assert "if (CloudMarchFor(TCHAR_TO_ANSI(*CloudMarchSwitch), false) < 0)" in cpp
    assert "world_beauty.clouds: -cloud-march=%s is not auto, constrained, discrete or probe" in cpp
    note = config_surface.by_key("render_switches").note
    assert "-cloud-march=auto|constrained|discrete|probe" in note and "CLOUD_MARCH_SWITCH_WORDS" in note
    catalog = _block(_read(CATALOG), "world_beauty.clouds:", "world_beauty.distant_clouds:")
    assert "-cloud-march=" in catalog
    for word in wb.CLOUD_MARCH_SWITCH_WORDS:
        assert word in catalog, word


def test_the_measure_path_never_sees_the_table():
    """FlightSimSky.cpp, FlightSimVisualScene.cpp and FlightSimWeather.cpp (every
    quality) name none of the thirteen cvars: a measure render is byte-identical."""
    for name in ("FlightSimSky.cpp", "FlightSimVisualScene.cpp", "FlightSimWeather.cpp"):
        text = _read(PRIVATE / name)
        for cvar in wb.CLOUD_CVAR_NAMES.values():
            assert cvar not in text, (name, cvar)
        assert "SetWorldCvar" not in text and "CloudMarchFor" not in text, name
    assert "exposure_sees_plan_clouds" in _read(CPP)   # the exposure is still the plan's


def test_the_bridge_check_and_the_docs():
    check = _read(CHECK)
    for name in wb.CLOUD_CVAR_NAMES.values():
        assert f'TEXT(\\"{name}\\")' in check, name
    for line in ("r.SkyAtmosphere.AerialPerspectiveLUT.DepthResolution=32.0",
                 "r.SkyAtmosphere.TransmittanceLUT.SampleCount=30.0",
                 "r.SkyAtmosphere.MultiScatteringLUT.SampleCount=20.0"):
        assert line in check, line
    vfp = _read(VFP)
    entry = vfp[vfp.index("### Sky step 3"):]
    assert "UNMEASURED" in entry and "UNCALIBRATED" in entry
    assert "-cloud-march=probe" in entry and "visual_fix_round.ps1" in entry
    assert "887a0006" in entry and "RestoreCvars" in entry
    for name in wb.CLOUD_CVAR_NAMES.values():
        assert name in entry, name
    design = _read(DESIGN)
    assert "Built (sky step 3" in design
    assert "[EffectsQuality@Cine]" in design
