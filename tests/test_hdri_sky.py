"""Round 148: Poly Haven CC0 HDRI skies for the beauty render (-look-hdri=auto|light|off).

What must hold without an engine:

* the switch: auto by default, light, off; another word refuses by name; off builds
  nothing and switches nothing (today's frame exactly);
* the slot (clear noon, golden hour, overcast, rain/storm) per preset and sun, none at
  night; the cubemap yaw puts the photograph's sun at the directional light's azimuth
  (the engine's long-lat import and SourceCubemapAngle conventions, read from the
  5.7 source); the intensity matches the captured sky's upward irradiance and the
  lower hemisphere is divided by the change; the backdrop's camera-height law;
* the C++ laws (FLIGHTSIM-HDRI-PURE) are the Python ones, compiled and compared, and
  the C++ per-photograph table is the committed sidecars';
* the committed files are the pins (sha256), CC0, listed in README/LICENSE;
* beauty only: the switch runs after the sky light capture inside the beauty gate,
  the backdrop is in BeautyOnlyActors, hidden until the switch, unlit translucent with
  no custom depth or velocity; the label captures hide BeautyOnlyActors;
* the editor script imports the cubes and builds the backdrop material with the
  scalars the bridge sets, in the shader's input order.
"""

import ast
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core.scene import hdri_sky as hs
from core.scene import sky_hdri

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
HDRI_CPP = (SOURCE / "Private" / "FlightSimHdriSky.cpp").read_text(encoding="utf-8")
HDRI_H = (SOURCE / "Public" / "FlightSimHdriSky.h").read_text(encoding="utf-8")
CLOUDS_CPP = (SOURCE / "Private" / "FlightSimClouds.cpp").read_text(encoding="utf-8")
CLOUDS_H = (SOURCE / "Public" / "FlightSimClouds.h").read_text(encoding="utf-8")
RENDER_CPP = (SOURCE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
LOOKDEV_CPP = (SOURCE / "Private" / "FlightSimLookDev.cpp").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADER = (REPO / "assets" / "shaders" / "world" / "hdri_backdrop.hlsl").read_text(encoding="utf-8")
NEEDS_CXX = pytest.mark.skipif(shutil.which("g++") is None, reason="no C++ compiler on this machine")


def _block(text, begin, end):
    return text[text.index(begin) + len(begin):text.index(end, text.index(begin))]


def _script_value(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


# -- the switch and the laws --------------------------------------------------------------

def test_the_switch_defaults_to_auto_and_refuses_another_word():
    assert hs.LOOK_HDRI_DEFAULT == "auto"
    assert hs.mode_from(None) == "auto" and hs.mode_from("") == "auto"
    for word in hs.LOOK_HDRI_MODES:
        assert hs.mode_from(word) == word
    with pytest.raises(ValueError, match="hdri_sky.switch"):
        hs.mode_from("on")


def test_the_slot_per_preset_and_sun():
    clear, golden, overcast, storm = (hs.SLOTS.index(s) for s in ("clear", "golden", "overcast", "storm"))
    assert hs.slot_for("clear", 55.0) == clear and hs.slot_for("hazy", 40.0) == clear
    assert hs.slot_for("clear", 8.0) == golden and hs.slot_for("hazy", 14.9) == golden
    assert hs.slot_for("clear", 15.0) == clear
    assert hs.slot_for("overcast", 50.0) == overcast and hs.slot_for("overcast", 5.0) == overcast
    assert hs.slot_for("rain", 50.0) == storm and hs.slot_for("storm", 10.0) == storm
    assert hs.slot_for("clear", -5.0) == hs.SLOT_NONE and hs.slot_for("storm", -10.0) == hs.SLOT_NONE
    assert hs.slot_for("clear", -3.0) == golden   # civil twilight still takes the golden sky
    # every slot has one pin and every pin one slot
    assert sorted(hs.SLOT_HDRI) == sorted(hs.SLOTS) and len(hs.SLOT_HDRI) == len(hs.HDRIS)


def _long_lat_direction(longitude_deg):
    """The cube direction (xy) a long-lat import maps an image longitude to: UE's
    LookupLongLat column is (1 + atan2(D.x, -D.z) / pi) / 2 with D = (V.x, V.z, V.y)
    for the hardware cube vector V, i.e. longitude = atan2(V.x, -V.y)."""
    lon = math.radians(longitude_deg)
    return math.sin(lon), -math.cos(lon)


def test_the_yaw_puts_the_photographs_sun_at_the_lights_azimuth():
    for lon in (36.123, -11.8652, 170.0):
        sx, sy = _long_lat_direction(lon)   # the photograph's sun, in cube space
        for az in (0.0, 30.0, 135.0, -100.0):
            wx, wy = math.cos(math.radians(az)), math.sin(math.radians(az))   # the scene's sun
            yaw = math.radians(hs.cubemap_yaw_deg(lon, wx, wy))
            # the sky light samples the source at R(yaw) x the world direction
            rx, ry = wx * math.cos(yaw) - wy * math.sin(yaw), wx * math.sin(yaw) + wy * math.cos(yaw)
            assert rx == pytest.approx(sx, abs=1e-12) and ry == pytest.approx(sy, abs=1e-12), (lon, az)
    assert 0.0 <= hs.cubemap_yaw_deg(-170.0, 1.0, 0.0) < 360.0
    assert hs.wrap_deg(360.0) == 0.0 and hs.wrap_deg(-10.0) == 350.0


def test_the_intensity_matches_the_captured_irradiance_and_keeps_the_ground_bounce():
    ratio = hs.hdri_ratio(8000.0, 2.0)
    assert ratio == 4000.0
    for slot in range(len(hs.SLOTS)):
        now = 1.6
        new = hs.hdri_intensity(now, ratio, slot)
        assert new == now * ratio * hs.SLOT_FILL_GAIN[slot]
        # the drawn lower hemisphere (intensity x colour) is unchanged
        assert new * hs.lower_hemisphere_scale(now, new) == pytest.approx(now)
    assert hs.hdri_ratio(0.0, 2.0) == 0.0 and hs.hdri_ratio(1.0, 0.0) == 0.0
    assert hs.hdri_ratio(float("nan"), 1.0) == 0.0 and hs.hdri_ratio(1e-9, 1.0) == 0.0
    assert hs.hdri_ratio(1e9, 1.0) == 0.0
    assert hs.lower_hemisphere_scale(1.0, 0.0) == 1.0
    # the fill keeps today's energy unless a slot says otherwise
    assert hs.SLOT_FILL_GAIN == (1.0, 1.0, 1.0, 1.0)


def test_a_uniform_lower_hemisphere_adds_nothing_to_the_upward_sh_irradiance():
    """Why the switch can read the upward irradiance off the SH with the ground bounce
    in it: at order 3 a uniform lower hemisphere projects to 0 at +Z (UE's
    CalcDiffuseTransfer bands pi, 2pi/3)."""
    y00, y10 = 0.282095, 0.488603
    c00 = 2.0 * math.pi * y00            # the projection of 1 over the lower hemisphere
    c10 = -math.pi * y10                 # its cos(theta) moment
    irradiance_up = math.pi * c00 * y00 + (2.0 * math.pi / 3.0) * c10 * y10
    assert irradiance_up == pytest.approx(0.0, abs=1e-5)


def test_the_overcast_ground_returns_at_most_its_albedo_of_the_sky():
    clear, golden, overcast, storm = range(4)
    assert hs.lower_hemisphere_cap(clear, 10.0, 1.0) == 1.0 and hs.lower_hemisphere_cap(golden, 10.0, 1.0) == 1.0
    for slot in (overcast, storm):
        factor = hs.lower_hemisphere_cap(slot, 0.5, 2.0)
        assert 0.5 * factor == pytest.approx(hs.LOWER_CAP_ALBEDO * 2.0 / math.pi)
        assert hs.lower_hemisphere_cap(slot, 0.1, 2.0) == 1.0   # already below the cap
    assert "constexpr double LowerCapAlbedo = 0.25;" in HDRI_CPP and hs.LOWER_CAP_ALBEDO == 0.25


def test_the_backdrop_draws_only_for_a_low_camera_under_auto():
    assert hs.backdrop_weight("auto", 0.0) == hs.BACKDROP_OPACITY
    assert hs.backdrop_weight("auto", hs.BACKDROP_FULL_AGL_M) == hs.BACKDROP_OPACITY
    assert 0.0 < hs.backdrop_weight("auto", 800.0) < hs.BACKDROP_OPACITY
    assert hs.backdrop_weight("auto", hs.BACKDROP_NONE_AGL_M) == 0.0
    # the high scenes (#9, #15 at 2000 m, #13 at 10 km) never draw it
    for agl in (1600.0, 2000.0, 10000.0):
        assert hs.backdrop_weight("auto", agl) == 0.0
    for mode in ("light", "off"):
        assert hs.backdrop_weight(mode, 0.0) == 0.0
    assert hs.backdrop_scale(2.0, 3.0) == 6.0 * hs.BACKDROP_GAIN


def test_the_sun_hole_is_for_the_photographs_with_a_sun():
    clear, golden, overcast, storm = range(4)
    assert hs.sun_hole_deg(clear) == hs.sun_hole_deg(golden) == hs.SUN_HOLE_DEG
    assert hs.sun_hole_deg(overcast) == hs.sun_hole_deg(storm) == 0.0
    assert hs.sun_span_deg(golden, 8.0, 5.8887) == pytest.approx(2.1113)
    assert hs.sun_span_deg(storm, 50.0, 34.7) == 0.0


# -- C++ twin -------------------------------------------------------------------------------

@NEEDS_CXX
def test_the_cpp_laws_are_the_python_ones(tmp_path):
    block = _block(HDRI_CPP, "// FLIGHTSIM-HDRI-PURE-BEGIN", "// FLIGHTSIM-HDRI-PURE-END")
    words = ("", "auto", "light", "off", "on", "AUTO")
    presets = range(5)
    suns = (-10.0, -4.0, -3.9, 0.0, 8.0, 14.999, 15.0, 55.0)
    yaws = [(lon, az) for lon in (36.123, -11.8652, 179.0) for az in (0.0, 47.5, -120.0, 180.0)]
    aglss = (0.0, 599.0, 600.0, 750.0, 999.0, 1000.0, 1600.0, 10000.0)
    main = ["using namespace FlightSimHdriPure;", "int main() {"]
    for w in words:
        main.append(f'printf("mode %d\\n", ModeFrom("{w}"));')
    for p in presets:
        for s in suns:
            main.append(f'printf("slot %d\\n", SlotFor({p}, {s!r}));')
    for lon, az in yaws:
        x, y = math.cos(math.radians(az)), math.sin(math.radians(az))
        main.append(f'printf("yaw %.17g\\n", CubemapYawDeg({lon!r}, {x!r}, {y!r}));')
    for cap, hd in ((8000.0, 2.0), (0.0, 1.0), (1.0, 0.0), (1e-9, 1.0), (1e9, 1.0), (3.5, 7.0)):
        main.append(f'printf("ratio %.17g\\n", Ratio({cap!r}, {hd!r}));')
    for slot in range(4):
        main.append(f'printf("int %.17g %.17g\\n", Intensity(1.6, 4000.0, {slot}), LowerHemisphereScale(1.6, Intensity(1.6, 4000.0, {slot})));')
        main.append(f'printf("hole %.17g %.17g\\n", SunHoleFor({slot}), SunSpanFor({slot}, 8.0));')
        main.append(f'printf("pin %s %.17g %.17g %.17g %.17g\\n", HdriName({slot}), HdriSunLongitudeDeg({slot}), '
                    f'HdriSunElevationDeg({slot}), HdriClampLuminance({slot}), HdriNormalise({slot}));')
    for mode in range(3):
        for agl in aglss:
            main.append(f'printf("bw %.17g\\n", BackdropWeight({mode}, {agl!r}));')
    main.append('printf("bs %.17g\\n", BackdropScale(2.5, 0.83));')
    caps = [(slot, low, up) for slot in range(4) for low, up in ((0.5, 2.0), (0.1, 2.0), (0.0, 1.0), (3.0, 0.0))]
    for slot, low, up in caps:
        main.append(f'printf("cap %.17g\\n", LowerHemisphereCap({slot}, {low!r}, {up!r}));')
    main.append('printf("consts %.17g %.17g %.17g %.17g %.17g %.17g %.17g %d %.17g %.17g\\n", GoldenMaxSunDeg, NightSunDeg, '
                'BackdropFullAglM, BackdropNoneAglM, BackdropHorizonLowDeg, BackdropHorizonHighDeg, BackdropRadiusKm, '
                'BackdropSortPriority, BackdropOpacity, SunHoleDeg);')
    main.append("return 0; }")
    source = tmp_path / "hdri.cpp"
    source.write_text("#include <cmath>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n"
                      + block + "\n" + "\n".join(main), encoding="utf-8")
    subprocess.run(["g++", "-std=c++17", "-O1", "-Wall", "-Werror", "-Wno-unused-const-variable",
                    "-Wno-unused-variable", "-Wno-unused-function", "-o", str(tmp_path / "hdri"), str(source)],
                   check=True, capture_output=True, text=True)
    lines = subprocess.run([str(tmp_path / "hdri")], check=True, capture_output=True, text=True).stdout.splitlines()

    def rows(tag):
        return [line.split()[1:] for line in lines if line.startswith(tag + " ")]

    def py_mode(word):
        try:
            return hs.LOOK_HDRI_MODES.index(hs.mode_from(word))
        except ValueError:
            return -1
    assert [int(r[0]) for r in rows("mode")] == [py_mode(w) for w in words]
    assert [int(r[0]) for r in rows("slot")] == [hs.slot_for(hs.PRESETS[p], s) for p in presets for s in suns]
    want_yaw = [hs.cubemap_yaw_deg(lon, math.cos(math.radians(az)), math.sin(math.radians(az))) for lon, az in yaws]
    assert [float(r[0]) for r in rows("yaw")] == pytest.approx(want_yaw, abs=1e-9)
    want_ratio = [hs.hdri_ratio(c, h) for c, h in ((8000.0, 2.0), (0.0, 1.0), (1.0, 0.0), (1e-9, 1.0), (1e9, 1.0),
                                                   (3.5, 7.0))]
    assert [float(r[0]) for r in rows("ratio")] == want_ratio
    for slot, r in enumerate(rows("int")):
        new = hs.hdri_intensity(1.6, 4000.0, slot)
        assert [float(v) for v in r] == [new, hs.lower_hemisphere_scale(1.6, new)]
    for slot, r in enumerate(rows("hole")):
        name = hs.SLOT_HDRI[hs.SLOTS[slot]]
        assert [float(v) for v in r] == [hs.sun_hole_deg(slot),
                                         hs.sun_span_deg(slot, 8.0, hs.sidecar(name)["sun_elevation_deg"])]
    for slot, r in enumerate(rows("pin")):
        name = hs.SLOT_HDRI[hs.SLOTS[slot]]
        side = hs.sidecar(name)
        assert r[0] == name
        assert [float(v) for v in r[1:]] == [side["sun_longitude_deg"], side["sun_elevation_deg"],
                                             side["clamp_luminance"], side["normalise"]]
    want_bw = [hs.backdrop_weight(hs.LOOK_HDRI_MODES[m], a) for m in range(3) for a in aglss]
    assert [float(r[0]) for r in rows("bw")] == pytest.approx(want_bw, abs=1e-15)
    assert float(rows("bs")[0][0]) == hs.backdrop_scale(2.5, 0.83)
    assert [float(r[0]) for r in rows("cap")] == pytest.approx(
        [hs.lower_hemisphere_cap(slot, low, up) for slot, low, up in caps], abs=1e-15)
    c = rows("consts")[0]
    assert [float(v) for v in c[:7]] == [hs.GOLDEN_MAX_SUN_DEG, hs.NIGHT_SUN_DEG, hs.BACKDROP_FULL_AGL_M,
                                         hs.BACKDROP_NONE_AGL_M, hs.BACKDROP_HORIZON_LOW_DEG,
                                         hs.BACKDROP_HORIZON_HIGH_DEG, hs.BACKDROP_RADIUS_KM]
    assert int(c[7]) == hs.BACKDROP_SORT_PRIORITY
    assert [float(v) for v in c[8:]] == [hs.BACKDROP_OPACITY, hs.SUN_HOLE_DEG]


def test_the_cpp_gains_are_the_python_ones():
    body = HDRI_CPP[HDRI_CPP.index("inline double SlotFillGain(int Slot)"):]
    values = re.search(r"Values\[SlotCount\] = \{([^}]*)\}", body).group(1)
    assert tuple(float(v) for v in values.split(",")) == hs.SLOT_FILL_GAIN
    assert hs.MIN_RATIO == 1e-4 and "constexpr double MinRatio = 1e-4;" in HDRI_CPP
    assert hs.MAX_RATIO == 1e6 and "constexpr double MaxRatio = 1e6;" in HDRI_CPP
    assert f"constexpr double BackdropGain = {hs.BACKDROP_GAIN};" in HDRI_CPP


# -- the files ----------------------------------------------------------------------------------

def test_the_committed_files_are_the_pins_and_cc0():
    readme = (REPO / "assets" / "hdri" / "README.md").read_text(encoding="utf-8")
    licence = (REPO / "assets" / "hdri" / "LICENSE").read_text(encoding="utf-8")
    third = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    assert "CC0" in licence and "creativecommons.org/publicdomain/zero/1.0" in licence
    total = 0
    for name, row in hs.HDRIS.items():
        source = hs.source_path(name)
        assert source.stat().st_size == row["bytes"], name
        assert sky_hdri.sha256_of(source) == row["sha256"], name
        side = hs.sidecar(name)
        assert side["source_sha256"] == row["sha256"] and side["licence"] == hs.LICENCE == "CC0-1.0"
        assert side["slot"] == row["slot"] and side["clamp_factor"] == hs.CLAMP_FACTOR
        assert sky_hdri.sha256_of(hs.prepared_path(name)) == side["prepared_sha256"], name
        assert side["prepared_resolution"] == [1024, 512] and side["source_resolution"] == [2048, 1024]
        assert side["prepared_upper_mean_luminance"] == pytest.approx(1.0, rel=0.02)
        for text in (readme, licence):
            assert row["source"] in text and row["url"] in text, name
        assert row["sha256"] in readme and row["sha256"] in third
        assert row["url"].startswith("https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/2k/")
        total += source.stat().st_size + hs.prepared_path(name).stat().st_size
    assert total < 25_000_000   # modest: four 2K photographs and their 1K sky-light copies
    attributes = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "*.hdr binary" in attributes.splitlines()


def test_the_prepared_copy_reads_back_with_the_sun_clamped():
    name = hs.SLOT_HDRI["golden"]
    image = sky_hdri.read_rgbe(hs.prepared_path(name))
    assert image.shape == (512, 1024, 3)
    side = hs.sidecar(name)
    lum = sky_hdri.luminance(image)
    # the clamp, scaled by the normalisation (RGBE rounding and the box mean below it)
    assert float(lum.max()) <= side["clamp_luminance"] * side["normalise"] * 1.01
    # the sun's own pixel sits on the clamp's plateau
    row = int((90.0 - side["sun_elevation_deg"]) / 180.0 * image.shape[0])
    col = int((side["sun_longitude_deg"] + 180.0) / 360.0 * image.shape[1])
    assert float(lum[row, col]) >= 0.9 * side["clamp_luminance"] * side["normalise"]


# -- the bridge: beauty only, off is today's frame ---------------------------------------------------

def test_off_builds_nothing_and_switches_nothing():
    build = _block(HDRI_CPP, "bool FFlightSimHdriSky::Build(", "double FFlightSimHdriSky::SwitchSkyLight(")
    off = build[build.index("if (Mode == ModeOff)"):]
    off = off[:off.index("return true;")]
    for call in ("SpawnActor", "SetIntensity", "SourceType", "SetCubemap", "LoadObject", "HdriSkyLoadCube"):
        assert call not in off, call
    assert build.index("if (Mode == ModeOff)") < build.index("HdriSkyLoadCube(")
    assert 'FParse::Value(*Switches, TEXT("look-hdri="), Word);' in build
    assert "is not one of auto, light, off" in build
    switch = _block(HDRI_CPP, "double FFlightSimHdriSky::SwitchSkyLight(", "void FFlightSimHdriSky::Advance(")
    assert switch.index("if (!bWantsSwitch || bSwitched") < switch.index("SourceType = SLS_SpecifiedCubemap")
    # bWantsSwitch is set only after a mode other than off loaded its cube
    assert build.index("bWantsSwitch = true;") > build.index("if (Mode == ModeOff)")
    assert build.index("bWantsSwitch = true;") > build.index("if (!LightCube.IsValid())")


def test_the_switch_runs_after_the_sky_capture_inside_the_beauty_gate():
    at = RENDER_CPP.index("WorldBeauty.SwitchSkyLightToHdri(World, VisualScene);")
    gate = RENDER_CPP.rfind("if (", 0, at)
    assert RENDER_CPP[gate:at].startswith("if (bBeauty && WorldBeauty.IsBuilt() && WorldBeauty.WantsHdriSwitch())")
    assert RENDER_CPP.count("SwitchSkyLightToHdri(") == 1
    capture = RENDER_CPP.index("USkyLightComponent::UpdateSkyCaptureContents(World);\n\t\tFlushRenderingCommands();")
    assert capture < at
    # the scene is restored (hidden components shown) before the switch
    assert RENDER_CPP.rfind("Component->SetVisibility(true);", 0, at) > capture
    assert "S.WorldBeauty->SwitchSkyLightToHdri(S.World.Get(), *S.Visual);" in LOOKDEV_CPP
    assert CLOUDS_CPP.count("HdriSky.Build(World, Scene, Preset, SunElevationDeg, HdriSwitches, Error)") == 1
    assert CLOUDS_CPP.count("HdriSky.Advance(CameraCm, Frame);") == 1
    assert "SkyLightBaseIntensity = static_cast<float>(SkyLightBaseIntensity * Factor);" in CLOUDS_CPP
    assert "FFlightSimHdriSky HdriSky;" in CLOUDS_H


def test_the_backdrop_never_reaches_a_label_or_the_sky_capture():
    build = _block(HDRI_CPP, "bool FFlightSimHdriSky::Build(", "double FFlightSimHdriSky::SwitchSkyLight(")
    for line in ("Scene.BeautyOnlyActors.Add(Actor);", "Mesh->SetRenderCustomDepth(false);",
                 "Mesh->SetCastShadow(false);", "Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);",
                 "Actor->SetActorHiddenInGame(true);", "Mesh->SetVisibility(false);",
                 "Mesh->bVisibleInReflectionCaptures = false;", "Mesh->bVisibleInRealTimeSkyCaptures = false;"):
        assert line in build, line
    switch = _block(HDRI_CPP, "double FFlightSimHdriSky::SwitchSkyLight(", "void FFlightSimHdriSky::Advance(")
    # the lower hemisphere's alpha (the capture's lerp weight) is kept
    assert "Lower.A = LowerNow.A;" in switch
    # shown only after the final capture of the HDRI
    assert switch.rindex("HdriSkyCapture(World, Sky);") < switch.index("BackdropMesh->SetVisibility(true);")
    label = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp")
    assert "Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);" in label.read_text(encoding="utf-8")


def test_the_backdrop_material_is_unlit_translucent_and_writes_no_label_data():
    create = _block(SCRIPT, "def create_hdri_backdrop():", "\n\n\ndef ")
    for line in ('"shading_model", unreal.MaterialShadingModel.MSM_UNLIT',
                 '"blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT',
                 '"apply_cloud_fogging", True', '"compute_fog_per_pixel", True',
                 '"allow_translucent_custom_depth_writes", False', '"output_translucent_velocity", False'):
        assert line in create, line
    assert "M_FlightSimHdriBackdrop" in _script_value("WORLD_BEAUTY_MATERIALS")
    assert _script_value("WORLD_GENERATIONS")["M_FlightSimHdriBackdrop"] == "1"
    assert "create_look_hdris()" in SCRIPT and "create_hdri_backdrop()" in SCRIPT
    assert SCRIPT.index("\ncreate_look_hdris()") < SCRIPT.index("\ncreate_hdri_backdrop()")


def test_the_material_parameters_are_the_ones_the_bridge_sets():
    scalars = _script_value("WORLD_HDRI_BACKDROP_SCALARS")
    inputs = ("Dir", "Sky", "SunDir", "SceneDepth") + tuple(scalars)
    assert 'WORLD_HDRI_BACKDROP_INPUTS = ("Dir", "Sky", "SunDir", "SceneDepth") + tuple(WORLD_HDRI_BACKDROP_SCALARS)' in SCRIPT
    set_by_bridge = set(re.findall(r'SetScalarParameterValue\(TEXT\("(\w+)"\)', HDRI_CPP))
    assert set_by_bridge == set(scalars)
    assert 'SetTextureParameterValue(TEXT("Sky"), BackdropCube.Get());' in HDRI_CPP
    # the shader reads every input, and documents them in order
    header = SHADER[SHADER.index("// Inputs:"):SHADER.index("// Returns")]
    for name in inputs:
        assert name in header, name
        assert re.search(rf"\b{name}\b", SHADER[SHADER.index("float3 d ="):]), name
    assert "TextureCubeSample(Sky, SkySampler, r)" in SHADER
    # an instance nobody set draws nothing
    assert scalars["Scale"] == 0.0 and scalars["Opacity"] == 0.0
    assert scalars["HorizonLowDeg"] == hs.BACKDROP_HORIZON_LOW_DEG
    assert scalars["HorizonHighDeg"] == hs.BACKDROP_HORIZON_HIGH_DEG
    assert scalars["SkyDepthCm"] == hs.BACKDROP_SKY_DEPTH_CM
    assert "constexpr double BackdropSkyDepthCm = 1.0e8;" in HDRI_CPP


def test_the_backdrop_shader_turns_the_cube_as_the_sky_light_does():
    assert "float3 r = float3(d.x * cy - d.y * sy, d.x * sy + d.y * cy, d.z);" in SHADER
    assert "L *= (lum > ClampLum && lum > 0.0) ? ClampLum / lum : 1.0;" in SHADER
    assert "smoothstep(HorizonLowDeg" in SHADER
    # sky pixels only: nothing opaque behind the sphere is covered
    assert "w *= step(SkyDepthCm, SceneDepth);" in SHADER
    assert hs.BACKDROP_RADIUS_KM * 1e5 * 100 < hs.BACKDROP_SKY_DEPTH_CM * 1e3


def test_the_asset_paths_agree():
    for name in hs.HDRIS:
        assert hs.light_asset(name) == f"/Game/FlightSim/Sky/T_HdriLight_{name}.T_HdriLight_{name}"
        assert hs.backdrop_asset(name) == f"/Game/FlightSim/Sky/T_HdriBackdrop_{name}.T_HdriBackdrop_{name}"
    assert 'TEXT("/Game/FlightSim/Sky/%s%s.%s%s")' in HDRI_CPP
    assert 'HdriSkyAsset(TEXT("T_HdriLight_"), Slot)' in HDRI_CPP
    assert 'HdriSkyAsset(TEXT("T_HdriBackdrop_"), Slot)' in HDRI_CPP
    assert hs.BACKDROP_MATERIAL.split(".")[0] in HDRI_CPP
    assert "FLIGHTSIM_RENDER_SWITCHES" in CLOUDS_CPP[CLOUDS_CPP.index("HdriSwitches"):][:400]


def test_the_cli_lists_the_pins(capsys):
    assert hs.main(["list"]) == 0
    out = capsys.readouterr().out
    for name in hs.HDRIS:
        assert name in out
    json.dumps(hs.HDRIS)   # serialisable
