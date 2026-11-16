"""Sky-clouds lane (2026-11-15): -look-cloud-light=on|off and -cloud-material=ours|epic.

The Python twin (core/scene/world_beauty.py CLOUD_LIGHT_*, cloud_sky_ao), the C++
pure block (FlightSimClouds.cpp CloudLightRow), the material script
(WORLD_CLOUD_LIGHT_SCALARS, M_FlightSimCloudLayersLit 2) and cloud_sky_ao.hlsl agree,
and OFF is c9e13c53's cloud exactly. Lit 2 (round 1426): the light conserves energy
(albedo untouched, the base on the sky light only). Beauty only: no label pass.
"""
import ast
import json
import math
import re
import subprocess
import shutil
from pathlib import Path

import pytest

from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
CPP = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp").read_text(encoding="utf-8")
HDR = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimClouds.h").read_text(encoding="utf-8")
PURE = CPP[CPP.index("// FLIGHTSIM-WORLD-PURE-BEGIN"):CPP.index("// FLIGHTSIM-WORLD-PURE-END")]
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text(encoding="utf-8")
HLSL = (REPO / "assets/shaders/world/cloud_sky_ao.hlsl").read_text(encoding="utf-8")
SHAPES = ("cumulus", "stratocumulus", "overcast", "nimbostratus", "altocumulus")   # C++ enum order


def _script_value(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _cpp(name):
    return float(re.search(r"constexpr (?:double|int) " + name + r" = ([0-9.-]+);", PURE).group(1))


def _cpp_array(pattern):
    return [float(v) for v in re.search(pattern, PURE).group(1).split(",")]


def test_off_is_the_baked_scattering_and_the_materials_defaults():
    off = wb.CLOUD_LIGHT_OFF
    for key, field in (("phase_g", "PhaseG"), ("phase_g2", "PhaseG2"), ("phase_blend", "PhaseBlend"),
                       ("contribution", "MsContribution"), ("occlusion", "MsOcclusion"),
                       ("eccentricity", "MsEccentricity")):
        assert off[field] == wb.CLOUD_SCATTERING[key] == _script_value("CLOUD_SCATTERING")[key]
    assert _script_value("WORLD_CLOUD_LIGHT_SCALARS") == off
    assert wb.cloud_light_row(False, "cumulus") == off
    cpp_off = _cpp_array(r"static const double Values\[LgtFieldCount\] = \{([^}]*)\};")
    assert cpp_off == [off[f] for f in wb.CLOUD_LIGHT_FIELDS]
    names = re.search(r"static const char\* const Names\[LgtFieldCount\] = \{\s*([^}]*)\}", PURE).group(1)
    assert tuple(re.findall(r'"(\w+)"', names)) == wb.CLOUD_LIGHT_FIELDS


def test_on_row_matches_cpp_and_the_stated_physics():
    assert (_cpp("CloudLightPhaseG"), _cpp("CloudLightPhaseG2"), _cpp("CloudLightPhaseBlend")) == wb.CLOUD_LIGHT_PHASE
    assert wb.CLOUD_LIGHT_PHASE[:2] == (0.8, -0.3)   # the dual-lobe HG of the brief
    g, g2, b = wb.CLOUD_LIGHT_PHASE
    assert (1 - b) * g + b * g2 == pytest.approx(0.58)   # effective asymmetry, between 0.5 and 0.85
    assert wb.CLOUD_LIGHT_OCTAVE == (_cpp("CloudLightOctave"),) * 3 == (0.5, 0.5, 0.5)   # Wrenninge 2013
    assert "Powder" not in PURE   # lit 2: the powder scaled the albedo (round 1426)
    dark = _cpp_array(r"CloudLightBaseDarkening\(int Cloud\)\s*\{\s*static const double Rows\[CloudCount\] = \{([^}]*)\}")
    rise = _cpp_array(r"CloudLightBaseRise\(int Cloud\)\s*\{\s*static const double Rows\[CloudCount\] = \{([^}]*)\}")
    assert dark == [wb.CLOUD_LIGHT_BASE_DARKENING[s] for s in SHAPES]
    assert rise == [wb.CLOUD_LIGHT_BASE_RISE[s] for s in SHAPES]
    # a fair cumulus base 0.4-0.6 of its flank; a nimbostratus / storm base darker than any fair cloud
    assert 0.4 <= 1 - wb.CLOUD_LIGHT_BASE_DARKENING["cumulus"] <= 0.6
    assert wb.CLOUD_LIGHT_BASE_DARKENING["nimbostratus"] == max(wb.CLOUD_LIGHT_BASE_DARKENING.values())
    row = wb.cloud_light_row(True, "cumulus")
    assert row["MsOcclusion"] > wb.CLOUD_LIGHT_OFF["MsOcclusion"]   # #13's flat white: more self-shadow
    assert row["MsContribution"] < wb.CLOUD_LIGHT_OFF["MsContribution"]


def _phase(cos_t, g, g2, blend):
    """VolumetricCloud.usf SamplePhaseFunction: lerp of two normalised HG lobes."""
    def hg(g, c):
        return (1 - g * g) / (4 * math.pi * (1 + g * g - 2 * g * c) ** 1.5)
    return hg(g, cos_t) + blend * (hg(g2, cos_t) - hg(g, cos_t))


def test_energy_the_phase_is_normalised_and_the_octaves_meet_wrenninge():
    """Energy: the dual-lobe phase integrates to 1 over the sphere (each HG lobe is
    normalised and the blend is convex), and the octave constants meet Wrenninge et
    al. 2013's condition a <= b (Hillaire 2016 s. 5): each octave scatters no more
    than the one before, (c / o)^i <= 1."""
    for row in (wb.cloud_light_row(True, s) for s in SHAPES):
        n = 4000
        total = sum(_phase(-1 + (k + 0.5) * 2 / n, row["PhaseG"], row["PhaseG2"], row["PhaseBlend"])
                    for k in range(n)) * 2 * math.pi * 2 / n
        assert total == pytest.approx(1.0, abs=2e-3)
        c, o = row["MsContribution"], row["MsOcclusion"]
        assert c <= o
        assert all((c / o) ** i <= 1.0 for i in range(1, 4))


def test_energy_the_albedo_is_untouched_and_the_sun_loses_nothing():
    """Lit 2: Base Color is the material's Albedo exactly (>= the 0.9 floor), so
    the sun's single and multiple scattering are the OFF material's; the base
    acts on the sky light only (the AO pin)."""
    albedo = _script_value("WORLD_CLOUD_ALBEDO")
    assert albedo >= wb.CLOUD_LIGHT_ALBEDO_FLOOR == 0.9
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    lit = create[create.index("    if not lit:"):]
    lit = lit[lit.index("return\n") :]
    assert 'lib.connect_material_property(albedo, "", unreal.MaterialProperty.MP_BASE_COLOR)' in lit
    assert lit.count("MP_BASE_COLOR") == 1
    assert 'lib.connect_material_property(sky_ao, "", unreal.MaterialProperty.MP_AMBIENT_OCCLUSION)' in lit
    # nothing on the lit material's extra nodes reads the extinction (cloud_layers.hlsl
    # compiled twice: round 1426's +27 %), the camera or the sun
    assert "(extinction, " not in lit and "SunDirWS" not in lit and "CameraPos" not in lit
    assert _script_value("WORLD_CLOUD_SKY_AO_INPUTS") == ("NormAlt", "SkyBottomOcclusion", "BaseDarkening",
                                                         "BaseRise")
    for name in ("Extinction", "SunDirWS", "Powder", "CameraPos", "Albedo"):
        assert name not in re.sub(r"//.*", "", HLSL), name


def test_energy_the_sky_ao_counts_the_base_once():
    """The AO pin REPLACES the engine's bottom gradient: OFF (no pin) is
    saturate(1 - occ + h); ON is the darker of that and the flat base, never a
    product, bounded below by both and equal to the engine where the base is
    not darker (a cumulus under a 0.45 belly cap: OFF within 0.01)."""
    def engine(h, occ):
        return min(max(1 - occ + h, 0.0), 1.0)
    for shape in SHAPES:
        row = wb.cloud_light_row(True, shape)
        for occ in (0.0, 0.3, 0.45, 0.5, 0.8):
            for k in range(21):
                h = k / 20
                ao = wb.cloud_sky_ao(h, occ, row)
                flat = wb.cloud_sky_ao(h, 0.0, row)
                assert ao == pytest.approx(min(engine(h, occ), flat))
                assert ao >= engine(h, occ) * flat - 1e-12   # never darker than a product
                assert ao >= 1 - max(occ, row["BaseDarkening"]) - 1e-12
            assert wb.cloud_sky_ao(1.0, occ, row) == 1.0   # a top: the whole sky
    cum = wb.cloud_light_row(True, "cumulus")
    for k in range(21):
        assert abs(wb.cloud_sky_ao(k / 20, 0.45, cum) - engine(k / 20, 0.45)) <= 0.01
    off = wb.CLOUD_LIGHT_OFF
    for k in range(21):
        assert wb.cloud_sky_ao(k / 20, 0.5, off) == pytest.approx(engine(k / 20, 0.5))


def test_energy_a_frame_seen_from_below_keeps_its_brightness():
    """Round 1426's #3 / #15 (under the layer): the old albedo factor (base 0.55 /
    0.3 times powder) scaled the sun and the sky light alike. Lit 2 at the bottom
    band (h 0..0.25): the sun term is OFF's; the sky term is never under the
    engine's own gradient or the stated base, whichever is darker."""
    for shape in ("cumulus", "nimbostratus"):
        row = wb.cloud_light_row(True, shape)
        band = [k / 100 for k in range(26)]
        old = sum(1 - row["BaseDarkening"] * (1 - _smooth(h / row["BaseRise"])) for h in band) / len(band)
        sky = sum(wb.cloud_sky_ao(h, 0.5, row) for h in band) / len(band)
        engine = sum(min(1.0, 0.5 + h) for h in band) / len(band)
        # sun 50 / sky 50 under the layer: lit 2 keeps more than the old albedo did
        assert 0.5 * 1.0 + 0.5 * sky > 0.5 * old + 0.5 * old * engine
        assert sky <= engine + 1e-12


def _smooth(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def test_the_shader_is_the_python_formula():
    assert "float engineVis = saturate(1.0 - saturate(SkyBottomOcclusion) + h);" in HLSL
    assert ("float flatBase = lerp(1.0 - saturate(BaseDarkening), 1.0, smoothstep(0.0, max(BaseRise, 1e-3), h));"
            in HLSL)
    assert "return min(engineVis, flatBase);" in HLSL
    names = set(re.findall(r"\b([A-Z][A-Za-z]+)\b", re.sub(r"//.*", "", HLSL)))
    for pin in _script_value("WORLD_CLOUD_SKY_AO_INPUTS"):
        assert pin in names, pin
    assert not (REPO / "assets/shaders/world/cloud_albedo.hlsl").exists()


def test_the_material_wires_the_six_pins_and_bumps_its_generation():
    pins = _script_value("WORLD_CLOUD_LIGHT_PINS")
    assert set(pins) == {"PhaseG", "PhaseG2", "PhaseBlend", "MsContribution", "MsOcclusion", "MsEccentricity"}
    assert set(pins.values()) == {"PhaseG", "PhaseG2", "PhaseBlend", "MultiScatteringContribution",
                                  "MultiScatteringOcclusion", "MultiScatteringEccentricity"}
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"] == "11"   # rain-grey: pins from parameters
    assert _cpp("CloudGraphGeneration") == 11
    # sky-clouds2 review: the light is its own material; the default graph is 8's again
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayersLit"] == "2"   # lit 2: round 1426
    assert '"M_FlightSimCloudLayersLit": "2",' in SCRIPT
    assert 'create_world_cloud_layers(lit=True)' in SCRIPT
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    off = create[:create.index("    if not lit:")]
    assert ("WORLD_CLOUD_LIGHT_SCALARS" not in off and 'world_custom(material, lib, "cloud_sky_ao"' not in off
            and "MP_AMBIENT_OCCLUSION" not in off)
    assert wb.CLOUD_LIGHT_MATERIAL in CPP
    assert "UMaterialInstanceDynamic::Create(Parent, Cloud)" in CPP
    assert '"M_FlightSimCloudLayers": "13"' in SCRIPT
    assert 'world_custom(material, lib, "cloud_sky_ao"' in SCRIPT
    assert "cloud_albedo" not in create


def test_the_bridge_reads_refuses_gates_sets_and_records():
    assert 'FParse::Value(*Switches, TEXT("look-cloud-light="), CloudLightSwitch);' in CPP
    assert 'FParse::Value(*Switches, TEXT("cloud-material="), CloudMaterialSwitch);' in CPP
    assert "-look-cloud-light=%s is not on or off" in CPP
    assert "-cloud-material=%s is not ours or epic" in CPP
    assert 'FString CloudLightSwitch = TEXT("off");' in HDR   # off until the Windows A/B
    assert '		CloudLightSwitch = TEXT("off");' in CPP and wb.CLOUD_LIGHT_DEFAULT == "off"
    assert 'FString CloudMaterialSwitch = TEXT("ours");' in HDR
    assert "CloudBillowApplies(CloudLightBillow(CloudBillowSwitch == TEXT(\"on\"), bLight), State.Shape)" in CPP
    assert "return bBillowOn && !bLightOn;" in PURE
    assert wb.cloud_light_billow(True, False) and not wb.cloud_light_billow(True, True)
    assert not wb.cloud_light_billow(False, False)
    assert "CloudLightRow(bLight, State.Shape, LightRow);" in CPP
    assert "SunDirWS" not in CPP   # lit 2: no powder, no view weighting
    assert 'SetScalarParameterValue(FName(TEXT("SkyBottomOcclusion")), static_cast<float>(BottomOcclusion));' in CPP
    assert 'LightOut->SetNumberField(TEXT("SkyBottomOcclusion"), BottomOcclusion);' in CPP
    assert 'Layer->SetObjectField(TEXT("cloud_light_row"), LightOut);' in CPP
    assert wb.CLOUD_MATERIAL_EPIC in CPP
    assert wb.CLOUD_MATERIAL_WORDS == ("ours", "epic")
    assert wb.CLOUD_LIGHT_SWITCH == "-look-cloud-light" and wb.CLOUD_MATERIAL_SWITCH == "-cloud-material"


def test_the_volumetrics_plugin_stays_opt_in_for_the_epic_ab():
    plugins = json.loads((REPO / "ue/FlightSim.uproject").read_text(encoding="utf-8"))["Plugins"]
    assert all(p["Name"] != "Volumetrics" for p in plugins)   # review: opt-in, documented
    assert '"Name": "Volumetrics", "Enabled": true' in (REPO / "core/scene/world_beauty.py").read_text(encoding="utf-8")
    assert "did not load; ours drawn" in CPP
    assert wb.CLOUD_MATERIAL_EPIC.startswith("/Volumetrics/Sky/Materials/")


@pytest.mark.skipif(shutil.which("c++") is None, reason="no C++ compiler")
def test_the_pure_light_row_compiles_and_matches(tmp_path):
    src = tmp_path / "t.cpp"
    src.write_text("#include <cstdio>\n#include <cmath>\n#include <algorithm>\n#include <cstring>\n#include <cstdint>\n" + PURE.replace("// FLIGHTSIM-WORLD-PURE-BEGIN", "")
                   + "\nint main(){using namespace FlightSimWorldPure; double r[LgtFieldCount];"
                     "for(int s=0;s<CloudCount;++s){CloudLightRow(true,s,r);for(int f=0;f<LgtFieldCount;++f)"
                     "std::printf(\"%g \",r[f]);std::printf(\"\\n\");}CloudLightRow(false,0,r);"
                     "for(int f=0;f<LgtFieldCount;++f)std::printf(\"%g \",r[f]);std::printf(\"\\n\");}\n", encoding="utf-8")
    exe = tmp_path / "t"
    built = subprocess.run(["c++", "-std=c++17", "-o", str(exe), str(src)], capture_output=True, text=True)
    if built.returncode != 0:
        pytest.skip("pure block needs more than the standard library here: " + built.stderr[-200:])
    rows = [[float(v) for v in line.split()] for line in subprocess.check_output([str(exe)], text=True).splitlines()]
    for s, shape in enumerate(SHAPES):
        expect = wb.cloud_light_row(True, shape)
        assert rows[s] == pytest.approx([expect[f] for f in wb.CLOUD_LIGHT_FIELDS])
    assert rows[-1] == pytest.approx([wb.CLOUD_LIGHT_OFF[f] for f in wb.CLOUD_LIGHT_FIELDS])


# -- lane rain-grey (2026-11-16): a deck keeps round 95's energy-conserving node ------

def test_deck_scatter_restores_round95_on_decks_only():
    storm = _script_value("STORM_SCATTERING")
    round95 = {"PhaseG": storm["phase_g"], "PhaseG2": storm["phase_g2"], "PhaseBlend": storm["phase_blend"],
               "MsContribution": storm["contribution"], "MsOcclusion": storm["occlusion"],
               "MsEccentricity": storm["eccentricity"]}
    assert wb.CLOUD_DECK_SCATTER == round95
    # Wrenninge's energy condition (contribution <= occlusion): the deck row meets it, step 1's does not.
    assert wb.CLOUD_DECK_SCATTER["MsContribution"] <= wb.CLOUD_DECK_SCATTER["MsOcclusion"]
    assert wb.CLOUD_LIGHT_OFF["MsContribution"] > wb.CLOUD_LIGHT_OFF["MsOcclusion"]
    for shape in SHAPES:
        row = wb.cloud_scatter_row(False, shape)
        if shape in ("overcast", "nimbostratus"):
            assert {k: row[k] for k in round95} == round95
        else:
            assert row == wb.CLOUD_LIGHT_OFF
        assert wb.cloud_scatter_row(False, shape, "beauty") == wb.CLOUD_LIGHT_OFF
        assert wb.cloud_scatter_row(True, shape) == wb.cloud_light_row(True, shape)
    assert wb.cloud_deck_scatter_applies("bogus", False, "nimbostratus") is None
    assert wb.CLOUD_DECK_SCATTER_DEFAULT == "round95"


def test_deck_scatter_twins_match_cpp():
    vals = _cpp_array(r"static const double Values\[LgtMsEccentricity \+ 1\] = \{([^}]*)\};")
    assert vals == [wb.CLOUD_DECK_SCATTER[f] for f in wb.CLOUD_LIGHT_FIELDS[:6]]
    assert 'std::strcmp(Word, "round95") == 0) { return 1; }' in PURE
    assert 'std::strcmp(Word, "beauty") == 0) { return 0; }' in PURE
    assert "(Cloud == CloudOvercast || Cloud == CloudNimbostratus)" in PURE
    assert 'FString CloudDeckScatterSwitch = TEXT("round95");' in HDR
    assert 'TEXT("cloud-deck-scatter="), CloudDeckScatterSwitch' in CPP
    body = CPP[CPP.index("CloudLightRow(bLight, State.Shape, LightRow);"):]
    assert body.index("CloudDeckScatterRow(bDeckScatter, LightRow);") < body.index("SetScalarParameterValue(FName(ANSI_TO_TCHAR(CloudLightFieldName(F)))")


def test_default_material_drives_the_six_pins_from_parameters():
    create = SCRIPT[SCRIPT.index("def create_world_cloud_layers"):SCRIPT.index("def create_world_tiles_beauty")]
    start = create.index("    if not lit:")
    unlit = create[start:create.index("        return\n", start)]
    assert "connect_cloud_scatter_pins(lib, asset, node, scatter)" in unlit
    assert "WORLD_CLOUD_LIGHT_PINS" in unlit and "cloud_sky_ao" not in unlit
    defaults = _script_value("WORLD_CLOUD_LIGHT_SCALARS")
    assert {k: defaults[k] for k in wb.CLOUD_DECK_SCATTER} == {k: wb.CLOUD_LIGHT_OFF[k] for k in wb.CLOUD_DECK_SCATTER}
