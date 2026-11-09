"""The beauty look: light, exposure, grade and lens for ``-quality=beauty``.

One function, :func:`plan_beauty_look`, turns the render's sun, weather and
camera into the ``beauty_look.json`` sidecar the render commandlet reads via
``-beauty-look=`` (FlightSimBeautyLook.cpp). The commandlet applies it to
the beauty capture ONLY, echoes it, and records what it read back into
``render.json`` under ``beauty_look``. VISUAL ONLY: physics never reads it,
and the ``measure`` quality never receives the flag, so every Gate 6
measurement stands byte for byte.

What is decided here, and on what basis
---------------------------------------
* **Sun in lux: ONE transmittance model, the physical sky's.** The light's
  intensity is the OUTER-SPACE solar illuminance,
  :data:`core.sky.plan.SUN_ILLUMINANCE_LUX` (the same number the -sky= plan
  puts on its sun), and the engine dims AND reddens it once, per pixel, along
  the real sun direction. Read in the UE 5.7.4 source: with
  ``bPerPixelAtmosphereTransmittance`` on, the light's CPU illuminance is the
  outer-space one with no transmittance applied
  (DirectionalLightComponent.cpp
  ``GetSunIlluminanceAccountingForSkyAtmospherePerPixelTransmittance``), and
  the shader samples the transmittance LUT at the pixel's own zenith angle
  (SkyAtmosphereCommon.ush ``GetAtmosphereTransmittance``), so the
  ``TransmittanceMinLightElevationAngle = 90`` floor never reaches it. Every
  beauty render turns per-pixel transmittance on (the world lane's
  FlightSimClouds.cpp ApplyAtmosphere, or the -sky= plan); the host refuses a
  beauty look whose sun is in outer-space lux while it is off. The same lux
  is the sky atmosphere's input, so the sky dome, the captured sky light and
  the aerial perspective are lit by the real sun too. A stated
  ``scene.sun_lux`` is the user's and goes on the light unchanged (it is
  then the outer-space number as well).
* **Sun colour.** The engine's per-pixel transmittance is the ONLY owner:
  no temperature band, no grade temperature. A golden-hour sun is dimmed and
  warmed once, by the atmosphere. (The lighting block's stated
  ``color_temperature_k`` and the X-Plane colours stay the lighting lane's;
  the beauty host never tints the sun, so no 8-bit comparison of the light
  colour decides anything.)
* **Exposure.** MANUAL EV100 per sun-elevation band
  (:data:`EV100_BANDS`), a sunlit scene at EV100 14.5-15, realised through
  the physical camera (aperture, 180-degree shutter, ISO 100) plus the
  compensation that lands the band's EV100. Manual, not auto with tight
  limits: beauty clips carry labels too, and a meter that re-reads the
  frame as bank changes the bright-ground fraction is the "breathing"
  Gate 6 forbids; Local Exposure handles the shadowed valleys instead.
  Every renderable elevation (the render floor to 90 deg, by test) is
  within :data:`EV100_METER_TOLERANCE_STOPS` of the incident-meter EV100 of
  the modelled clear-sky horizontal illuminance (IES clear-sky diffuse plus
  the direct beam). The band then follows the light the scene actually gets
  (:func:`scene_light`): the world preset's cloud deck
  (core/scene/world_beauty.py select_preset, the same selector the world
  lane draws with) and the lighting look's sun and sky-fill scales move the
  target by log2 of the metered ratio, and its ``brightness_ev`` stops land
  on top. A card's exposure triple or the physical sky's plan wins over the
  band (the host keeps them, and says so).
* **Tonemap.** UE's filmic (ACES-fitted) tonemapper with its 5.7
  constructor defaults set EXPLICITLY (read from Engine/Private/Scene.cpp),
  so the record names the curve rather than "default".
* **Grade.** Post-process colour grading per named look
  (:data:`GRADES`: golden_hour, desert_noon, storm, overcast), not a LUT
  texture: no asset to author on the render machine, deterministic, and
  every number is in the record. Chosen automatically from the world
  preset (the world lane's own selector), then the sun (:func:`grade_for`),
  or forced by ``grade=``. Each grade's only colour-temperature knob is its
  ``WhiteTemp``; ColorGain is neutral on every grade. No environment switch: the
  FLIGHTSIM_* surface is frozen (core/config_surface.py, E1).
* **Lens.** :data:`LENSES` (standard, cinematic). The field of view is the
  pose solver's and is NEVER changed: the host derives the focal length
  from the capture's own FOV and the sensor width, and records both.
  Aperture-driven depth of field only on ``cinematic``, focused per frame
  at the camera-to-aircraft range (the two poses the manifest records).
  Motion blur from a 180-degree shutter. Bloom, lens flare and grain
  subtle. No lens distortion and no chromatic aberration (pixel-moving);
  :func:`pixel_effects` records what each effect does to label agreement.
* **Local exposure and reflections** (:data:`LOCAL_EXPOSURE`,
  :data:`REFLECTIONS`): UE 5.1+ bilateral local exposure for shadowed
  valleys; Lumen and screen-space reflection quality raised.

Every number marked UNCALIBRATED is a starting point chosen by reasoning,
not measured: it is set by a probe render on the render machine
(docs/visual/PROBE_LOG.md, "## look-dev", names the probe for each), and
the sidecar lists them under ``uncalibrated``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.sky.plan import SUN_ILLUMINANCE_LUX as _SKY_SUN_ILLUMINANCE_LUX

#: The sidecar's version; the host refuses one it does not know. 2: the sun
#: is outer-space lux under the engine's per-pixel transmittance, and the
#: plan carries no sun temperature (a version-1 sidecar's lux was a ground
#: direct normal over a zenith factor, and must not reach a version-2 host).
BEAUTY_LOOK_VERSION = 2

#: The refusal name for every problem with a beauty look (Python and host).
CONSTRAINT = "render.beauty_look"


class BeautyLookError(ValueError):
    """A beauty look that cannot be planned as asked, refused by name."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint


# -- sun -----------------------------------------------------------------------

#: The outer-space solar illuminance the beauty sun carries: the physical
#: sky's own number (core/sky/plan.py SUN_ILLUMINANCE_LUX, UE's documented
#: physical-sky value), so the two sun paths share ONE transmittance model.
#: Not a new value: imported, never restated.
SUN_OUTER_SPACE_LUX = _SKY_SUN_ILLUMINANCE_LUX

#: The commandlet's own ceiling (RenderSunLuxMax, core/scenario/solar.py
#: SUN_LUX_MAX): no sun is brighter than the one above the atmosphere.
SUN_LUX_CEILING = 133100.0

#: Who colours and dims the beauty sun, as the sidecar and the host state it.
SUN_TRANSMITTANCE_OWNER = "engine_per_pixel"

# -- exposure ------------------------------------------------------------------

#: (lowest sun elevation deg, EV100), highest band first: the manual exposure
#: of a beauty frame. A sunlit scene at EV100 14-15 (sunny-16 is EV 15).
#: UNCALIBRATED: set by probe render on the render machine (one probe per
#: band: the sunlit grey card at ~18% of white after the tonemapper, the
#: sky unclipped).
EV100_BANDS: Tuple[Tuple[float, float], ...] = (
    (40.0, 15.0),
    (25.0, 14.5),
    (15.0, 13.9),
    (8.0, 13.0),
    (4.0, 12.0),
    (-90.0, 11.0),
)

#: How far a band may sit from the incident meter's EV100 for the modelled
#: clear-sky horizontal illuminance at ANY renderable elevation, both edges
#: of every band included (test-enforced): a guard on the starting values,
#: not a calibration.
EV100_METER_TOLERANCE_STOPS = 1.5

#: Incident-meter calibration constant C (lux * s): E = C/100 * 2^EV100. The
#: same 250 core/sky/plan.py uses, so the two exposure paths agree.
METER_CALIBRATION_C = 250.0

#: IES clear-sky horizontal DIFFUSE illuminance, E = A + B * sin(el)^C klx
#: (IES RP-21, clear sky: A = 0.8, B = 15.5, C = 0.5). Reference only: the
#: meter column of the record, never the light.
IES_CLEAR_DIFFUSE_KLX = (0.8, 15.5, 0.5)

#: The physical camera the exposure is realised through. The aperture is
#: per lens (it also drives depth of field on the cinematic lens); the
#: shutter is the 180-degree rule at the clip's frame rate; ISO is fixed and
#: the compensation lands the band's EV100 (UE 5.7
#: PostProcessEyeAdaptation.cpp: camera EV100 = log2(N^2 * (1/t) * 100 /
#: ISO), exposure scaled by 2^bias, so bias = camera EV100 - target EV100).
CAMERA_ISO = 100.0
SHUTTER_ANGLE_DEG = 180.0

# -- tonemap -------------------------------------------------------------------

#: UE 5.7's filmic tonemapper constants, set explicitly to the engine's own
#: FPostProcessSettings constructor values (Engine/Private/Scene.cpp, read
#: on this machine): the ACES-fitted curve, named in the record. NOT
#: uncalibrated: these are the engine's, stated rather than re-tuned.
TONEMAP: Dict[str, float] = {
    "FilmSlope": 0.88,
    "FilmToe": 0.55,
    "FilmShoulder": 0.26,
    "FilmBlackClip": 0.0,
    "FilmWhiteClip": 0.04,
    "ToneCurveAmount": 1.0,
}

# -- grades --------------------------------------------------------------------

#: The four named grades, as UE post-process colour grading. Vectors are
#: (R, G, B, overall) like FVector4 in FPostProcessSettings. WhiteTemp is
#: the white-balance temperature: light at that temperature renders white,
#: so ABOVE 6500 warms the image and below cools it. ONE warmth owner per
#: grade: WhiteTemp is the grade's only colour-temperature knob, ColorGain
#: is neutral on every grade, and the sun's own colour is the atmosphere's
#: (no temperature band; the module docstring says why). ``ev100_offset``
#: adds to the band's EV100 (negative opens the exposure); the deck and the
#: lighting look's scales are metered separately (:func:`scene_light`), so
#: no grade stands in for dim light.
#: UNCALIBRATED: set by probe render on the render machine (the grade
#: probes: one clip per grade, the same frame graded four ways for the
#: contact sheet, a white quad in frame read for hue).
GRADES: Dict[str, Dict[str, Any]] = {
    "golden_hour": {
        "ColorSaturation": [1.0, 1.0, 1.0, 1.04],
        "ColorContrast": [1.0, 1.0, 1.0, 1.04],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        # A light artistic warmth on top of the atmosphere's reddening: the
        # one knob, until the 10/15/20-degree probe series is read.
        "WhiteTemp": 6700.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
    },
    "desert_noon": {
        "ColorSaturation": [1.0, 1.0, 1.0, 0.96],
        "ColorContrast": [1.0, 1.0, 1.0, 1.08],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 6500.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
    },
    "storm": {
        "ColorSaturation": [1.0, 1.0, 1.0, 0.75],
        "ColorContrast": [1.0, 1.0, 1.0, 1.1],
        "ColorGamma": [1.0, 1.0, 1.0, 0.96],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        # The storm's cool cast: its one temperature knob.
        "WhiteTemp": 6100.0,
        "WhiteTint": 0.0,
        # The deck's dim light is metered (scene_light); the commandlet's
        # storm meter (a drawn cell) may open further and records its stops.
        "ev100_offset": 0.0,
    },
    "overcast": {
        # An overcast or hazy world with no rain: neutral white, a little
        # flatter, no mood stops.
        "ColorSaturation": [1.0, 1.0, 1.0, 0.95],
        "ColorContrast": [1.0, 1.0, 1.0, 1.0],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 6500.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
    },
}
GRADE_NAMES: Tuple[str, ...] = tuple(GRADES)
#: Below this sun elevation (deg) a clear-weather beauty frame takes the
#: golden_hour grade; above it desert_noon. UNCALIBRATED: set by probe
#: render on the render machine (the 10/15/20 deg probe series).
GOLDEN_HOUR_BELOW_DEG = 15.0
#: Weather words that take the storm grade (core/scene/weather_look.py STORMS).
STORM_EVENTS = ("thunderstorm", "tornado")
#: The world preset (core/scene/world_beauty.py PRESETS, chosen by its
#: select_preset, the selector the world lane draws with) -> the grade.
#: ``clear`` falls through to the sun.
PRESET_GRADES: Dict[str, Optional[str]] = {
    "storm": "storm", "rain": "storm", "overcast": "overcast", "hazy": "overcast",
    "clear": None,
}
#: World presets drawn under a cloud deck: the direct beam is shadowed, so
#: the metered light is the overcast fraction of the clear sky
#: (core/scene/hero_lighting.py OVERCAST_ILLUMINANCE_FRACTION, the one
#: number both lanes read).
DECK_PRESETS = ("storm", "rain", "overcast")

# -- lenses --------------------------------------------------------------------

#: The two lens presets. Keys in capitals are UE FPostProcessSettings names,
#: applied verbatim by the host. ``aperture_f`` is the f-number (exposure on
#: both, depth of field on cinematic only); ``depth_of_field`` focuses at the
#: subject range per frame; the vignette stays 0 on standard because the
#: owner rejected edge shading on 2026-10-11 (core/sky/plan.py POST_PROCESS)
#: and cinematic carries a light one, stated. MotionBlurMax is the cap on
#: the smear, in percent of the frame width. Chromatic aberration
#: (SceneFringeIntensity) is 0 on both: it moves pixels off the labels.
#: UNCALIBRATED: set by probe render on the render machine (the lens probe:
#: the same clip through standard and cinematic, bloom and flare read on
#: the sun-in-frame shot).
LENSES: Dict[str, Dict[str, Any]] = {
    "standard": {
        "aperture_f": 4.0,
        "depth_of_field": False,
        "BloomIntensity": 0.35,
        "BloomThreshold": -1.0,
        "LensFlareIntensity": 0.12,
        "LensFlareThreshold": 8.0,
        "VignetteIntensity": 0.0,
        "FilmGrainIntensity": 0.02,
        "SceneFringeIntensity": 0.0,
        "MotionBlurMax": 1.0,
        "MotionBlurPerObjectSize": 0.0,
        "DepthOfFieldBladeCount": 7,
    },
    "cinematic": {
        "aperture_f": 2.0,
        "depth_of_field": True,
        "BloomIntensity": 0.45,
        "BloomThreshold": -1.0,
        "LensFlareIntensity": 0.18,
        "LensFlareThreshold": 8.0,
        "VignetteIntensity": 0.2,
        "FilmGrainIntensity": 0.035,
        "SceneFringeIntensity": 0.0,
        "MotionBlurMax": 1.0,
        "MotionBlurPerObjectSize": 0.0,
        "DepthOfFieldBladeCount": 7,
    },
}
LENS_NAMES: Tuple[str, ...] = tuple(LENSES)
DEFAULT_LENS = "standard"
#: The sensor width (mm) when the camera states none: the documented default
#: lens (35 mm on a 36 mm sensor, FlightSimRenderCommandlet.cpp).
DEFAULT_SENSOR_WIDTH_MM = 36.0

# -- local exposure and reflections -------------------------------------------

#: UE 5.1+ local exposure (bilateral): contrast scales below 1 lift the
#: shadowed valley and hold the snow without moving the global exposure.
#: UNCALIBRATED: set by probe render on the render machine (the Matterhorn
#: north-face probe: valley floor and snowfield in one frame).
LOCAL_EXPOSURE: Dict[str, float] = {
    "LocalExposureHighlightContrastScale": 0.85,
    "LocalExposureShadowContrastScale": 0.8,
    "LocalExposureDetailStrength": 1.0,
    "LocalExposureBlurredLuminanceBlend": 0.6,
    "LocalExposureMiddleGreyBias": 0.0,
}

#: Lumen and screen-space reflection quality for beauty (the GI and
#: reflection METHOD overrides are the V0 ones, unchanged). Lumen's
#: qualities are clamped by the engine to [0.25, 2] in the editor UI;
#: LumenMaxTraceDistance is in cm (default 20000 = 200 m, short for an
#: aerial frame). UNCALIBRATED: set by probe render on the render machine
#: (the lake/runway probe: wet-surface reflections at 300 m AGL, and the
#: frame time it costs).
#:
#: Integration (2026-11-09): Lumen's per-view QUALITY and DISTANCE overrides
#: (LumenReflectionQuality, LumenFinalGatherQuality, LumenSceneLightingQuality,
#: LumenMaxTraceDistance, LumenSceneViewDistance, LumenSurfaceCacheResolution)
#: have ONE owner, the render-path lane (FlightSimRenderCommandlet.cpp
#: RenderBeautyLumen* constants, recorded in render.json
#: render_settings.beauty_path.lumen_capture_overrides): they belong to the
#: quality tier, not to a grade or a lens, and the render-path block runs
#: after this look, so a value here was silently overwritten (this table's
#: 2 km trace distance became 4 km while beauty_look echoed 2 km). The look
#: keeps what only it sets.
REFLECTIONS: Dict[str, Any] = {
    "lumen_quality_owner": ("render-path lane: render.json "
                            "render_settings.beauty_path.lumen_capture_overrides"),
    "LumenSceneDetail": 2.0,
    "LumenFrontLayerTranslucencyReflections": True,
    "ScreenSpaceReflectionIntensity": 100.0,
    "ScreenSpaceReflectionQuality": 100.0,
    "ScreenSpaceReflectionMaxRoughness": 0.6,
}

#: The constants a probe render must set, as the record lists them.
UNCALIBRATED: Tuple[str, ...] = (
    "EV100_BANDS", "GRADES", "GOLDEN_HOUR_BELOW_DEG", "LENSES", "LOCAL_EXPOSURE",
    "REFLECTIONS",
)


# -- validation ------------------------------------------------------------------


def validate_grade(name: Any) -> str:
    """The grade name, or BeautyLookError by name."""
    word = str(name or "").strip().lower()
    if word not in GRADES:
        raise BeautyLookError(CONSTRAINT, f"beauty grade {name!r} is not one of "
                                          f"{', '.join(GRADE_NAMES)}")
    return word


def validate_lens(name: Any) -> str:
    """The lens preset name, or BeautyLookError by name."""
    word = str(name or "").strip().lower()
    if word not in LENSES:
        raise BeautyLookError(CONSTRAINT, f"beauty lens {name!r} is not one of "
                                          f"{', '.join(LENS_NAMES)}")
    return word


def _band(bands: Sequence[Tuple[float, float]], elevation_deg: float) -> Tuple[float, str]:
    for index, (lowest, value) in enumerate(bands):
        if elevation_deg >= lowest:
            upper = "" if index == 0 else f" and below {bands[index - 1][0]:g}"
            low = "any" if lowest <= -90.0 else f"{lowest:g} deg"
            return value, f"sun at {elevation_deg:.2f} deg: band from {low}{upper}"
    raise AssertionError("the lowest band starts at -90 deg")  # pragma: no cover


# -- the physics ------------------------------------------------------------------


def clear_sky_horizontal_lux(elevation_deg: float, altitude_m: float = 0.0) -> float:
    """Modelled clear-sky GLOBAL horizontal illuminance, lux: the Bird &
    Hulstrom direct beam on the horizontal plus the IES clear-sky diffuse.
    0 with the sun at or below the horizon. A reference for the meter
    column, never the light."""
    if elevation_deg <= 0.0:
        return 0.0
    from core.scenario.solar import illuminance_lux

    direct = illuminance_lux(elevation_deg, altitude_m=altitude_m).illuminance_lux
    s = math.sin(math.radians(elevation_deg))
    a, b, c = IES_CLEAR_DIFFUSE_KLX
    return direct * s + 1000.0 * (a + b * s ** c)


def meter_ev100(horizontal_lux: float) -> float:
    """The incident meter's EV100 for a horizontal illuminance (C = 250)."""
    return math.log2(max(horizontal_lux, 1e-6) * 100.0 / METER_CALIBRATION_C)


def ev100_band(elevation_deg: float) -> Tuple[float, str]:
    """(EV100, basis) for a sun at ``elevation_deg``."""
    return _band(EV100_BANDS, float(elevation_deg))


def sun_lux_for(elevation_deg: float, altitude_m: float = 0.0,
                stated: Optional[float] = None) -> Dict[str, Any]:
    """The light's lux: the stated one, or the outer-space solar illuminance
    (:data:`SUN_OUTER_SPACE_LUX`, the physical sky's), which the engine's
    per-pixel atmosphere transmittance dims and reddens once. None (with
    the reason) when the sun is down: the host keeps its own sun then.
    ``ground_direct_normal_lux`` is the clear-sky model's reference for
    what that transmittance should land at the ground (a probe compares
    it), never the light."""
    if stated is not None:
        from core.scenario.solar import sun_lux_problem

        problem = sun_lux_problem(stated)
        if problem:
            raise BeautyLookError(CONSTRAINT, problem)
        return {"lux": float(stated), "source": "stated",
                "transmittance": SUN_TRANSMITTANCE_OWNER,
                "basis": ("scene.sun_lux as stated, on the light unchanged (the "
                          "outer-space number: the engine's per-pixel transmittance "
                          "dims it at the ground)")}
    if elevation_deg <= 0.0:
        return {"lux": None, "source": "none",
                "basis": "the sun is at or below the horizon: no clear-sky direct beam"}
    from core.scenario.solar import illuminance_lux

    ground = illuminance_lux(elevation_deg, altitude_m=altitude_m)
    lux = min(float(SUN_OUTER_SPACE_LUX), SUN_LUX_CEILING)
    return {"lux": lux, "source": "outer_space",
            "transmittance": SUN_TRANSMITTANCE_OWNER,
            "ground_direct_normal_lux_reference": round(ground.illuminance_lux, 1),
            "air_mass": round(ground.air_mass, 4),
            "basis": (f"outer-space solar illuminance {lux:g} lx (core/sky/plan.py "
                      f"SUN_ILLUMINANCE_LUX, the physical sky's); the engine's per-pixel "
                      f"atmosphere transmittance dims and reddens it once along the real "
                      f"sun direction (no temperature band, no zenith division); "
                      f"reference only: {ground.source}, clear-sky direct normal "
                      f"{ground.illuminance_lux:.0f} lx at the ground")}


def world_preset_for_card(card: Optional[Mapping[str, Any]],
                          weather_draws_cell: bool = False) -> Tuple[str, Dict[str, Any]]:
    """(world preset, inputs) for a written card, read field for field the
    way the world lane's host reads it (FlightSimClouds.cpp Build: ``look``
    else ``randomization.look``; ``weather_look``) and chosen by the SAME
    selector (core/scene/world_beauty.py select_preset), so the grade and
    the exposure follow the world the frame is drawn in.
    ``weather_draws_cell``: the storm weather draws a cell (a thunderstorm
    event; the host also counts that as a storm)."""
    from core.scene.world_beauty import select_preset

    def obj(parent: Any, key: str) -> Dict[str, Any]:
        value = parent.get(key) if isinstance(parent, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    def num(parent: Mapping[str, Any], key: str) -> float:
        try:
            value = float(parent.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    card = card if isinstance(card, Mapping) else {}
    look = obj(card, "look") or obj(obj(card, "randomization"), "look")
    weather = obj(card, "weather_look")
    rain = max(num(look, "precipitation_rate_mmh"), num(weather, "rain_rate_mmh"))
    rain_word = str(look.get("precipitation", "")) == "rain"
    storm = str(weather.get("storm", "")) == "thunderstorm" or bool(weather_draws_cell)
    cover = 0.0
    layers = look.get("clouds")
    if isinstance(layers, list) and layers and isinstance(layers[0], Mapping):
        layer = layers[0]
        if num(layer, "top_m") > num(layer, "base_m"):
            cover = num(layer, "cover")
    visibility = num(look, "visibility_km")
    inputs = {"storm": storm, "rain_rate_mmh": rain, "precipitation_rain": rain_word,
              "cloud_cover": cover, "visibility_km": visibility}
    return select_preset(storm, rain, rain_word, cover, visibility), inputs


def grade_for(sun_elevation_deg: float, weather_event: Optional[str] = None,
              raining: bool = False, world_preset: Optional[str] = None) -> Tuple[str, str]:
    """(grade, basis) chosen from the world preset (the world lane's
    selector: :func:`world_preset_for_card`), then the weather words, then
    the sun. An overcast or hazy world never takes a sunny grade."""
    preset = str(world_preset) if world_preset is not None else None
    if preset is not None and PRESET_GRADES.get(preset):
        return PRESET_GRADES[preset], f"world preset {preset} (core/scene/world_beauty.py)"
    event = str(weather_event or "none")
    if event in STORM_EVENTS:
        return "storm", f"weather event {event}"
    if raining:
        return "storm", "rain is stated"
    if sun_elevation_deg < GOLDEN_HOUR_BELOW_DEG:
        return "golden_hour", (f"sun {sun_elevation_deg:.1f} deg, below "
                               f"{GOLDEN_HOUR_BELOW_DEG:g} deg")
    return "desert_noon", (f"sun {sun_elevation_deg:.1f} deg, at or above "
                           f"{GOLDEN_HOUR_BELOW_DEG:g} deg")


def scene_light(elevation_deg: float, altitude_m: float = 0.0, *,
                world_preset: Optional[str] = None,
                sun_intensity_scale: Optional[float] = None,
                sky_light_scale: Optional[float] = None) -> Dict[str, Any]:
    """The light the scene actually gets, as a ratio of the clear-sky meter:
    under a cloud deck (:data:`DECK_PRESETS`) the overcast fraction of the
    clear sky (the direct beam is shadowed, so the lighting look's sun scale
    does not count again); otherwise the lighting look's sun scale on the
    direct beam plus its sky-fill scale on the diffuse. ``stops`` =
    log2(ratio), added to the band's EV100 (negative opens the exposure)."""
    from core.scene.hero_lighting import OVERCAST_ILLUMINANCE_FRACTION

    clear = clear_sky_horizontal_lux(elevation_deg, altitude_m)
    sun_scale = 1.0 if sun_intensity_scale is None else max(float(sun_intensity_scale), 0.0)
    sky_scale = 1.0 if sky_light_scale is None else max(float(sky_light_scale), 0.0)
    if clear <= 0.0:
        return {"ratio": 1.0, "stops": 0.0, "horizontal_lux": 0.0,
                "basis": "the sun is down: no clear-sky reference"}
    if world_preset in DECK_PRESETS:
        ratio = float(OVERCAST_ILLUMINANCE_FRACTION)
        basis = (f"world preset {world_preset}: a cloud deck shadows the beam; "
                 f"{ratio:g} of the clear sky (core/scene/hero_lighting.py "
                 f"OVERCAST_ILLUMINANCE_FRACTION, UNCALIBRATED)")
    else:
        from core.scenario.solar import illuminance_lux

        s = math.sin(math.radians(elevation_deg))
        direct = illuminance_lux(elevation_deg, altitude_m=altitude_m).illuminance_lux * s
        diffuse = clear - direct
        ratio = (sun_scale * direct + sky_scale * diffuse) / clear
        basis = (f"clear-sky meter with the lighting look's sun x{sun_scale:g} on the "
                 f"direct beam and sky fill x{sky_scale:g} on the diffuse")
    ratio = max(ratio, 1e-3)
    return {"ratio": round(ratio, 6), "stops": round(math.log2(ratio), 4),
            "horizontal_lux": round(clear * ratio, 1), "basis": basis}


def shutter_seconds(fps: float) -> float:
    """The 180-degree shutter's exposure time at ``fps``."""
    if not (isinstance(fps, (int, float)) and math.isfinite(fps) and fps > 0):
        raise BeautyLookError(CONSTRAINT, f"a frame rate of {fps!r} has no shutter")
    return (SHUTTER_ANGLE_DEG / 360.0) / float(fps)


def camera_ev100(aperture_f: float, shutter_s: float, iso: float = CAMERA_ISO) -> float:
    """UE's physical-camera EV100: log2(N^2 / t * 100 / ISO)."""
    return math.log2(aperture_f * aperture_f / shutter_s * 100.0 / iso)


def focal_length_mm(sensor_width_mm: float, horizontal_fov_deg: float) -> float:
    """The focal length a sensor needs for a horizontal FOV (the host does
    the same from the capture's own FOV; the FOV is never changed)."""
    return sensor_width_mm / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))


def pixel_effects(lens: Mapping[str, Any], width_px: int) -> Dict[str, Any]:
    """What each beauty effect does to label agreement: ``moves`` (shifts
    pixels off the geometry the labels describe), ``softens`` (spreads
    edges, the centroid stays), ``none``. Masks, class, depth and boxes
    come from their own captures of the SAME frame, without these."""
    blur_px = float(lens["MotionBlurMax"]) / 100.0 * int(width_px)
    effects = {
        "lens_distortion": {"on": False, "effect": "moves", "note": "not implemented"},
        "chromatic_aberration": {"on": float(lens["SceneFringeIntensity"]) > 0.0,
                                 "effect": "moves",
                                 "SceneFringeIntensity": float(lens["SceneFringeIntensity"])},
        "motion_blur": {"on": True, "effect": "softens",
                        "max_smear_px": round(blur_px, 2),
                        "note": ("smears along screen velocity, at most MotionBlurMax % of "
                                 "the width; the chase aircraft moves little on screen, the "
                                 "ground most; label captures render with motion blur off")},
        "depth_of_field": {"on": bool(lens["depth_of_field"]), "effect": "softens",
                           "note": "focused at the aircraft; the background softens"},
        "bloom": {"on": float(lens["BloomIntensity"]) > 0.0, "effect": "softens",
                  "note": "screen-space glow may lighten pixels just outside the mask"},
        "lens_flare": {"on": float(lens["LensFlareIntensity"]) > 0.0, "effect": "none",
                       "note": "image-based ghosts from bright pixels; no geometry"},
        "vignette": {"on": float(lens["VignetteIntensity"]) > 0.0, "effect": "none"},
        "film_grain": {"on": float(lens["FilmGrainIntensity"]) > 0.0, "effect": "none"},
    }
    effects["pixel_moving"] = sorted(name for name, row in effects.items()
                                     if isinstance(row, dict) and row["on"]
                                     and row["effect"] == "moves")
    return effects


# -- the plan ---------------------------------------------------------------------


def plan_beauty_look(sun_elevation_deg: float, *, fps: float, width_px: int,
                     sensor_width_mm: Sequence[float] = (DEFAULT_SENSOR_WIDTH_MM,),
                     grade: Optional[str] = None, lens: str = DEFAULT_LENS,
                     weather_event: Optional[str] = None, raining: bool = False,
                     altitude_m: float = 0.0, stated_sun_lux: Optional[float] = None,
                     physical_sky: bool = False, world_preset: Optional[str] = None,
                     sun_intensity_scale: Optional[float] = None,
                     sky_light_scale: Optional[float] = None,
                     brightness_ev: Optional[float] = None) -> Dict[str, Any]:
    """The complete ``beauty_look.json``. Pure: same inputs, same bytes.

    ``sensor_width_mm``: one per camera pass, in the card's camera order
    (the host picks by ``-camera-index=``). ``physical_sky``: the -sky= plan
    lights and exposes the scene, so the sun and exposure rows are left to
    it (stated, not silently dropped). ``world_preset``: the world lane's
    preset for the card (:func:`world_preset_for_card`); it chooses the
    grade and whether a deck shadows the beam. ``sun_intensity_scale``,
    ``sky_light_scale``, ``brightness_ev``: the lighting look's (webapp
    render_look_for), which the host applies to the light and which the
    exposure therefore meters (:func:`scene_light`) and adds."""
    elevation = float(sun_elevation_deg)
    if not math.isfinite(elevation) or not -90.0 <= elevation <= 90.0:
        raise BeautyLookError(CONSTRAINT, f"a sun elevation of {sun_elevation_deg!r} deg "
                                          f"is outside -90..90")
    lens_name = validate_lens(lens)
    if grade is None:
        grade_name, grade_basis = grade_for(elevation, weather_event, raining, world_preset)
    else:
        grade_name, grade_basis = validate_grade(grade), "stated by the caller"
    sensors = [float(s) for s in sensor_width_mm]
    if not sensors or any(not math.isfinite(s) or s <= 0.0 for s in sensors):
        raise BeautyLookError(CONSTRAINT, f"sensor widths {list(sensor_width_mm)!r} must be "
                                          f"positive millimetres, one per camera")
    brightness = 0.0 if brightness_ev is None else float(brightness_ev)
    if not math.isfinite(brightness):
        raise BeautyLookError(CONSTRAINT, f"brightness_ev {brightness_ev!r} is not a number of stops")
    lens_row = LENSES[lens_name]
    grade_row = GRADES[grade_name]
    shutter = shutter_seconds(fps)
    aperture = float(lens_row["aperture_f"])
    cam_ev = camera_ev100(aperture, shutter)

    if physical_sky:
        sun = {"lux": None, "source": "physical_sky",
               "transmittance": SUN_TRANSMITTANCE_OWNER,
               "basis": "the -sky= plan lights the scene (core/sky/plan.py)"}
        exposure: Dict[str, Any] = {
            "ev100": None, "basis": "the -sky= plan's EV100 (core/sky/plan.py) stands"}
    else:
        sun = sun_lux_for(elevation, altitude_m, stated_sun_lux)
        band_ev, band_basis = ev100_band(elevation)
        light = scene_light(elevation, altitude_m, world_preset=world_preset,
                            sun_intensity_scale=sun_intensity_scale,
                            sky_light_scale=sky_light_scale)
        # Lower EV100 = more exposure: a dimmer scene opens by log2(ratio)
        # stops, and the lighting look's brightness stops brighten on top.
        target = band_ev + light["stops"] + float(grade_row["ev100_offset"]) - brightness
        horizontal = clear_sky_horizontal_lux(elevation, altitude_m)
    sun["colour"] = ("the engine's per-pixel atmosphere transmittance (one model, the "
                     "physical sky's): no temperature band, the beauty host never tints "
                     "the sun")
    if not physical_sky and sun["lux"] is None:
        # No lux on the light (the sun is down): the host keeps its unitless
        # sun, and a sunlit EV100 over a unitless sun is a black frame. The
        # host's own exposure stands.
        exposure = {
            "ev100": None,
            "basis": ("the sun is not in lux (at or below the horizon): the host's "
                      "unitless sun and its own exposure stand")}
    elif not physical_sky:
        exposure = {
            "ev100": round(target, 4),
            "band_ev100": band_ev,
            "grade_ev100_offset": float(grade_row["ev100_offset"]),
            "scene_light_stops": light["stops"],
            "scene_light_basis": light["basis"],
            "brightness_ev": brightness,
            "world_preset": world_preset,
            "basis": band_basis,
            "method": "manual (physical camera + compensation), constant over the clip",
            "aperture_f": aperture,
            "shutter_s": round(shutter, 8),
            "shutter_angle_deg": SHUTTER_ANGLE_DEG,
            "iso": CAMERA_ISO,
            "camera_ev100": round(cam_ev, 4),
            "AutoExposureBias": round(cam_ev - target, 4),
            "meter_ev100_reference": (round(meter_ev100(horizontal), 3)
                                      if horizontal > 0.0 else None),
            # The CLEAR-sky reference (hero_lighting reads it and applies its
            # own overcast fraction); the scene's own light is the next key.
            "meter_horizontal_lux_reference": round(horizontal, 1),
            "meter_horizontal_lux_scene": light["horizontal_lux"],
        }

    post = {key: value for key, value in lens_row.items()
            if key[0].isupper()}
    plan = {
        "beauty_look_version": BEAUTY_LOOK_VERSION,
        "grade": grade_name,
        "grade_basis": grade_basis,
        "lens": lens_name,
        # The world lane's preset for this card (None: no card was read).
        # The grade, the exposure's deck and the beauty X-Plane sky
        # condition (webapp xplane_lighting_flags) all read this one word.
        "world_preset": world_preset,
        "sun_elevation_deg": round(elevation, 4),
        "sun": sun,
        "exposure": exposure,
        "tonemap": {"tonemapper": "UE filmic (ACES-fitted), engine 5.7 defaults stated",
                    **TONEMAP},
        "color_grade": {key: grade_row[key] for key in
                        ("ColorSaturation", "ColorContrast", "ColorGamma", "ColorGain",
                         "ColorOffset", "WhiteTemp", "WhiteTint")},
        "camera": {
            "aperture_f": aperture,
            "depth_of_field": bool(lens_row["depth_of_field"]),
            "focus": ("per frame: |capture - aircraft actor| (the poses the manifest "
                      "records)") if lens_row["depth_of_field"] else "off (focal distance 0)",
            "sensor_width_mm": sensors,
            "fov": "the pose solver's, unchanged; focal length derived from it",
            "shutter_angle_deg": SHUTTER_ANGLE_DEG,
            "MotionBlurAmount": SHUTTER_ANGLE_DEG / 360.0,
            "MotionBlurTargetFPS": int(round(float(fps))),
            "fps": float(fps),
        },
        "lens_post": post,
        "local_exposure": {"LocalExposureMethod": "Bilateral", **LOCAL_EXPOSURE},
        "reflections": dict(REFLECTIONS),
        "pixel_effects": pixel_effects(lens_row, width_px),
        "uncalibrated": list(UNCALIBRATED),
        "note": ("VISUAL ONLY, beauty quality only; every UNCALIBRATED value is set by a "
                 "probe render on the render machine (docs/visual/PROBE_LOG.md)"),
    }
    if plan["pixel_effects"]["pixel_moving"]:
        # A pixel-moving effect is allowed only when the record names it; this
        # module's presets carry none, so reaching here means a preset changed.
        plan["note"] += ("; PIXEL-MOVING effects on: "
                         + ", ".join(plan["pixel_effects"]["pixel_moving"]))
    return plan


def write_beauty_look(plan: Mapping[str, Any], path: Path) -> Path:
    """Write the sidecar as ASCII JSON (render.json echoes it; gotcha 13)."""
    text = json.dumps(plan, indent=2, sort_keys=False, ensure_ascii=True)
    path = Path(path)
    path.write_text(text + "\n", encoding="ascii")
    return path


BEAUTY_LOOK_PREFIX = "-beauty-look="


def beauty_look_flags(path: Optional[Path], plan: Optional[Mapping[str, Any]] = None) -> List[str]:
    """The commandlet tokens: ``-beauty-look=<abs path>``, plus
    ``-sun-lux=<lux>`` when the plan puts the sun in lux. Empty when there
    is no sidecar (measure quality), so every pinned command stands."""
    if path is None:
        return []
    tokens = [f"{BEAUTY_LOOK_PREFIX}{Path(path).resolve()}"]
    lux = ((plan or {}).get("sun") or {}).get("lux")
    if lux is not None:
        # The same token builder the sensing block uses (repr, round-trips
        # the double), so the light gets exactly the plan's lux.
        from core.render.flags import sensing_flags

        tokens += sensing_flags(sun_lux=float(lux))
    return tokens
