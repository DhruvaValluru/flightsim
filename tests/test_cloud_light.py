"""Sky-clouds lane (2026-11-15): -look-cloud-light=on|off and -cloud-material=ours|epic.

The Python twin (core/scene/world_beauty.py CLOUD_LIGHT_*, cloud_albedo), the C++
pure block (FlightSimClouds.cpp CloudLightRow), the material script
(WORLD_CLOUD_LIGHT_SCALARS, graph generation 9) and cloud_albedo.hlsl agree, and OFF
is c9e13c53's cloud exactly. Beauty only: nothing here touches a label pass.
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
CPP = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp").read_text()
HDR = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Public/FlightSimClouds.h").read_text()
PURE = CPP[CPP.index("// FLIGHTSIM-WORLD-PURE-BEGIN"):CPP.index("// FLIGHTSIM-WORLD-PURE-END")]
SCRIPT = (REPO / "scripts/ue_create_materials.py").read_text()
HLSL = (REPO / "assets/shaders/world/cloud_albedo.hlsl").read_text()
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
    assert _cpp("CloudLightPowder") == wb.CLOUD_LIGHT_POWDER
    assert _cpp("CloudLightPowderDepthM") == wb.CLOUD_LIGHT_POWDER_DEPTH_M
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


def test_cloud_albedo_off_is_exact_and_on_is_bounded():
    off = wb.CLOUD_LIGHT_OFF
    for sigma, h, c in ((0.0, 0.0, -1.0), (0.05, 0.1, 0.3), (0.002, 0.9, 1.0)):
        assert wb.cloud_albedo(0.98, sigma, h, c, off) == 0.98
    on = wb.cloud_light_row(True, "cumulus")
    # facing the sun (silver lining): no powder; the top of the layer: no base darkening
    assert wb.cloud_albedo(0.98, 0.001, 1.0, 1.0, on) == pytest.approx(0.98)
    # away from the sun, a thin edge darkens by the powder, a dense core barely
    edge = wb.cloud_albedo(0.98, 0.002, 1.0, -1.0, on)
    core = wb.cloud_albedo(0.98, 0.05, 1.0, -1.0, on)
    p_edge = 1 - math.exp(-2 * 0.002 * 40.0)
    assert edge == pytest.approx(0.98 * (0.4 + 0.6 * p_edge))
    assert edge < core < 0.98 and core > 0.96
    # the base: (1 - 0.45) at the bottom, 1 from a quarter of the layer up, monotone between
    assert wb.cloud_albedo(1.0, 1.0, 0.0, 1.0, on) == pytest.approx(0.55)
    assert wb.cloud_albedo(1.0, 1.0, 0.25, 1.0, on) == pytest.approx(1.0)
    seq = [wb.cloud_albedo(1.0, 1.0, h / 20, 1.0, on) for h in range(21)]
    assert all(b >= a for a, b in zip(seq, seq[1:]))
    for shape in SHAPES:
        row = wb.cloud_light_row(True, shape)
        for h in (0.0, 0.5, 1.0):
            for c in (-1.0, 0.0, 1.0):
                assert 0.0 < wb.cloud_albedo(0.98, 0.03, h, c, row) <= 0.98


def test_the_shader_is_the_python_formula():
    assert "1.0 - exp(-2.0 * sigma * max(PowderDepthM, 0.0))" in HLSL
    assert "saturate(PowderAmount) * saturate(0.5 - 0.5 * cosSun)" in HLSL
    assert "lerp(1.0 - saturate(BaseDarkening), 1.0, smoothstep(0.0, max(BaseRise, 1e-3), saturate(NormAlt)))" in HLSL
    assert "return Albedo * lerp(1.0, powder, w) * base;" in HLSL
    names = set(re.findall(r"\b([A-Z][A-Za-z]+)\b", HLSL))
    for pin in _script_value("WORLD_CLOUD_ALBEDO_INPUTS"):
        assert pin in names, pin


def test_the_material_wires_the_six_pins_and_bumps_its_generation():
    pins = _script_value("WORLD_CLOUD_LIGHT_PINS")
    assert set(pins) == {"PhaseG", "PhaseG2", "PhaseBlend", "MsContribution", "MsOcclusion", "MsEccentricity"}
    assert set(pins.values()) == {"PhaseG", "PhaseG2", "PhaseBlend", "MultiScatteringContribution",
                                  "MultiScatteringOcclusion", "MultiScatteringEccentricity"}
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimCloudLayers"] == "9"
    assert _cpp("CloudGraphGeneration") == 9
    assert '"M_FlightSimCloudLayers": "11"' in SCRIPT
    assert 'world_custom(material, lib, "cloud_albedo"' in SCRIPT
    assert "lib.connect_material_property(lit_albedo, \"\", unreal.MaterialProperty.MP_BASE_COLOR)" in SCRIPT


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
    assert 'SetVectorParameterValue(TEXT("SunDirWS")' in CPP
    assert 'Layer->SetObjectField(TEXT("cloud_light_row"), LightOut);' in CPP
    assert wb.CLOUD_MATERIAL_EPIC in CPP
    assert wb.CLOUD_MATERIAL_WORDS == ("ours", "epic")
    assert wb.CLOUD_LIGHT_SWITCH == "-look-cloud-light" and wb.CLOUD_MATERIAL_SWITCH == "-cloud-material"


def test_the_volumetrics_plugin_is_enabled_for_the_epic_ab():
    plugins = json.loads((REPO / "ue/FlightSim.uproject").read_text())["Plugins"]
    assert {"Name": "Volumetrics", "Enabled": True} in plugins
    assert wb.CLOUD_MATERIAL_EPIC.startswith("/Volumetrics/Sky/Materials/")


@pytest.mark.skipif(shutil.which("c++") is None, reason="no C++ compiler")
def test_the_pure_light_row_compiles_and_matches(tmp_path):
    src = tmp_path / "t.cpp"
    src.write_text("#include <cstdio>\n#include <cmath>\n#include <algorithm>\n#include <cstring>\n#include <cstdint>\n" + PURE.replace("// FLIGHTSIM-WORLD-PURE-BEGIN", "")
                   + "\nint main(){using namespace FlightSimWorldPure; double r[LgtFieldCount];"
                     "for(int s=0;s<CloudCount;++s){CloudLightRow(true,s,r);for(int f=0;f<LgtFieldCount;++f)"
                     "std::printf(\"%g \",r[f]);std::printf(\"\\n\");}CloudLightRow(false,0,r);"
                     "for(int f=0;f<LgtFieldCount;++f)std::printf(\"%g \",r[f]);std::printf(\"\\n\");}\n")
    exe = tmp_path / "t"
    built = subprocess.run(["c++", "-std=c++17", "-o", str(exe), str(src)], capture_output=True, text=True)
    if built.returncode != 0:
        pytest.skip("pure block needs more than the standard library here: " + built.stderr[-200:])
    rows = [[float(v) for v in line.split()] for line in subprocess.check_output([str(exe)], text=True).splitlines()]
    for s, shape in enumerate(SHAPES):
        expect = wb.cloud_light_row(True, shape)
        assert rows[s] == pytest.approx([expect[f] for f in wb.CLOUD_LIGHT_FIELDS])
    assert rows[-1] == pytest.approx([wb.CLOUD_LIGHT_OFF[f] for f in wb.CLOUD_LIGHT_FIELDS])
