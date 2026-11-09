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
* **Sun in lux.** The light's intensity is the clear-sky DIRECT NORMAL
  illuminance at the sun's elevation (Bird & Hulstrom 1981, already in
  core/scenario/solar.py: ~100 klx with a high sun, falling with air mass),
  divided by :data:`UE_ZENITH_TRANSMITTANCE`. Why the division (read in the
  UE 5.7 source, DirectionalLightComponent.cpp): an atmosphere sun light's
  intensity is OUTER-SPACE illuminance, and the ground receives it times
  the sky atmosphere's transmittance; this scene pins
  ``TransmittanceMinLightElevationAngle = 90`` (§6.6 gotcha 1), so that
  transmittance is always the ZENITH one. The air-mass falloff has to come
  from the number set here, and only the zenith factor is divided out. A
  stated ``scene.sun_lux`` is the user's and goes on the light unchanged.
* **Sun colour.** The same pinned zenith transmittance keeps a low sun
  white, so the beauty sun takes a colour temperature per elevation band
  (:data:`SUN_TEMPERATURE_BANDS`). The host skips it when anything else
  already coloured the sun (the lighting block, X-Plane colours).
* **Exposure.** MANUAL EV100 per sun-elevation band
  (:data:`EV100_BANDS`), a sunlit scene at EV100 14-15, realised through
  the physical camera (aperture, 180-degree shutter, ISO 100) plus the
  compensation that lands the band's EV100. Manual, not auto with tight
  limits: beauty clips carry labels too, and a meter that re-reads the
  frame as bank changes the bright-ground fraction is the "breathing"
  Gate 6 forbids; Local Exposure handles the shadowed valleys instead.
  Each band is checked (by test) against the incident-meter EV100 of the
  modelled clear-sky horizontal illuminance (IES clear-sky diffuse plus
  the direct beam), so a band cannot drift far from physics before the
  probe sets it. A card's exposure triple or the physical sky's plan wins
  over the band (the host keeps them, and says so).
* **Tonemap.** UE's filmic (ACES-fitted) tonemapper with its 5.7
  constructor defaults set EXPLICITLY (read from Engine/Private/Scene.cpp),
  so the record names the curve rather than "default".
* **Grade.** Post-process colour grading per named look
  (:data:`GRADES`: golden_hour, desert_noon, storm), not a LUT texture: no
  asset to author on the render machine, deterministic, and every number
  is in the record. Chosen automatically from the weather and the sun
  (:func:`grade_for`), or forced by ``grade=``. No environment switch: the
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

#: The sidecar's version; the host refuses one it does not know.
BEAUTY_LOOK_VERSION = 1

#: The refusal name for every problem with a beauty look (Python and host).
CONSTRAINT = "render.beauty_look"


class BeautyLookError(ValueError):
    """A beauty look that cannot be planned as asked, refused by name."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint


# -- sun -----------------------------------------------------------------------

#: The sky atmosphere's luminance transmittance at the zenith, sea level, UE
#: 5.7's Earth defaults: what the engine multiplies the light's lux by on its
#: way to the ground in this scene (the pinned +90 deg transmittance floor).
#: UNCALIBRATED: set by probe render on the render machine (the -calibration
#: white quad, sky atmosphere on vs off, at sun elevation 50 deg).
UE_ZENITH_TRANSMITTANCE = 0.90

#: The commandlet's own ceiling (RenderSunLuxMax, core/scenario/solar.py
#: SUN_LUX_MAX): no sun is brighter than the one above the atmosphere.
SUN_LUX_CEILING = 133100.0

#: (lowest sun elevation deg, light colour temperature K), highest band
#: first. The direct beam reddens with air mass; the engine cannot show it
#: here (zenith transmittance pinned). UE treats 6500 K as white.
#: UNCALIBRATED: set by probe render on the render machine (golden-hour and
#: noon probes: the sunlit side of a white quad, read for hue).
SUN_TEMPERATURE_BANDS: Tuple[Tuple[float, float], ...] = (
    (40.0, 5600.0),
    (25.0, 5200.0),
    (15.0, 4700.0),
    (8.0, 4000.0),
    (-90.0, 3300.0),
)

# -- exposure ------------------------------------------------------------------

#: (lowest sun elevation deg, EV100), highest band first: the manual exposure
#: of a beauty frame. A sunlit scene at EV100 14-15 (sunny-16 is EV 15).
#: UNCALIBRATED: set by probe render on the render machine (one probe per
#: band: the sunlit grey card at ~18% of white after the tonemapper, the
#: sky unclipped).
EV100_BANDS: Tuple[Tuple[float, float], ...] = (
    (40.0, 15.0),
    (25.0, 14.7),
    (15.0, 14.2),
    (8.0, 13.4),
    (-90.0, 12.6),
)

#: How far a band may sit from the incident meter's EV100 for the modelled
#: clear-sky horizontal illuminance at the band's representative elevation
#: (test-enforced): a guard on the starting values, not a calibration.
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

#: The three named grades, as UE post-process colour grading. Vectors are
#: (R, G, B, overall) like FVector4 in FPostProcessSettings. WhiteTemp is
#: the white-balance temperature: light at that temperature renders white,
#: so ABOVE 6500 warms the image and below cools it. ``ev100_offset`` adds
#: to the band's EV100 (negative opens the exposure) and
#: ``sun_temperature_k`` replaces the elevation band's sun colour when set.
#: UNCALIBRATED: set by probe render on the render machine (the three grade
#: probes: one clip per grade, the same frame graded three ways for the
#: contact sheet).
GRADES: Dict[str, Dict[str, Any]] = {
    "golden_hour": {
        "ColorSaturation": [1.0, 1.0, 1.0, 1.08],
        "ColorContrast": [1.0, 1.0, 1.0, 1.04],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.03, 1.0, 0.95, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 7000.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
        "sun_temperature_k": None,
    },
    "desert_noon": {
        "ColorSaturation": [1.0, 1.0, 1.0, 0.96],
        "ColorContrast": [1.0, 1.0, 1.0, 1.08],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 0.99, 0.97, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 6700.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
        "sun_temperature_k": None,
    },
    "storm": {
        "ColorSaturation": [1.0, 1.0, 1.0, 0.75],
        "ColorContrast": [1.0, 1.0, 1.0, 1.1],
        "ColorGamma": [1.0, 1.0, 1.0, 0.96],
        "ColorGain": [0.97, 0.99, 1.02, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 6100.0,
        "WhiteTint": 0.0,
        # Opens 0.7 stop under the storm's dim light; the commandlet's storm
        # meter (a drawn cell) may open further and records its own stops.
        "ev100_offset": -0.7,
        # Overcast light is neutral-to-cool, not the low sun's orange.
        "sun_temperature_k": 6500.0,
    },
}
GRADE_NAMES: Tuple[str, ...] = tuple(GRADES)
#: Below this sun elevation (deg) a clear-weather beauty frame takes the
#: golden_hour grade; above it desert_noon. UNCALIBRATED: set by probe
#: render on the render machine (the 10/15/20 deg probe series).
GOLDEN_HOUR_BELOW_DEG = 15.0
#: Weather words that take the storm grade (core/scene/weather_look.py STORMS).
STORM_EVENTS = ("thunderstorm", "tornado")

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
REFLECTIONS: Dict[str, Any] = {
    "LumenReflectionQuality": 2.0,
    "LumenFinalGatherQuality": 2.0,
    "LumenSceneLightingQuality": 2.0,
    "LumenSceneDetail": 2.0,
    "LumenMaxTraceDistance": 200000.0,
    "LumenFrontLayerTranslucencyReflections": True,
    "ScreenSpaceReflectionIntensity": 100.0,
    "ScreenSpaceReflectionQuality": 100.0,
    "ScreenSpaceReflectionMaxRoughness": 0.6,
}

#: The constants a probe render must set, as the record lists them.
UNCALIBRATED: Tuple[str, ...] = (
    "UE_ZENITH_TRANSMITTANCE", "SUN_TEMPERATURE_BANDS", "EV100_BANDS",
    "GRADES", "GOLDEN_HOUR_BELOW_DEG", "LENSES", "LOCAL_EXPOSURE",
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


def sun_temperature_band(elevation_deg: float) -> Tuple[float, str]:
    """(colour temperature K, basis) for the beauty sun."""
    return _band(SUN_TEMPERATURE_BANDS, float(elevation_deg))


def sun_lux_for(elevation_deg: float, altitude_m: float = 0.0,
                stated: Optional[float] = None) -> Dict[str, Any]:
    """The light's lux: the stated one, or the clear-sky direct normal
    illuminance over the engine's zenith transmittance. None (with the
    reason) when the sun is down: the host keeps its own sun then."""
    if stated is not None:
        from core.scenario.solar import sun_lux_problem

        problem = sun_lux_problem(stated)
        if problem:
            raise BeautyLookError(CONSTRAINT, problem)
        return {"lux": float(stated), "source": "stated",
                "basis": "scene.sun_lux as stated, on the light unchanged"}
    if elevation_deg <= 0.0:
        return {"lux": None, "source": "none",
                "basis": "the sun is at or below the horizon: no clear-sky direct beam"}
    from core.scenario.solar import illuminance_lux

    ground = illuminance_lux(elevation_deg, altitude_m=altitude_m)
    lux = min(ground.illuminance_lux / UE_ZENITH_TRANSMITTANCE, SUN_LUX_CEILING)
    return {"lux": round(lux, 1), "source": "model",
            "ground_direct_normal_lux": round(ground.illuminance_lux, 1),
            "air_mass": round(ground.air_mass, 4),
            "zenith_transmittance": UE_ZENITH_TRANSMITTANCE,
            "basis": (f"{ground.source}; clear-sky direct normal at the ground "
                      f"{ground.illuminance_lux:.0f} lx / the engine's zenith "
                      f"transmittance {UE_ZENITH_TRANSMITTANCE:g} (UNCALIBRATED): an "
                      f"atmosphere sun light's lux is outer-space illuminance and "
                      f"this scene pins its transmittance at the zenith")}


def grade_for(sun_elevation_deg: float, weather_event: Optional[str] = None,
              raining: bool = False) -> Tuple[str, str]:
    """(grade, basis) chosen from the weather and the sun."""
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
                     physical_sky: bool = False) -> Dict[str, Any]:
    """The complete ``beauty_look.json``. Pure: same inputs, same bytes.

    ``sensor_width_mm``: one per camera pass, in the card's camera order
    (the host picks by ``-camera-index=``). ``physical_sky``: the -sky= plan
    lights and exposes the scene, so the sun and exposure rows are left to
    it (stated, not silently dropped)."""
    elevation = float(sun_elevation_deg)
    if not math.isfinite(elevation) or not -90.0 <= elevation <= 90.0:
        raise BeautyLookError(CONSTRAINT, f"a sun elevation of {sun_elevation_deg!r} deg "
                                          f"is outside -90..90")
    lens_name = validate_lens(lens)
    if grade is None:
        grade_name, grade_basis = grade_for(elevation, weather_event, raining)
    else:
        grade_name, grade_basis = validate_grade(grade), "stated by the caller"
    sensors = [float(s) for s in sensor_width_mm]
    if not sensors or any(not math.isfinite(s) or s <= 0.0 for s in sensors):
        raise BeautyLookError(CONSTRAINT, f"sensor widths {list(sensor_width_mm)!r} must be "
                                          f"positive millimetres, one per camera")
    lens_row = LENSES[lens_name]
    grade_row = GRADES[grade_name]
    shutter = shutter_seconds(fps)
    aperture = float(lens_row["aperture_f"])
    cam_ev = camera_ev100(aperture, shutter)

    if physical_sky:
        sun = {"lux": None, "source": "physical_sky",
               "basis": "the -sky= plan lights the scene (core/sky/plan.py)",
               "temperature_k": None, "temperature_basis": "the -sky= plan"}
        exposure: Dict[str, Any] = {
            "ev100": None, "basis": "the -sky= plan's EV100 (core/sky/plan.py) stands"}
    else:
        sun = sun_lux_for(elevation, altitude_m, stated_sun_lux)
        if grade_row["sun_temperature_k"] is not None:
            temperature, temp_basis = (float(grade_row["sun_temperature_k"]),
                                       f"the {grade_name} grade")
        else:
            temperature, temp_basis = sun_temperature_band(elevation)
        sun["temperature_k"] = temperature
        sun["temperature_basis"] = temp_basis
        band_ev, band_basis = ev100_band(elevation)
        target = band_ev + float(grade_row["ev100_offset"])
        horizontal = clear_sky_horizontal_lux(elevation, altitude_m)
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
            "meter_horizontal_lux_reference": round(horizontal, 1),
        }

    post = {key: value for key, value in lens_row.items()
            if key[0].isupper()}
    plan = {
        "beauty_look_version": BEAUTY_LOOK_VERSION,
        "grade": grade_name,
        "grade_basis": grade_basis,
        "lens": lens_name,
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
        tokens.append(f"-sun-lux={float(lux):g}")
    return tokens
