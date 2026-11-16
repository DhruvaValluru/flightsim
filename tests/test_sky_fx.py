"""High-sky effects lane (2026-11-15): the beauty rainbow and in-cloud flash.

* the bows sit where water puts them (primary 40.6-42.4 deg, red outside;
  secondary 50-53 deg, red inside), the band colours sum to white, and
  rainbow.hlsl's tables are core/sky/sky_fx.py's;
* the C++ pure laws (FlightSimSkyFx.h) are the Python ones (g++);
* the material script, the HLSL inputs and the C++ parameter names agree; the
  material is unlit additive with no custom depth or velocity;
* both effects are beauty only (BeautyOnlyActors; armed only on the beauty
  vantage), switches parsed with the old behaviour reachable, catalogued.
"""

import ast
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.sky import sky_fx as fx

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_H = (SOURCE / "Public" / "FlightSimSkyFx.h").read_text(encoding="utf-8")
FX_CPP = (SOURCE / "Private" / "FlightSimSkyFx.cpp").read_text(encoding="utf-8")
WEATHER_CPP = (SOURCE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
LOOK_CPP = (SOURCE / "Private" / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
SCENE_H = (SOURCE / "Public" / "FlightSimVisualScene.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
CATALOG = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
HLSL = (REPO / "assets" / "shaders" / "world" / "rainbow.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _script_value(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _hlsl_table(name):
    body = re.search(rf"{name}\[9\] = \{{(.*?)\}};", HLSL, re.S).group(1)
    return [float(v) for v in re.findall(r"-?\d+\.\d+", body)]


# -- the physics of the bow -------------------------------------------------------

def test_water_index_matches_hale_querry():
    assert fx.water_index(400.0) == pytest.approx(1.339, abs=2e-4)
    assert fx.water_index(700.0) == pytest.approx(1.331, abs=2e-4)
    assert fx.water_index(500.0) == pytest.approx(1.335, abs=1e-3)
    assert fx.water_index(600.0) == pytest.approx(1.332, abs=1e-3)


def test_bows_sit_where_water_puts_them():
    primary, secondary = fx.bow_radii(1), fx.bow_radii(2)
    # Primary 40.6-42.4 deg, red (long wavelength) outside; secondary 50-53 deg, red inside.
    assert all(40.6 <= r <= 42.4 for r in primary)
    assert list(primary) == sorted(primary)
    assert all(50.0 <= r <= 53.0 for r in secondary)
    assert list(secondary) == sorted(secondary, reverse=True)
    # The textbook 42 deg red edge and the ~9 deg Alexander's band between them.
    assert primary[-1] == pytest.approx(42.3, abs=0.15)
    assert 7.5 < secondary[-1] - primary[-1] < 9.5


def test_bow_width_is_sun_disc_plus_airy():
    assert fx.RAINBOW_SIGMA_DEG == pytest.approx(math.hypot(0.533 / 4.0, 0.4), abs=1e-3)


def test_band_colours_sum_to_white_and_run_blue_to_red():
    colours = fx.band_colours()
    for c in range(3):
        assert sum(band[c] for band in colours) == pytest.approx(1.0, abs=1e-4)
    assert all(v >= 0.0 for band in colours for v in band)
    assert colours[0][2] > colours[0][0] and colours[-1][0] > colours[-1][2]


def test_ring_peaks_on_the_bows_and_secondary_is_dimmer():
    lum = lambda t: sum(fx.rainbow_ring(t))
    peak_p = max(lum(40.0 + 0.05 * i) for i in range(60))
    peak_s = max(lum(49.5 + 0.05 * i) for i in range(80))
    band = lum(46.5)
    assert band < 0.05 * peak_p          # Alexander's dark band: nothing added
    assert 0.3 < peak_s / peak_p < 0.6   # the secondary at ~0.43
    assert lum(38.0) > band              # the inner skirt brightens inside the bow


def test_rain_gain_and_gates():
    assert fx.rainbow_strength(True, 0.0, 20.0) == 0.0
    assert fx.rainbow_strength(True, 5.0, 0.0) == 0.0
    assert fx.rainbow_strength(False, 5.0, 20.0) == 0.0
    tau = 0.25 * 5.0 ** 0.63 * 2.0
    assert fx.rainbow_strength(True, 5.0, 20.0) == pytest.approx(1.0 - math.exp(-tau))
    assert fx.rainbow_strength(True, 40.0, 20.0) > fx.rainbow_strength(True, 2.0, 20.0)
    assert fx.rainbow_top_fade(0.0, 1200.0) == 1.0 and fx.rainbow_top_fade(1600.0, 1200.0) == 0.0


def test_modes_refuse_by_name():
    assert fx.rainbow_mode(None) == "on" and fx.rainbow_mode("off") == "off"
    assert fx.cloud_flash_mode(None) == fx.CLOUD_FLASH_SCHEDULE
    with pytest.raises(ValueError, match="-look-rainbow=maybe"):
        fx.rainbow_mode("maybe")
    with pytest.raises(ValueError, match="-look-cloud-flash=always"):
        fx.cloud_flash_mode("always")


def test_flash_intensity_and_schedule():
    # 8.7e5 J at 80 lm/W over 1/60 s: 3.3e8 cd (the weather look's 3e8 cd order).
    assert fx.cloud_flash_cd(1.0 / 60.0) == pytest.approx(3.32e8, rel=0.01)
    assert fx.cloud_flash_cd(1e-6) == fx.cloud_flash_cd(1e-3)
    share = fx.cloud_flash_share(6.0, 3.0)
    assert share == pytest.approx(6.0 / 60.0 * 0.75 * 0.3)
    lit = sum(fx.cloud_flash_lit(fx.CLOUD_FLASH_SCHEDULE, 775307, 0.3 * i + 0.1, 6.0, 3.0) for i in range(20000))
    assert lit / 20000 == pytest.approx(share, abs=0.004)
    assert not any(fx.cloud_flash_lit(fx.CLOUD_FLASH_OFF, 1, t, 60.0, 3.0) for t in range(50))
    assert all(fx.cloud_flash_lit(fx.CLOUD_FLASH_ON, 1, t, 6.0, 3.0) for t in range(50))
    e, n, u = fx.cloud_flash_rel_m(3000.0, 4000.0, 4000.0, 1000.0, 11000.0)
    assert math.hypot(e, n) == pytest.approx(2400.0) and u == pytest.approx(4000.0)
    e, n, _ = fx.cloud_flash_rel_m(300.0, 0.0, 4000.0, 1000.0, 11000.0)
    assert e == pytest.approx(270.0) and n == 0.0


# -- the shader and the material ---------------------------------------------------

def test_hlsl_tables_are_the_python_ones():
    assert _hlsl_table("PRIMARY_DEG") == pytest.approx(list(fx.bow_radii(1)), abs=1e-4)
    assert _hlsl_table("SECONDARY_DEG") == pytest.approx(list(fx.bow_radii(2)), abs=1e-4)
    flat = [v for band in fx.band_colours() for v in band]
    body = re.search(r"BAND_RGB\[9\] = \{(.*?)\};", HLSL, re.S).group(1)
    assert [float(v) for v in re.findall(r"\d+\.\d+", body)] == pytest.approx(flat, abs=1e-5)
    assert f"SIGMA_DEG = {fx.RAINBOW_SIGMA_DEG:.4f}" in HLSL
    assert f"SECONDARY_RATIO = {fx.RAINBOW_SECONDARY_RATIO:.2f}" in HLSL


def test_material_script_inputs_match_the_shader_and_cpp():
    scalars = _script_value("WORLD_RAINBOW_SCALARS")
    for name in ("PrimaryPeak", "InnerGlow", "InnerFoldDeg"):
        assert scalars[name] == fx.RAINBOW_LOOK[name]
    header = [m for m in re.findall(r"^//   (\w+)\s+float", HLSL, re.M)]
    assert tuple(header) == ("WorldPos", "CameraPos", "SunDir", "SunIlluminance") + tuple(scalars)
    for name in scalars:
        assert f'TEXT("{name}")' in FX_CPP
    assert "M_FlightSimRainbow" in _script_value("WORLD_BEAUTY_MATERIALS")
    assert _script_value("WORLD_GRAPH_GENERATIONS")["M_FlightSimRainbow"] == "1"
    assert _script_value("WORLD_GENERATIONS")["M_FlightSimRainbow"] == "1"
    body = SCRIPT[SCRIPT.index("def create_world_rainbow"):SCRIPT.index("def create_sky_hdri")]
    assert "BLEND_ADDITIVE" in body and "MSM_UNLIT" in body
    assert '"allow_translucent_custom_depth_writes", False' in body
    assert '"output_translucent_velocity", False' in body
    assert "\ncreate_world_rainbow()" in SCRIPT


def test_cpp_look_constants_are_the_python_ones():
    def const(name):
        return float(re.search(rf"constexpr double {name} = ([0-9.e+-]+);", FX_H).group(1))
    assert const("RainbowPrimaryPeak") == fx.RAINBOW_LOOK["PrimaryPeak"]
    assert const("RainbowInnerGlow") == fx.RAINBOW_LOOK["InnerGlow"]
    assert const("RainbowInnerFoldDeg") == fx.RAINBOW_LOOK["InnerFoldDeg"]
    assert const("RainbowRadiusKm") == fx.RAINBOW_RADIUS_KM
    assert const("RainbowTopFadeM") == fx.RAINBOW_TOP_FADE_M
    assert const("RainbowDefaultRainTopM") == fx.RAINBOW_DEFAULT_RAIN_TOP_M
    assert const("CloudFlashEnergyJ") == fx.CLOUD_FLASH_ENERGY_J
    assert const("CloudFlashVisibleS") == fx.CLOUD_FLASH_VISIBLE_S
    assert "constexpr double DefaultCloudBaseM = 1200.0;" in LOOK_CPP


@NEEDS_CXX
def test_the_cpp_pure_laws_are_the_python_ones(tmp_path):
    pure = FX_H[FX_H.index("// -- sky fx pure: begin --"):FX_H.index("// -- sky fx pure: end --")]
    cases = [(on, r, e) for on in (0, 1) for r in (0.0, 0.5, 5.0, 40.0) for e in (-3.0, 0.0, 10.0, 55.0)]
    times = [0.1 + 0.37 * i for i in range(400)]
    rels = [(3000.0, 4000.0), (300.0, 0.0), (0.0, 0.0), (-8000.0, 1500.0)]
    main = ["using namespace FlightSimSkyFxPure;", "int main() {"]
    for on, r, e in cases:
        main.append(f'printf("s %.17g\\n", RainbowStrength({"true" if on else "false"}, {r!r}, {e!r}));')
    for sh in (1e-6, 1.0 / 60.0, 0.25):
        main.append(f'printf("cd %.17g\\n", CloudFlashCd({sh!r}));')
    for mode in (0, 1, 2):
        for t in times:
            main.append(f'printf("lit %d\\n", CloudFlashLit({mode}, 775307ull, {t!r}, 6.0, 3.0) ? 1 : 0);')
    for ce, cn in rels:
        main.append(f"{{ double E, N, U; CloudFlashRelM({ce!r}, {cn!r}, 4000.0, 1000.0, 11000.0, E, N, U); "
                    'printf("rel %.17g %.17g %.17g\\n", E, N, U); }')
    main.append("return 0; }")
    source = tmp_path / "fx.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n" + pure + "\n" + "\n".join(main),
                      encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-o", str(tmp_path / "fx"), str(source)], check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "fx")], check=True, capture_output=True, text=True).stdout.splitlines()
    s = [float(l.split()[1]) for l in lines if l.startswith("s ")]
    assert s == pytest.approx([fx.rainbow_strength(bool(on), r, e) for on, r, e in cases], rel=1e-12, abs=1e-15)
    cd = [float(l.split()[1]) for l in lines if l.startswith("cd ")]
    assert cd == pytest.approx([fx.cloud_flash_cd(sh) for sh in (1e-6, 1.0 / 60.0, 0.25)], rel=1e-12)
    lit = [int(l.split()[1]) for l in lines if l.startswith("lit ")]
    assert lit == [int(fx.cloud_flash_lit(m, 775307, t, 6.0, 3.0)) for m in (0, 1, 2) for t in times]
    rel = [tuple(float(v) for v in l.split()[1:]) for l in lines if l.startswith("rel ")]
    for got, (ce, cn) in zip(rel, rels):
        assert got == pytest.approx(fx.cloud_flash_rel_m(ce, cn, 4000.0, 1000.0, 11000.0), abs=1e-9)


# -- beauty only, switches ---------------------------------------------------------

def test_rainbow_is_beauty_only_and_label_safe():
    body = FX_CPP[FX_CPP.index("void FFlightSimVisualScene::ApplyBeautySkyFx"):]
    assert "BeautyOnlyActors.Add(RainbowActor);" in body
    assert "SetCastShadow(false)" in body and "SetRenderCustomDepth(false)" in body
    assert "ECollisionEnabled::NoCollision" in body
    # The only caller is the beauty weather look (itself only FFlightSimWorldBeauty::Build's).
    callers = [p.name for p in (SOURCE / "Private").glob("*.cpp")
               if "ApplyBeautySkyFx(" in p.read_text(encoding="utf-8", errors="ignore")]
    assert sorted(callers) == ["FlightSimSkyFx.cpp", "FlightSimWeatherLook.cpp"]
    look = LOOK_CPP[LOOK_CPP.index("void FFlightSimVisualScene::ApplyBeautyWeatherLook"):]
    assert "ApplyBeautySkyFx(World, Beauty);" in look[:look.index("\n}\n")]
    assert "void ApplyBeautySkyFx(UWorld* World, const TSharedPtr<FJsonObject>& Beauty);" in SCENE_H


def test_cloud_flash_is_armed_only_on_the_beauty_vantage():
    vantage = WEATHER_CPP[WEATHER_CPP.index("void FFlightSimWeather::ApplyBeautyStormVantage"):]
    vantage = vantage[:vantage.index("\n}\n")]
    assert "FlightSimSkyFx::ParseCloudFlash(BeautyCloudFlashMode" in vantage
    assert WEATHER_CPP.count("ParseCloudFlash(") == 1
    assert "int BeautyCloudFlashMode = 0;" in (SOURCE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
    advance = WEATHER_CPP[WEATHER_CPP.index("void FFlightSimWeather::Advance"):]
    assert "const bool bBeautyFlash = Best == nullptr && StormMaterial != nullptr &&" in advance
    assert "if (StormMaterial != nullptr && !bBeautyFlash)" in advance


def test_switch_defaults_keep_old_behaviour_reachable():
    assert 'FString Word = TEXT("on");' in FX_CPP and 'TEXT("look-rainbow=")' in FX_CPP
    assert 'FString Word = TEXT("schedule");' in FX_CPP and 'TEXT("look-cloud-flash=")' in FX_CPP
    assert "FLIGHTSIM_RENDER_SWITCHES" in FX_CPP
    for code in ("sky_fx.rainbow:", "sky_fx.cloud_flash:"):
        assert code in CATALOG
    assert "-look-rainbow=%s is not on or off" in FX_CPP
    assert "-look-cloud-flash=%s is not off, schedule or on" in FX_CPP
