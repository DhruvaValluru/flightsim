"""Hyperreal rain (2026-11-14): the beauty rain reads as rain on camera.

The round-83 review: #07 (a tower view in heavy rain) is a flat grey screen with
sparse, short, opaque streaks; #06 and #09's rain reads as scratches. The causes
were in the code, and each fix is pinned here by reading the source (no engine on
this machine):

* the streak's length was the card camera's exposure (the documented daylight
  default 1/500 s: 2-6 px dashes); the beauty's streaks are now exposed over the
  beauty camera's 180-degree shutter (weather_look.BEAUTY_RAIN_SHUTTER_S), the
  lightning's window unchanged, the measure path's shutter unchanged;
* nothing defocused a near drop; M_RainDrops's Aperture (the lens's pupil from the
  view's field, the stated f/4 on a 36 mm sensor) grows the streak and spreads its
  light -- near drops large and soft, far ones thin;
* the coverage cap flattened every near streak to a bar (applied after the soft
  profile); it is now the mean's, the profile over it;
* the drop was a lit white surface (the unshadowed sun under the deck); SceneLit of
  its radiance is the scene's luminance behind it (drop_scene_tone.hlsl);
* the curtain drew 2 px streaks at full alpha on every shell (a 25 m drop is 0.1 px
  wide): the light of the drawn width is now the drop's (rain_veil.curtain_streak_alpha).

BEAUTY ONLY: every term is a no-op at its material default, set only through
FFlightSimWeather::ApplyBeautyRainReadability (FFlightSimWorldBeauty, -quality=beauty)
or on the beauty veil's shells; the labels and a measure render are byte-identical.
UNCALIBRATED: no frame rendered on this machine.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

from core.scene import rain_veil, weather_look

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
WEATHER_CPP = (BRIDGE / "Private" / "FlightSimWeather.cpp").read_text(encoding="utf-8")
WEATHER_H = (BRIDGE / "Public" / "FlightSimWeather.h").read_text(encoding="utf-8")
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
SHADERS = REPO / "assets" / "shaders" / "weather"
OFFSET = (SHADERS / "rain_drop_offset.hlsl").read_text(encoding="utf-8")
OPACITY = (SHADERS / "rain_drop_opacity.hlsl").read_text(encoding="utf-8")
TONE = (SHADERS / "drop_scene_tone.hlsl").read_text(encoding="utf-8")


def _assigned(name):
    for node in ast.parse(SCRIPT).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}\n", start)]


def _cpp_constant(text, name):
    match = re.search(rf"constexpr double {name} = ([0-9.eE+-]+);", text)
    assert match, name
    return float(match.group(1))


# -- the shutter: the streak's length is fall speed x the camera's exposure -----------------

def test_the_beauty_streak_is_exposed_over_the_beauty_cameras_shutter_not_the_cards():
    shape = weather_look.beauty_rain_shape(40.0, 262144)
    assert tuple(shape) == weather_look.BEAUTY_RAIN_KEYS
    assert shape["shutter_s"] == weather_look.BEAUTY_RAIN_SHUTTER_S == 1.0 / 48.0
    # The card camera's documented default (1/500 s) drew 1.8 cm of streak for a 9 m/s drop.
    assert 9.0 * shape["shutter_s"] > 5 * 9.0 / 500.0
    # Near long, far short: the length on screen is fall speed x shutter / range.
    pixel = rain_veil.BEAUTY_REFERENCE_PIXEL_RAD
    length_px = lambda range_m: 6.5 * shape["shutter_s"] / (range_m * pixel)
    assert length_px(2.0) > 60 and 8 < length_px(20.0) < 12
    # The cap (max_streak_rad) now binds only inside the near-thinned metres.
    assert 6.5 * shape["shutter_s"] / shape["max_streak_rad"] < shape["near_thin_m"]
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainShutterS") == weather_look.BEAUTY_RAIN_SHUTTER_S
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert "const double StreakShutter = BeautyShutterS > 0.0 && !bCinematicRain ? BeautyShutterS : Shutter;" \
        in advance
    assert 'TEXT("Shutter"), static_cast<float>(StreakShutter)' in advance
    assert "StepRainLayers(Wind, CameraVelocity, Share, StreakShutter, Dt, PixelAngle);" in advance
    assert 'TEXT("User.Shutter"), static_cast<float>(StreakShutter)' in advance
    # The lightning's window keeps the view's shutter.
    assert "WindowPower(Curve, Flash, T - Shutter, T)" in advance
    # Set only by the beauty readability (FFlightSimWorldBeauty's call), 0 otherwise.
    assert WEATHER_CPP.count("BeautyShutterS = Shape.ShutterS;") == 1
    assert "double BeautyShutterS = 0.0;" in WEATHER_H


# -- the lens: near drops defocused to the pupil ----------------------------------------------

def test_the_near_drops_are_defocused_to_the_lenss_pupil_and_keep_their_light():
    # f/4 on a 36 mm sensor: a 35 mm lens's pupil is 8.75 mm, a 250 mm lens's 62.5 mm.
    assert weather_look.BEAUTY_RAIN_F_NUMBER == 4.0 and weather_look.BEAUTY_RAIN_SENSOR_MM == 36.0
    fov35 = math.degrees(2.0 * math.atan(18.0 / 35.0))
    assert abs(weather_look.beauty_rain_aperture_cm(fov35) - 0.875) < 1e-6
    fov250 = math.degrees(2.0 * math.atan(18.0 / 250.0))
    assert abs(weather_look.beauty_rain_aperture_cm(fov250) - 6.25) < 1e-6
    assert weather_look.beauty_rain_aperture_cm(fov35, f_number=0.0) == 0.0
    assert weather_look.beauty_rain_aperture_cm(0.0) == 0.0
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainFNumber") == weather_look.BEAUTY_RAIN_F_NUMBER
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainSensorMm") == weather_look.BEAUTY_RAIN_SENSOR_MM
    aperture = _function(WEATHER_CPP, "double FFlightSimWeather::BeautyApertureCm(")
    assert "BeautySensorMm / (2.0 * FMath::Tan(FMath::DegreesToRadians(HorizontalFovDeg) * 0.5))" in aperture
    assert "return FocalMm / BeautyFNumber / 10.0;" in aperture
    assert "!(BeautyFNumber > 0.0)" in aperture
    advance = _function(WEATHER_CPP, "void FFlightSimWeather::Advance(")
    assert "if (BeautyFNumber > 0.0)" in advance
    assert 'TEXT("Aperture")' in advance and "BeautyApertureCm(View.HorizontalFovDeg)" in advance
    assert WEATHER_CPP.count('TEXT("Aperture")') == 1
    # Both shaders grow the streak by the pupil, after the soft widening, and the opacity's
    # coverage (D / streak x width / drawn width) then spreads the same light over it.
    for text in (OFFSET, OPACITY):
        assert "if (Aperture > 0.0)" in text
        assert text.index("width *= 1.0 + Soft;") < text.index("if (Aperture > 0.0)")
        block = text[text.index("if (Aperture > 0.0)"):]
        assert "streak += Aperture;" in block and "width += Aperture;" in block
        assert re.search(r"//\s+Aperture\s", text)
    assert OPACITY.index("width += Aperture;") < OPACITY.index(
        "float coverage = (diameterCm / streak) * (widthCm / width) * Weight;")


# -- the cap: on the mean, the soft profile over it ----------------------------------------------

def test_the_coverage_cap_is_on_the_streaks_mean_and_the_profile_survives_it():
    assert weather_look.BEAUTY_RAIN_MAX_COVERAGE == 0.15
    # The Gaussian's centre of a capped streak: 2.27 x 1.31 x the cap, below opaque.
    peak = weather_look.BEAUTY_RAIN_MAX_COVERAGE / 0.441 / 0.763
    assert 0.4 < peak < 0.5
    cap = OPACITY.index("float shown = min(saturate(coverage), MaxCoverage);")
    profile = OPACITY.index("if (Soft > 0.0 || Vary > 0.0)")
    assert cap < profile, "the cap is applied before the soft profile"
    assert "shown = saturate(shown * across * along * bright);" in OPACITY
    assert "coverage *= across * along * bright;" not in OPACITY
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainMaxCoverage") == weather_look.BEAUTY_RAIN_MAX_COVERAGE


# -- the light: the drop's radiance partly the scene behind it ------------------------------------

def test_the_drop_takes_its_radiance_from_the_scene_behind_it_beauty_only():
    assert 0.0 < weather_look.BEAUTY_RAIN_SCENE_LIT < 1.0
    assert weather_look.beauty_rain_shape(10.0, 262144)["scene_lit"] == weather_look.BEAUTY_RAIN_SCENE_LIT
    assert _cpp_constant(WEATHER_CPP, "WeatherBeautyRainSceneLit") == weather_look.BEAUTY_RAIN_SCENE_LIT
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    assert 'RainMaterial->SetScalarParameterValue(TEXT("SceneLit")' in readability
    assert WEATHER_CPP.count('TEXT("SceneLit")') == 1
    for key in ("shutter_s", "f_number", "sensor_mm", "scene_lit"):
        assert f'TEXT("{key}")' in readability, key
    # The shader: one SceneColor tap at offset 0 (as the veil's), luminance x SceneLit.
    assert "float lum = dot(A, float3(0.2126, 0.7152, 0.0722));" in TONE
    assert "return float3(lum, lum, lum) * SceneLit;" in TONE
    assert re.search(r"//\s+A\s", TONE) and re.search(r"//\s+SceneLit\s", TONE)
    lit = SCRIPT[SCRIPT.index("def drop_lit"):SCRIPT.index("def _translucent_unlit")]
    assert "def drop_lit(material, lib, x, y, scene_lit=False):" in lit
    assert 'custom(material, lib, "drop_scene_tone"' in lit
    assert "unreal.MaterialExpressionOneMinus, lit_share" in lit   # the lit term keeps 1 - SceneLit
    assert 'tap.set_editor_property("const_input", unreal.Vector2D(0.0, 0.0))' in lit
    assert "MaterialExpressionAdd, glow, tone" in lit   # added to the flash's emissive
    drops = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def _veil_lit")]
    assert "drop_lit(material, lib, -900, 800, scene_lit=True)" in drops
    splash = SCRIPT[SCRIPT.index("def create_rain_splash"):SCRIPT.index("def create_rain_drops")] \
        if SCRIPT.index("def create_rain_splash") < SCRIPT.index("def create_rain_drops") \
        else SCRIPT[SCRIPT.index("def create_rain_splash"):]
    assert "scene_lit=True" not in splash.split("\ndef ", 2)[0]   # the splashes are unchanged


# -- the material: every new parameter exposed, default the measure path's, generation bumped ---

def test_the_new_parameters_are_exposed_default_off_and_the_generation_is_bumped():
    params = _assigned("DROPS_PARAMETERS")
    assert "Aperture" in params and "SceneLit" in params
    defaults = _assigned("DROPS_BEAUTY_DEFAULTS")
    assert defaults["Aperture"] == 0.0 and defaults["SceneLit"] == 0.0
    assert _assigned("STORM_GENERATIONS")["M_RainDrops"] == "7"
    drops = SCRIPT[SCRIPT.index("def create_rain_drops"):SCRIPT.index("def _veil_lit")]
    before, after = drops.split('lib, "rain_drop_opacity"')
    assert '"Aperture": params["Aperture"]' in before and '"Aperture": params["Aperture"]' in after
    # SceneLit is made inside drop_lit, not as a dangling weather parameter.
    assert '"FlashLux", "SceneLit")}' in drops
    # The curtain is not rebuilt for this (its graph is unchanged).
    assert _assigned("STORM_GENERATIONS")["M_RainCurtain"] == "6"


# -- the curtain: a widened streak keeps its drop's light ----------------------------------------

def test_the_curtain_streak_keeps_the_light_of_the_drops_true_width():
    assert rain_veil.VEIL_STREAK_PROFILE_MEAN == 0.441
    # exp(-16 x^2) over |x| <= 0.5 averages 0.441.
    xs = [i / 2000.0 - 0.5 for i in range(2001)]
    assert abs(sum(math.exp(-16.0 * x * x) for x in xs) / len(xs) - 0.441) < 0.002
    pixel = rain_veil.BEAUTY_REFERENCE_PIXEL_RAD
    near = rain_veil.curtain_streak_alpha(25.0, pixel, 2.0)
    far = rain_veil.curtain_streak_alpha(250.0, pixel, 2.0)
    assert 0.0 < far < near < rain_veil.VEIL_STREAK_ALPHA
    assert abs(near / far - 10.0) < 1e-9   # x true width / drawn width: 1 / range
    # A 250 mm lens (7x the reference pixel) nearly resolves a 25 m drop and keeps most of it.
    long_lens = rain_veil.curtain_streak_alpha(25.0, pixel / 7.0, 2.0)
    assert near < long_lens <= rain_veil.VEIL_STREAK_ALPHA
    assert rain_veil.curtain_streak_alpha(25.0, 0.0, 2.0) == rain_veil.VEIL_STREAK_ALPHA
    veil = WEATHER_CPP[WEATHER_CPP.index("namespace FlightSimRainVeil\n{\n\tconstexpr double VeilShellRadiusNearM"):]
    assert _cpp_constant(veil, "VeilStreakProfileMean") == rain_veil.VEIL_STREAK_PROFILE_MEAN
    alpha = _function(WEATHER_CPP, "double FFlightSimWeather::CurtainStreakAlpha(")
    assert "ShellRadiusM * WeatherCmPerMetre * VeilStreakPixels * VeilStreakProfileMean * PixelAngle" in alpha
    assert "PresentedWidthMm(FMath::Max(D0Mm, 0.5)) * 0.1 / DrawnCm" in alpha
    step = _function(WEATHER_CPP, "void FFlightSimWeather::StepBeautyRainVeil(")
    assert "CurtainStreakAlpha(VeilShellRadiiM[Shell], PixelAngle)" in step
    assert 'TEXT("StreakAlpha")' in step
    assert "double CurtainStreakAlpha(double ShellRadiusM, double PixelAngle) const;" in WEATHER_H


# -- beauty only: the defaults are the measure path's, expression for expression ----------------

def test_every_hyperreal_term_is_a_no_op_at_its_default():
    # Aperture 0: neither shader enters its block; MaxCoverage 1 and Soft = Vary = 0:
    # shown = min(saturate(coverage), 1) = saturate(coverage), as before; SceneLit 0:
    # base x (1 - 0), emissive + lum x 0.
    assert OFFSET.count("if (Aperture > 0.0)") == 1 and OPACITY.count("if (Aperture > 0.0)") == 1
    assert "float shown = min(saturate(coverage), MaxCoverage);" in OPACITY
    assert '"Aperture": 0.0, "SceneLit": 0.0' in SCRIPT
    # The shutter, lens and scene-lit share are set in one place: the beauty readability.
    readability = _function(WEATHER_CPP, "void FFlightSimWeather::ApplyBeautyRainReadability(")
    for name in ("BeautyShutterS", "BeautyFNumber", "BeautySensorMm"):
        assert f"{name} = Shape.{name[6:]};" in readability, name
        assert WEATHER_CPP.count(f"{name} = Shape.") == 1, name
    # The measure path's shutter line is untouched.
    assert ("const double Shutter = bCinematicRain ? WeatherCinematicShutterS : "
            "FMath::Max(View.ShutterSeconds, 1.0e-5);") in WEATHER_CPP
