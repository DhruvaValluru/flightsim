"""Round 147 (r146 #13, the 747 at 10 km over the ocean at noon): the far cumulus deck
drew as flat white cut-outs on a uniform navy sea. Seen from 10 km almost every cloud in
frame is past the constrained hand-over (24 km), i.e. the 2D distant sheet, whose
screen-derivative normal is flat at that range, so -look-cloud-light (the volumetric
material) could not change it. What must hold without an engine:

* the sheet's tops relief and sea shadow live in one branch (fromAbove, past the
  hand-over); with TopRelief and SeaShadow 0 (the material's defaults) the round-146
  output is untouched; the HLSL constants are the Python twin's;
* the bridge sets the four new scalars under -look-sheet-tops (on by default), the sea
  shadow only over the ocean, and records them;
* the C++ laws (SheetTopRelief, SheetSeaShadowFor, SheetMidZKm, HighApLutDepthKm) are
  the Python ones, compiled and compared;
* the aerial-perspective LUT is raised only for a camera above 5 km, never below the row;
* the ocean's HorizonLift defaults to 1 (generation 6 exactly) and the sea cap gets
  SEA_HORIZON_LIFT under -look-sea-horizon (on by default).
"""

import ast
import math
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
TILES_CPP = (SOURCE / "Private" / "FlightSimGoogleTiles.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "world"
DISTANT = (SHADERS / "distant_clouds.hlsl").read_text(encoding="utf-8")
OCEAN_EMISSIVE = (SHADERS / "ocean_emissive.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end)]


def _script_value(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


# -- the sheet's shader -------------------------------------------------------------------

def test_the_tops_constants_are_the_python_twins():
    for name, value in (("TOPS_STEP_SHARE", wb.SHEET_TOPS_STEP_SHARE),
                        ("TOPS_SHADOW_SHARE", wb.SHEET_TOPS_SHADOW_SHARE),
                        ("TOPS_SHADOW_DEPTH", wb.SHEET_TOPS_SHADOW_DEPTH),
                        ("TOPS_AO_FLOOR", wb.SHEET_TOPS_AO_FLOOR),
                        ("TOPS_EDGE_SOFTEN", wb.SHEET_TOPS_EDGE_SOFTEN)):
        assert f"const float {name} = {value};" in DISTANT, name


def test_the_round_146_output_is_untouched_with_the_new_scalars_at_zero():
    base, tops = DISTANT.split("// Round 147: the tops seen from above")
    # the round-146 result is computed in full before the branch
    assert "float a = opacity * fadeIn * rim * saturate(SheetFade);" in base
    # the branch is entered only from above, where the sheet draws, with a scalar above 0
    assert "[branch] if (fromAbove && sheetWeight > 0.0 && (TopRelief > 0.0 || SeaShadow > 0.0))" in tops
    assert "[branch] if (relief > 0.0)" in tops and "[branch] if (SeaShadow > 0.0 && V.z > 0.02" in tops
    assert tops.rstrip().endswith("return float4(L, a);")
    # the shadow is a black layer under the cloud (unlit translucent "over")
    assert "float total = a + shadowA * (1.0 - a);" in tops and "L * (a / total)" in tops
    # the material's defaults are round 146's
    scalars = _script_value("WORLD_DISTANT_SCALARS")
    assert scalars["TopRelief"] == 0.0 and scalars["SeaShadow"] == 0.0
    assert set(("TopRelief", "SeaShadow", "GroundZKm", "MidZKm")) <= set(scalars)
    assert _script_value("WORLD_GENERATIONS")["M_FlightSimDistantClouds"] == "6"
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimDistantClouds"] == "6"


def test_the_sea_shadow_follows_the_view_ray_down_and_the_sun_ray_up():
    assert "float2 groundKm = kmxy - V.xy / V.z * dropKm;" in DISTANT
    assert "float2 casterKm = groundKm + SunDir.xy / SunDir.z * max(MidZKm - GroundZKm, 0.0);" in DISTANT


# -- the bridge -----------------------------------------------------------------------------

def test_the_bridge_sets_the_tops_under_the_switch_and_the_shadow_over_the_ocean_only():
    apply = _block(CLOUDS_CPP, "void FFlightSimWorldBeauty::ApplyDistantClouds(",
                   "void FFlightSimWorldBeauty::ApplyHighAltitudeAerialPerspective(")
    for name in ("TopRelief", "SeaShadow", "GroundZKm", "MidZKm"):
        assert f'Material->SetScalarParameterValue(TEXT("{name}")' in apply, name
    assert 'SheetSeaShadowFor(bSheetTops, Surface == TEXT("ocean"))' in apply
    assert 'Out->SetObjectField(TEXT("tops"), Tops);' in apply
    assert 'FString SheetTopsSwitch = TEXT("on");' in CLOUDS_H and 'FString HighApSwitch = TEXT("on");' in CLOUDS_H
    assert 'FParse::Value(*Switches, TEXT("look-sheet-tops="), SheetTopsSwitch);' in CLOUDS_CPP
    assert 'FParse::Value(*Switches, TEXT("look-high-ap="), HighApSwitch);' in CLOUDS_CPP
    # after the sheet, once
    assert CLOUDS_CPP.count("ApplyHighAltitudeAerialPerspective(Aircraft);") == 1
    assert CLOUDS_CPP.index("ApplyDistantClouds(World, Scene, Weather, DistantMode, Seed);") < \
        CLOUDS_CPP.index("ApplyHighAltitudeAerialPerspective(Aircraft);")


def test_the_python_rows():
    on = wb.sheet_tops_row("on", "ocean", 1500.0, 2700.0)
    assert on == {"TopRelief": 1.0, "SeaShadow": wb.SHEET_SEA_SHADOW, "GroundZKm": 0.0, "MidZKm": 2.1}
    assert wb.sheet_tops_row("on", "grass", 1500.0, 2700.0)["SeaShadow"] == 0.0
    assert wb.sheet_tops_row("off", "ocean", 1500.0, 2700.0)["TopRelief"] == 0.0
    assert wb.sheet_tops_row("off", "ocean", 1500.0, 2700.0)["SeaShadow"] == 0.0
    assert wb.sea_horizon_lift("on") == wb.SEA_HORIZON_LIFT and wb.sea_horizon_lift("off") == 1.0
    assert wb.high_ap_lut_depth_km("on", 10000.0, 96.0) == pytest.approx(math.sqrt(2 * 6371.0 * 10.0))
    assert wb.high_ap_lut_depth_km("on", 3000.0, 96.0) == 96.0          # low cameras keep the row
    assert wb.high_ap_lut_depth_km("off", 10000.0, 96.0) == 96.0
    assert wb.high_ap_lut_depth_km("on", 20000.0, 96.0) == wb.HIGH_AP_MAX_KM
    assert wb.high_ap_lut_depth_km("on", 5500.0, 400.0) == 400.0        # never below the row


@NEEDS_CXX
def test_the_cpp_laws_are_the_python_ones(tmp_path):
    block = _block(CLOUDS_CPP, "// FLIGHTSIM-WORLD-PURE-BEGIN", "// FLIGHTSIM-WORLD-PURE-END")
    cases = [(on, alt, row) for on in (0, 1) for alt in (0.0, 4999.0, 5001.0, 10000.0, 30000.0)
             for row in (96.0, 160.0, 500.0)]
    main = ["using namespace FlightSimWorldPure;", "int main() {",
            "printf(\"tops %.17g %.17g %.17g %.17g %.17g\\n\", SheetTopRelief(true), SheetTopRelief(false),"
            " SheetSeaShadowFor(true, true), SheetSeaShadowFor(true, false), SheetSeaShadowFor(false, true));",
            "printf(\"mid %.17g\\n\", SheetMidZKm(1500.0, 2700.0));",
            "printf(\"apc %.17g %.17g\\n\", HighApMinAltitudeM, HighApMaxKm);"]
    for on, alt, row in cases:
        main.append(f"printf(\"ap %.17g\\n\", HighApLutDepthKm({'true' if on else 'false'}, {alt!r}, {row!r}));")
    main.append("return 0; }")
    source = tmp_path / "r147.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-o", str(tmp_path / "r147"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "r147")], check=True, capture_output=True, text=True).stdout.splitlines()
    tops = [float(v) for v in lines[0].split()[1:]]
    assert tops == [wb.SHEET_TOPS_RELIEF, 0.0, wb.SHEET_SEA_SHADOW, 0.0, 0.0]
    row = wb.sheet_tops_row("on", "ocean", 1500.0, 2700.0)
    assert float(lines[1].split()[1]) == row["MidZKm"]
    assert [float(v) for v in lines[2].split()[1:]] == [wb.HIGH_AP_MIN_ALTITUDE_M, wb.HIGH_AP_MAX_KM]
    got = [float(l.split()[1]) for l in lines if l.startswith("ap ")]
    want = [wb.high_ap_lut_depth_km("on" if on else "off", alt, row) for on, alt, row in cases]
    assert got == pytest.approx(want, rel=0, abs=1e-12)


# -- the sea ----------------------------------------------------------------------------------

def test_the_sea_horizon_lift_defaults_to_generation_6_and_the_cap_gets_the_lift():
    assert _script_value("WORLD_OCEAN_SCALARS")["HorizonLift"] == 1.0
    assert _script_value("WORLD_GENERATIONS")["M_FlightSimOceanBeauty"] == "7"
    assert "float3 sky = lerp(pale * HORIZON_GAIN * max(HorizonLift, 0.0), SkyLum * ZENITH_TINT, sqrt(elevation));" \
        in OCEAN_EMISSIVE
    assert re.search(r"//\s+HorizonLift\s", OCEAN_EMISSIVE)
    # only the emissive node takes the pin (the normal and colour bodies never read it)
    assert '+ ("HorizonLift",)' in SCRIPT and 'WORLD_OCEAN_INPUTS["ocean_emissive"]' in SCRIPT
    assert f"constexpr double SeaHorizonLift = {wb.SEA_HORIZON_LIFT};" in TILES_CPP
    assert 'FParse::Value(*TilesSwitches(), TEXT("look-sea-horizon="), SeaHorizonWord);' in TILES_CPP
    assert 'SeaMaterial->SetScalarParameterValue(FName(TEXT("HorizonLift")), static_cast<float>(SeaHorizonLift));' \
        in TILES_CPP
