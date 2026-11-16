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
  on top. ONE owner (:func:`exposure_target`), two bases: the band, or,
  with a -sky= plan, the plan's own clear-sky meter EV100 (round 2: before
  it the plan's EV100 stood alone, so a storm under a deck was metered for
  a clear sun and rendered black: the first Windows shot c, luma mean
  3.6/255). The plan's camera is kept and only the compensation moves. A
  card's exposure triple still wins (the host keeps it, and says so). Then
  the frame is METERED once before frame 0 under a deck, or when Lumen GI
  does not run (:data:`EXPOSURE_METER_TARGET_P90`): the prediction is
  opened to what the engine really drew, and held over the clip.
* **Tonemap.** UE's filmic (ACES-fitted) tonemapper with its 5.7
  constructor defaults set EXPLICITLY (read from Engine/Private/Scene.cpp),
  so the record names the curve rather than "default".
* **Grade.** Post-process colour grading per named look
  (:data:`GRADES`: golden_hour, desert_noon, storm, overcast), not a LUT
  texture: no asset to author on the render machine, deterministic, and
  every number is in the record. Chosen automatically from the world
  preset (the world lane's own selector), then the sun (:func:`grade_for`),
  or forced by ``grade=``. Each grade's only colour-temperature knob is its
  ``WhiteTemp`` (hyperreal-grade: :func:`white_balance_for`'s, from the
  modelled sun and sky illuminant, not the grade's); ColorGain is neutral on
  every grade. No environment switch: the
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
* **The engine look** (visual round 5, lane L1; :data:`ENGINE_LOOK`,
  :func:`engine_look_for`): the renderer's built-in lighting and post
  effects, PER WORLD PRESET (core/scene/world_beauty.py PRESETS: clear,
  hazy, overcast, rain, storm): screen-space GI and reflections, SSAO, the
  sun's cascaded and distance-field shadows (PCSS), contact shadows, local
  exposure, bloom (Gaussian, plus FFT convolution as a probe), the lens
  flare (drawn only with the sun in or just outside the frame), the film
  grain's shadow/midtone/highlight split, the volumetric fog's albedo and
  grid, the still's TSR warm-up and accumulation, and the full-frame
  filmback. Every effect has a ``-look-<name>=`` switch
  (:data:`ENGINE_LOOK_SWITCHES`, read from the command line or
  ``FLIGHTSIM_RENDER_SWITCHES``) and every value lands in render.json
  ``beauty_look.applied.engine_look``; the costly ones are PROBES whose
  ``auto`` is off on the constrained GPU (``FFlightSimWorldBeauty::
  ConstrainedGpu``: the Intel iGPU under D3D11 SM5) and on elsewhere.
  Nothing here touches the cloud march.
* **Film stock** (:data:`FILM_STOCKS`, round 5 lane L2): one film-emulation
  LUT per grade (assets/looks/film/*.cube, display-referred sRGB in and
  out, generated by scripts/make_film_luts.py from spectral datasheets),
  applied AFTER the tonemapper by the post-render pipeline
  (scripts/beauty_post.py, ffmpeg lut3d) or in-engine through
  scripts/cube_to_ue_lut.py. The record names the stock and its sha256
  (``film_stock``); the host ignores the key. Neutral grey stays neutral
  (tests/test_film_luts.py, within 2 %): no global tint.

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
from .weather_look import STORMS as _WEATHER_STORMS

#: The sidecar's version; the host refuses one it does not know. 2: the sun
#: is outer-space lux under the engine's per-pixel transmittance, and the
#: plan carries no sun temperature (a version-1 sidecar's lux was a ground
#: direct normal over a zenith factor, and must not reach a version-2 host).
#: 3 (visual round 5, L1): the ``engine_look`` block is required, and bloom,
#: lens flare, film grain and the screen-space reflection values moved out
#: of the lens and reflections rows into it (a version-3 host reads them
#: from there only, so a version-2 sidecar must not reach it).
BEAUTY_LOOK_VERSION = 3

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

#: aircraft-sharp (visual overhaul round 2): the shutter is for CLIPS. A
#: still is one instant -- its beauty sub-captures share one sim time and one
#: pose -- so the host turns motion blur off on a still
#: (FFlightSimBeautyLook::ApplyShutterPolicy; render.json
#: render_settings.beauty_path.aircraft_sharp records which ran). Round 1's
#: stills drew the J-11 as a smeared, ghosted blur: the commandlet never
#: rolled the engine's velocity frame, so the airframe's motion vector was
#: its displacement since spawn (docs/visual/PROBE_LOG.md "## aircraft-sharp").
SHUTTER_POLICY = {
    "clip": "motion blur on at the 180-degree shutter (MotionBlurAmount over MotionBlurTargetFPS)",
    "still": "motion blur off: one instant, one pose; the airframe is drawn tack sharp",
    "host": "FFlightSimBeautyLook::ApplyShutterPolicy (a still is at most one delivered frame)",
}

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

#: Round 2b (presets-colour): the tonemapper's hue guard, NOT one of the
#: engine's defaults. UE 5.7.4's FPostProcessSettings::BlueCorrection
#: (Scene.h: "Bright blue desaturates instead of going to violet"; Scene.cpp
#: default 0.6) lerps a blue-correct matrix in around the AP1 tone curve
#: (PostProcessCombineLUTs.usf) and undoes it after, so a saturated sky-blue
#: fill keeps its hue instead of skewing to violet; luminance is held by the
#: inverse, so the exposure owner's EV100 and the exposure meter's p90 do
#: not move with it. Round 0 (scenes 01, 08) read shadow midtones at hue
#: ~263 deg (violet) where a sky-blue fill sits near 205-215 deg. ExpandGamut
#: stays the engine's 1.0: its wide-gamut blue lies FURTHER from violet than
#: sRGB's, so it does not cause the cast. Applied in the combine-LUT pass,
#: which runs on every RHI (the D3D11 / SM5 render machine included).
#: UNCALIBRATED: set by probe render on the render machine (probe pc-blue:
#: round 0 scene 01 again, the cliff shadows' midtone hue read at 0.6 and 1.0).
TONEMAP_HUE: Dict[str, float] = {
    "BlueCorrection": 1.0,
}

#: hyperreal-grade (2026-11-14): the camera's shoulder, laid over the engine's
#: stated defaults (:data:`TONEMAP`) in the plan's ``tonemap`` row. The engine
#: curve's shoulder asymptotes at 1 + FilmWhiteClip = 1.04 and is then
#: clipped, so a bright cloud or a sunlit wing crosses display white with a
#: hard edge (:func:`film_tone_curve`: scene 8 x grey -> 0.99, 16 x -> clipped).
#: A real camera's response rolls into white and never clips the curve
#: itself: a white clip near 0 puts the asymptote at white, and a longer
#: shoulder starts the roll-off a little earlier (scene 4 x grey 0.935
#: against 0.944, mid-grey and the toe unchanged by construction). Only the
#: highlights move; the mids keep the engine's slope and the exposure owner's
#: EV100 stands. UNCALIBRATED: set by probe render on the render machine
#: (probe hr-shoulder: #01 and #11, the brightest cloud's sRGB histogram
#: with and without this row, no pile-up at 255).
TONEMAP_CAMERA: Dict[str, float] = {
    "FilmShoulder": 0.30,
    "FilmWhiteClip": 0.01,
}


def film_tone_curve(scene_linear: float, params: Optional[Mapping[str, float]] = None) -> float:
    """UE 5.7's filmic tone curve (TonemapCommon.ush FilmToneMap, the 1-D
    part, per channel in AP1): display-linear out for a scene-linear in,
    with the ``Film*`` parameters of ``params`` (default: :data:`TONEMAP`
    under :data:`TONEMAP_CAMERA`, the plan's row). The engine's own
    anchors are built in: scene 0.18 lands at display-linear 0.18
    (InMatch / OutMatch), and the result is clamped to the display [0, 1]
    as the shader's saturate does. A pure reference: the tests hold the
    camera shoulder to a soft roll-off, and a probe compares a frame's
    greys to it. Never applied here (the engine applies it per pixel)."""
    row = {**TONEMAP, **TONEMAP_CAMERA, **(params or {})}
    slope, toe, shoulder = float(row["FilmSlope"]), float(row["FilmToe"]), float(row["FilmShoulder"])
    black, white = float(row["FilmBlackClip"]), float(row["FilmWhiteClip"])
    toe_scale = 1.0 + black - toe
    shoulder_scale = 1.0 + white - shoulder
    in_match, out_match = 0.18, 0.18
    if toe > 0.8:
        toe_match = (1.0 - toe - out_match) / slope + math.log10(in_match)
    else:
        bt = (out_match + black) / toe_scale - 1.0
        toe_match = math.log10(in_match) - 0.5 * math.log((1.0 + bt) / (1.0 - bt)) * (toe_scale / slope)
    straight_match = (1.0 - toe) / slope - toe_match
    shoulder_match = shoulder / slope - straight_match
    log_x = math.log10(max(float(scene_linear), 1e-9))
    straight = slope * (log_x + straight_match)
    toe_colour = -black + (2.0 * toe_scale) / (1.0 + math.exp((-2.0 * slope / toe_scale) * (log_x - toe_match)))
    shoulder_colour = (1.0 + white) - (2.0 * shoulder_scale) / (
        1.0 + math.exp((2.0 * slope / shoulder_scale) * (log_x - shoulder_match)))
    toe_colour = toe_colour if log_x < toe_match else straight
    shoulder_colour = shoulder_colour if log_x > shoulder_match else straight
    t = min(max((log_x - toe_match) / (shoulder_match - toe_match), 0.0), 1.0)
    if shoulder_match < toe_match:
        t = 1.0 - t
    t = (3.0 - 2.0 * t) * t * t
    return min(max(toe_colour * (1.0 - t) + shoulder_colour * t, 0.0), 1.0)

# -- grades --------------------------------------------------------------------

#: The four named grades, as UE post-process colour grading. Vectors are
#: (R, G, B, overall) like FVector4 in FPostProcessSettings. ``ev100_offset``
#: adds to the band's EV100 (negative opens the exposure); the deck and the
#: lighting look's scales are metered separately (:func:`scene_light`), so
#: no grade stands in for dim light.
#:
#: hyperreal-grade (2026-11-14): ONE owner per quality of the picture.
#: Round 5's frames read as flat saturated navy skies (#01, #13) and dull
#: grey-brown ground (#11) because the same quality was applied three
#: times: the grade's ColorContrast (1.04 / 1.08 / 1.1) sat under the
#: engine's per-channel filmic curve (which already adds contrast AND
#: saturation to a chromatic sky: the blue channel rides the straight
#: section while red and green sit in the toe), and the film stock's own
#: S-curve (assets/looks/film, normalised to full range) came on top in
#: post. Likewise the storm's ColorSaturation 0.75 x ColorGamma 0.96 under
#: the Vision 2383 print (itself the muted stock) was desaturation twice.
#: Now: CONTRAST is the film stock's (ColorContrast 1 on every grade: the
#: stock's curve is the one S-curve after the tonemapper); SATURATION is
#: the stock's with the camera response's roll-off (:data:`CAMERA_RESPONSE`)
#: holding the most chromatic pixels; the grade keeps only a mild overall
#: saturation; WARMTH is :func:`white_balance_for`'s (the illuminant model),
#: so ``WhiteTemp`` here is each grade's white point ONLY when
#: :data:`WHITE_BALANCE` ``mode`` is ``grade`` (the round-2 numbers, kept
#: for that mode and for the lanes that read them); ColorGain is neutral on
#: every grade, and the sun's own colour is the atmosphere's (no
#: temperature band; the module docstring says why).
#: UNCALIBRATED: set by probe render on the render machine (the grade
#: probes: one clip per grade, the same frame graded four ways for the
#: contact sheet, a white quad in frame read for hue).
GRADES: Dict[str, Dict[str, Any]] = {
    "golden_hour": {
        "ColorSaturation": [1.0, 1.0, 1.0, 1.0],
        "ColorContrast": [1.0, 1.0, 1.0, 1.0],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        # mode "grade" only: a light artistic warmth over the atmosphere's.
        "WhiteTemp": 6700.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
    },
    "desert_noon": {
        "ColorSaturation": [1.0, 1.0, 1.0, 1.0],
        "ColorContrast": [1.0, 1.0, 1.0, 1.0],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        "WhiteTemp": 6500.0,
        "WhiteTint": 0.0,
        "ev100_offset": 0.0,
    },
    "storm": {
        # The 2383 print mutes the palette; the grade takes only a little more.
        "ColorSaturation": [1.0, 1.0, 1.0, 0.9],
        "ColorContrast": [1.0, 1.0, 1.0, 1.0],
        "ColorGamma": [1.0, 1.0, 1.0, 1.0],
        "ColorGain": [1.0, 1.0, 1.0, 1.0],
        "ColorOffset": [0.0, 0.0, 0.0, 0.0],
        # mode "grade" only: the storm's cool cast.
        "WhiteTemp": 6100.0,
        "WhiteTint": 0.0,
        # The deck's dim light is metered (scene_light); the commandlet's
        # storm meter (a drawn cell) may open further and records its stops.
        "ev100_offset": 0.0,
    },
    "overcast": {
        # An overcast or hazy world with no rain: a little flatter in colour,
        # no mood stops.
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
#: The grade keys the plan's ``color_grade`` row carries to the host.
GRADE_KEYS: Tuple[str, ...] = ("ColorSaturation", "ColorContrast", "ColorGamma", "ColorGain",
                               "ColorOffset", "WhiteTemp", "WhiteTint")

# -- white balance (hyperreal-grade, 2026-11-14) ---------------------------------------

#: The camera's white balance, from the light the scene is lit by. UE's
#: ``WhiteTemp`` is the temperature of the light that renders white
#: (FPostProcessSettings: 6500 leaves D65 alone, below cools the frame,
#: above warms it), so a camera on its daylight preset is ``daylight_k`` and
#: a perfect auto white balance sets it to the scene's own illuminant. Real
#: aerial photographs sit between the two: cameras' AWB keeps part of a low
#: sun's warmth on purpose, and a fixed daylight preset keeps all of it.
#: ``awb_share`` is that fraction (0: daylight, 1: the illuminant renders
#: neutral), applied in mired (1e6 / K, the near-linear scale of the
#: daylight locus). ``mode`` ``grade`` keeps each grade's own WhiteTemp
#: (:data:`GRADES`) instead, the round-2 numbers.
#: UNCALIBRATED: set by probe render on the render machine (probe hr-wb:
#: #01 (low sun) and #13 (storm) with awb_share 0, 0.35 and 1, a white quad
#: in frame read for hue; the share that reads as a photograph, not a gel).
WHITE_BALANCE: Dict[str, Any] = {
    "mode": "illuminant",
    "daylight_k": 6500.0,
    "awb_share": 0.35,
    "clamp_k": (4500.0, 7500.0),
}

#: The illuminant model behind :func:`white_balance_for`, stated, not
#: measured: the direct sun reddens with the air mass it crosses (Kasten &
#: Young 1989 air mass; the sun's CCT falls by ``sun_mired_per_air_mass``
#: mired per unit of air mass over 1, from ``sun_zenith_k`` at the zenith:
#: about 4500 K at 10 deg, 3600 K at 5 deg, floored at ``sun_floor_k``); a
#: clear sky's diffuse fill is blue (``clear_sky_k``); an overcast deck's
#: light is a little bluer than D65 (``overcast_sky_k``). A sunlit surface
#: facing the sun (the airframe a beauty frame is about) sees the two mixed
#: by their shares of ITS illuminance: the direct NORMAL beam plus the IES
#: diffuse (:func:`clear_sky_horizontal_lux`'s terms, the beam not
#: projected), in mired; so a low sun stays the warm light it is, where a
#: horizontal meter would read the blue sky instead. Under a deck it sees
#: the overcast sky alone.
#: UNCALIBRATED: set by probe render on the render machine (probe hr-wb: a
#: white quad's hue against the engine's own per-pixel transmittance at 5,
#: 10, 20 and 40 deg).
ILLUMINANT_MODEL: Dict[str, float] = {
    "sun_zenith_k": 5800.0,
    "sun_mired_per_air_mass": 11.0,
    "sun_floor_k": 2500.0,
    "clear_sky_k": 11000.0,
    "overcast_sky_k": 6800.0,
}


def mired(kelvin: float) -> float:
    """1e6 / K: the reciprocal scale white balance moves on."""
    return 1.0e6 / float(kelvin)


def air_mass(elevation_deg: float) -> float:
    """Kasten & Young (1989) relative optical air mass for a sun at
    ``elevation_deg`` (1 at the zenith, about 5.6 at 10 deg, 38 at the
    horizon); the horizon's value below it."""
    zenith = 90.0 - max(float(elevation_deg), 0.0)
    return 1.0 / (math.cos(math.radians(zenith)) + 0.50572 * (96.07995 - zenith) ** -1.6364)


def sun_cct_k(elevation_deg: float) -> float:
    """The transmitted sun's colour temperature (K) at ``elevation_deg``
    (:data:`ILLUMINANT_MODEL`): the zenith sun reddened by the air mass,
    floored at the horizon."""
    m = ILLUMINANT_MODEL
    reddened = mired(m["sun_zenith_k"]) + float(m["sun_mired_per_air_mass"]) * (air_mass(elevation_deg) - 1.0)
    return max(1.0e6 / reddened, float(m["sun_floor_k"]))


def scene_illuminant_k(elevation_deg: float, world_preset: Optional[str] = None,
                       deck_drawn: Optional[bool] = None, altitude_m: float = 0.0) -> Dict[str, Any]:
    """The colour temperature (K) of the light on a sunlit surface facing
    the sun, and how it was mixed: under a drawn deck the overcast sky;
    under an open sky the direct normal beam and the blue diffuse mixed in
    mired by their shares of that surface's illuminance; the sky alone with
    the sun down."""
    m = ILLUMINANT_MODEL
    if under_deck(world_preset, deck_drawn):
        return {"kelvin": float(m["overcast_sky_k"]), "sun_k": None, "sky_k": float(m["overcast_sky_k"]),
                "direct_share": 0.0, "basis": f"world preset {world_preset}: the deck's light is the "
                                              f"overcast sky, {m['overcast_sky_k']:g} K"}
    clear = clear_sky_horizontal_lux(elevation_deg, altitude_m)
    sky_k = float(m["clear_sky_k"])
    if clear <= 0.0:
        return {"kelvin": sky_k, "sun_k": None, "sky_k": sky_k, "direct_share": 0.0,
                "basis": f"the sun is down: the clear sky's fill alone, {sky_k:g} K"}
    from core.scenario.solar import illuminance_lux

    normal = illuminance_lux(elevation_deg, altitude_m=altitude_m).illuminance_lux
    diffuse = max(clear - normal * math.sin(math.radians(elevation_deg)), 0.0)
    share = min(max(normal / max(normal + diffuse, 1e-6), 0.0), 1.0)
    sun_k = sun_cct_k(elevation_deg)
    mixed = 1.0e6 / (share * mired(sun_k) + (1.0 - share) * mired(sky_k))
    return {"kelvin": round(mixed, 1), "sun_k": round(sun_k, 1), "sky_k": sky_k,
            "direct_share": round(share, 4),
            "basis": (f"sun at {float(elevation_deg):.2f} deg: the transmitted sun {sun_k:.0f} K "
                      f"({share:.0%} of a sun-facing surface's illuminance) and the clear sky's fill "
                      f"{sky_k:g} K, mixed in mired")}


def white_balance_for(elevation_deg: float, grade: str, world_preset: Optional[str] = None,
                      deck_drawn: Optional[bool] = None, altitude_m: float = 0.0,
                      settings: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """THE white-balance owner: the plan's ``color_grade.WhiteTemp`` and
    the row that says why. Mode ``illuminant`` (:data:`WHITE_BALANCE`):
    the daylight preset moved ``awb_share`` of the way, in mired, to the
    modelled scene illuminant (:func:`scene_illuminant_k`), clamped. Mode
    ``grade``: the grade's own WhiteTemp (:data:`GRADES`). WhiteTint is 0
    in both: no owner tints off the daylight locus."""
    wb = {**WHITE_BALANCE, **(settings or {})}
    name = validate_grade(grade)
    mode = str(wb.get("mode", "illuminant"))
    if mode not in ("illuminant", "grade"):
        raise BeautyLookError(CONSTRAINT, f"white balance mode {mode!r} is not illuminant or grade")
    if mode == "grade":
        return {"WhiteTemp": float(GRADES[name]["WhiteTemp"]), "WhiteTint": 0.0, "mode": mode,
                "owner": "white_balance_for (mode grade: the grade's own white point)",
                "basis": f"GRADES[{name!r}].WhiteTemp, the round-2 number; the illuminant is not read"}
    share = float(wb["awb_share"])
    if not math.isfinite(share) or not 0.0 <= share <= 1.0:
        raise BeautyLookError(CONSTRAINT, f"white balance awb_share {wb['awb_share']!r} is not 0..1")
    low, high = (float(v) for v in wb["clamp_k"])
    daylight = float(wb["daylight_k"])
    scene = scene_illuminant_k(elevation_deg, world_preset, deck_drawn, altitude_m)
    target_mired = mired(daylight) + share * (mired(scene["kelvin"]) - mired(daylight))
    temp = min(max(1.0e6 / target_mired, low), high)
    return {
        "WhiteTemp": round(temp, 1), "WhiteTint": 0.0, "mode": mode,
        "owner": "white_balance_for (the illuminant model; the grade's WhiteTemp is not read)",
        "daylight_k": daylight, "awb_share": share, "scene_illuminant_k": scene["kelvin"],
        "clamp_k": [low, high], "illuminant": scene,
        "basis": (f"the camera's daylight white ({daylight:g} K) moved {share:g} of the way in mired "
                  f"to the scene's illuminant ({scene['kelvin']:g} K: {scene['basis']}), clamped to "
                  f"{low:g}..{high:g} K; UE renders light of WhiteTemp as white, so a low sun keeps "
                  f"{1.0 - share:.0%} of its warmth in mired, as a photograph does"),
    }


# -- camera response (hyperreal-grade, 2026-11-14) -------------------------------------

#: The post pipeline's camera response (scripts/beauty_post.py step
#: ``camera``: a 3-D LUT built from these numbers at run time, applied in
#: 16-bit after the film stock and before the 8-bit halation). It does what
#: a camera's colour pipeline does after the tone curve and the engine's
#: tonemapper does not: (1) a SATURATION ROLL-OFF, hue and luma kept: HSV
#: saturation above ``chroma_knee`` is compressed toward ``chroma_limit``
#: with a continuous soft knee (s' = k + (L - k) u / (1 + u), u = (s - k) /
#: (L - k)), so a mid-saturation colour is untouched and the navy sky
#: (saturation 0.9+ after the per-channel curve and the slide stock) comes
#: back toward a photograph's 0.6-0.8 without a hue turn; (2) HIGHLIGHT
#: DESATURATION: from display-linear luma ``highlight_from`` a smoothstep to
#: ``highlight_desaturation`` of the chroma at white, the way a sensor's
#: channels clip together, so a sunlit cloud edge rolls to white rather
#: than yellow. The grey axis is the identity by construction. ``size`` is
#: the LUT's nodes per axis.
#: UNCALIBRATED: set by probe render on the render machine (probe
#: hr-camera: #01, #11, #13 with the step on and off, the sky's HSV
#: saturation and hue read in the post frame; 0.9+ before, 0.6-0.8 after,
#: hue within 3 deg).
CAMERA_RESPONSE: Dict[str, Any] = {
    "chroma_knee": 0.6,
    "chroma_limit": 1.0,
    "highlight_from": 0.85,
    "highlight_desaturation": 0.5,
    "size": 33,
}


def camera_response_for(settings: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """The plan's ``camera_response`` row: :data:`CAMERA_RESPONSE` under
    ``settings``, validated (knee below limit, limit at most 1, the
    highlight band inside the display range, an odd LUT size of 17 or
    more), with where it is applied."""
    row = {**CAMERA_RESPONSE, **(settings or {})}
    knee, limit = float(row["chroma_knee"]), float(row["chroma_limit"])
    start, desat = float(row["highlight_from"]), float(row["highlight_desaturation"])
    size = int(row["size"])
    if not (0.0 < knee < limit <= 1.0):
        raise BeautyLookError(CONSTRAINT, f"camera response chroma_knee {knee!r} must lie below "
                                          f"chroma_limit {limit!r}, which is at most 1")
    if not (0.0 < start < 1.0 and 0.0 <= desat <= 1.0):
        raise BeautyLookError(CONSTRAINT, f"camera response highlight_from {start!r} must be inside "
                                          f"0..1 and highlight_desaturation {desat!r} within 0..1")
    if size < 17 or size % 2 == 0:
        raise BeautyLookError(CONSTRAINT, f"camera response LUT size {size!r} must be odd and 17 or more")
    return {
        "chroma_knee": knee, "chroma_limit": limit, "highlight_from": start,
        "highlight_desaturation": desat, "size": size,
        "space": "display-referred sRGB in and out, after the film stock",
        "applied_by": ("scripts/beauty_post.py step camera (a 3-D LUT built from this row, ffmpeg "
                       "lut3d tetrahedral, 16-bit, before the 8-bit halation) when "
                       "FLIGHTSIM_BEAUTY_POST=on; the host reads no such key"),
        "grey_axis": "identity", "hue": "kept", "luma": "kept below highlight_from",
    }
GRADE_NAMES: Tuple[str, ...] = tuple(GRADES)
#: Below this sun elevation (deg) a clear-weather beauty frame takes the
#: golden_hour grade; above it desert_noon. UNCALIBRATED: set by probe
#: render on the render machine (the 10/15/20 deg probe series).
GOLDEN_HOUR_BELOW_DEG = 15.0
#: Weather words that take the storm grade: core/scene/weather_look.py STORMS
#: itself, the one list the world look (world_beauty.STORM_WORDS) reads too.
STORM_EVENTS = _WEATHER_STORMS
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

#: The exposure meter (FlightSimRenderCommandlet.cpp, the storm meter's
#: loop): the beauty frame read back once before frame 0, its 90th-percentile
#: sRGB luma opened to this target by AutoExposureBias, never closed, then
#: constant over the clip (no breathing). The PREDICTED EV100 (the band or the
#: -sky= plan, plus :func:`scene_light`'s deck stops) is the starting point;
#: the meter measures what the prediction cannot know: how dark the engine's
#: own deck and rain really render, and how much of the fill is missing when
#: Lumen GI does not run (the D3D11 / SM5 laptop, 2026-11-09: shot c at a
#: luma mean of 3.6/255). Per world preset under a deck; ``no_lumen_gi`` is
#: the target any beauty look meters to when the host finds Lumen GI
#: unsupported on its shader platform (DoesPlatformSupportLumenGI). The bright
#: end of a clear frame is sunlit ground and sky, already above it, so the
#: meter changes nothing there; it only stops a frame from going black.
#: UNCALIBRATED: set by probe render on the render machine (shot c under rain
#: and an overcast probe, the p90 luma read before and after).
EXPOSURE_METER_TARGET_P90: Dict[str, float] = {
    "storm": 0.40,
    "rain": 0.45,
    "overcast": 0.55,
    "no_lumen_gi": 0.45,
}

#: hl-exposure (2026-11-15): what the no-Lumen frame meter does under a CLEAR
#: sky (no deck drawn). ``incident`` (the new default): it does not run; the
#: exposure is the incident meter's (the band or the -sky= plan, moved by
#: :func:`scene_light`), the one physical exposure a photographer sets from
#: the light, and the subject meter keeps its highlight guard. ``frame``
#: (the old behaviour, ``-exposure-anchor=frame``): the frame's p90 is opened
#: to ``no_lumen_gi`` as before. Why: the p90 reads the frame's CONTENT, not
#: its light. Missing Lumen GI removes bounce from the SHADOWS, while a clear
#: frame's p90 is sunlit sky, sea or cloud top, which no GI changes; so the
#: meter opened a clear frame only because its content was dark. Scene #13
#: (747 at 10 km over the sea, round 199, 40c95c10): with the cumulus layer
#: below, the frame's p90 is 0.48 (cloud tops), inside the target's
#: tolerance, and the airframe's whites sit at sRGB 0.82-0.87 -- where
#: :func:`film_tone_curve` puts a 0.9-albedo sunlit white at the incident
#: exposure (scene-linear ~1.0 -> sRGB 0.87), i.e. that frame is exposed
#: for the light. With the layer off the p90 is the dark sea and the meter
#: opens it: the same light at a different exposure. A real camera at
#: sunny-16 (ISO 2720 incident meter, C = 250) does not brighten the sky
#: because the clouds below went away. Under a deck the meter still runs
#: (a deck's darkness is light, not content).
EXPOSURE_ANCHORS: Tuple[str, ...] = ("incident", "frame")
DEFAULT_EXPOSURE_ANCHOR = "incident"
EXPOSURE_ANCHOR_SWITCH = "-exposure-anchor="

#: Lane A (2026-11-11): the SUBJECT meter, the host's last word on a beauty
#: exposure this look owns (FlightSimRenderCommandlet.cpp, after the frame
#: meter above; these are its constants' twins, pinned by test). A
#: photographer meters the aircraft, not the sky behind it. Round 4's #04 and
#: #13 drew the airframe as clipped white plastic (the frame meter opened a
#: dark canyon / ocean frame by its p90 and the white paint went over the top);
#: round 5's #06 and #08 drew it black under a bright deck (the frame's p90 was
#: the cloud base). The aircraft's pixels are found by difference (a capture
#: with it hidden against one with it shown, inside its projected bounds): a
#: subject whose 97th-percentile sRGB luma clips is closed to the highlight
#: target; one whose median is under the floor is opened toward the mid
#: target, never past its own highlight bound nor a clipping frame. Constant
#: over the clip (no breathing). ``-subject-meter=off`` keeps the frame
#: meter's exposure. UNCALIBRATED: set by probe render on the render machine
#: (docs/visual/PROBE_LOG.md "## lane A": #04, #13, #06, #08, #01).
SUBJECT_METER: Dict[str, float] = {
    "highlight_p97": 0.94,
    "highlight_target_p97": 0.88,
    "mid_floor_p50": 0.30,
    "mid_target_p50": 0.36,
    "max_close_stops": 3.0,
    "max_open_stops": 1.0,   # round 7: 2 stops bleached #4 and #6 (the frame, not just the aircraft)
    "saturated_step_stops": 1.0,
    "high_percentile": 0.97,
    "rounds": 4,
    "mask_luma_delta": 16,
    "min_pixels": 200,
}
#: The frame meter's highlight bound (the host's BeautyMeterHighlightP90): a
#: frame clipping past it is never opened further by the subject meter.
FRAME_HIGHLIGHT_P90 = 0.92


def subject_meter_step(p50: float, p97: float, frame_p90: float, stops: float) -> float:
    """One subject-meter step in stops (0 = settled): the twin of the host's
    SubjectMeterStep. ``p50``/``p97`` are the aircraft's sRGB luma
    percentiles (0..1), ``frame_p90`` the whole frame's, ``stops`` what the
    subject meter has moved the bias by so far."""
    m = SUBJECT_METER
    step = 0.0
    if p97 > m["highlight_p97"]:
        step = 2.2 * 0.8 * math.log2(m["highlight_target_p97"] / p97)
        if p97 >= 254.0 / 255.0:
            step = min(step, -m["saturated_step_stops"])
    elif p50 < m["mid_floor_p50"] and frame_p90 < FRAME_HIGHLIGHT_P90:
        step = 2.2 * 0.8 * math.log2(m["mid_target_p50"] / max(p50, 1.0 / 255.0))
        step = min(step, 2.2 * math.log2(m["highlight_p97"] / max(p97, 1.0 / 255.0)))
        step = max(step, 0.0)
    nxt = min(max(stops + step, -m["max_close_stops"]), m["max_open_stops"])
    return 0.0 if abs(nxt - stops) < 0.05 else nxt - stops


def meter_luma_code(r: int, g: int, b: int) -> int:
    """The sRGB luma code (0..255) the host's meters bin a pixel by."""
    return min(max(int(0.2126 * r + 0.7152 * g + 0.0722 * b + 0.5), 0), 255)


def meter_percentile(codes, q: float) -> float:
    """The twin of the host's meter percentile (the storm/beauty meter's p90,
    the subject meter's SubjPercentile): a 256-bin histogram of luma codes,
    the first bin whose cumulative count reaches ``int(q * total)``, as 0..1.
    ``codes`` is any iterable of ints 0..255."""
    hist = [0] * 256
    total = 0
    for c in codes:
        hist[c] += 1
        total += 1
    wanted = int(q * total)
    seen = 0
    b = 0
    while b < 255 and seen + hist[b] < wanted:
        seen += hist[b]
        b += 1
    return b / 255.0


#: #9 TDR (2026-11-16): -meter-res=auto|full|half|quarter, the per-axis
#: divisor of the beauty target for the meters' metering captures (auto: half
#: on the constrained GPU, full elsewhere; measure never reduces).
METER_RES_DIVISORS: Dict[str, int] = {"full": 1, "half": 2, "quarter": 4}


#: Round 3 (2026-11-10): the share of a RELIT sun's meter gain the beauty
#: exposure takes. A lighting block that moves the physical sky's sun
#: (webapp.runs relight_sky_plan, core.sky.plan.relight) re-meters the plan's
#: incident EV100 on the new sun's HORIZONTAL illuminance; the beauty exposure
#: then closes by that whole gain. Round 1's #02 (super bright over #01's
#: golden-hour Yosemite: sun 6 -> 72 deg) closed 3.7 stops (EV100 11.6 ->
#: 15.3) for a frame of steep walls and slopes that gains far less than a
#: horizontal meter does: the high sun grazes the walls the low sun lit face
#: on, so #02 rendered DARKER than #01 (mean luma 76 vs 96) despite its +0.6 EV
#: and x1.6 sun. The preset numbers were also chosen by eye on the measure
#: path, where the calibrated look's exposure moves far less than a meter
#: between dawn and noon. So the exposure closes by this share of the gain
#: and opens the rest; a relight to a LOWER sun opens by the meter as before
#: (no share). UNCALIBRATED: set by probe render on the render machine (#02
#: against #01: super bright should read about 0.5 to 1 stop brighter).
RELIT_SUN_CLOSE_SHARE = 0.7

# -- lenses --------------------------------------------------------------------

#: The two lens presets. Keys in capitals are UE FPostProcessSettings names,
#: applied verbatim by the host. ``aperture_f`` is the f-number (exposure on
#: both, depth of field on cinematic only); ``depth_of_field`` focuses at the
#: subject range per frame; the vignette stays 0 on standard because the
#: owner rejected edge shading on 2026-10-11 (core/sky/plan.py POST_PROCESS)
#: and cinematic carries a light one, stated. MotionBlurMax is the cap on
#: the smear, in percent of the frame width. Chromatic aberration
#: (SceneFringeIntensity) is 0 on both: it moves pixels off the labels.
#: Round 5 (L1): bloom, lens flare and film grain are no longer the lens's;
#: they are per WORLD PRESET in :data:`ENGINE_LOOK` (one owner each), so a
#: storm and a clear noon differ where a real camera's would.
#: UNCALIBRATED: set by probe render on the render machine (the lens probe:
#: the same clip through standard and cinematic).
LENSES: Dict[str, Dict[str, Any]] = {
    "standard": {
        "aperture_f": 4.0,
        "depth_of_field": False,
        "VignetteIntensity": 0.0,
        "SceneFringeIntensity": 0.0,
        "MotionBlurMax": 1.0,
        "MotionBlurPerObjectSize": 0.0,
        "DepthOfFieldBladeCount": 7,
    },
    "cinematic": {
        "aperture_f": 2.0,
        "depth_of_field": True,
        "VignetteIntensity": 0.2,
        "SceneFringeIntensity": 0.0,
        "MotionBlurMax": 1.0,
        "MotionBlurPerObjectSize": 0.0,
        "DepthOfFieldBladeCount": 7,
    },
}
LENS_NAMES: Tuple[str, ...] = tuple(LENSES)
DEFAULT_LENS = "standard"
#: Camera presets that sit INSIDE the aircraft (core/scenario/camera.py
#: CAMERA_PRESETS; "shoulder" is the legacy word): the actor origin is the
#: JSBSim datum a few metres away inside the fuselage, so focusing there
#: would blur the scene the camera looks at. Their depth of field is off.
INSIDE_PRESETS = ("cockpit", "shoulder")
#: The sensor width (mm) when the camera states none: the documented default
#: lens (35 mm on a 36 mm sensor, FlightSimRenderCommandlet.cpp).
DEFAULT_SENSOR_WIDTH_MM = 36.0

# -- local exposure and reflections -------------------------------------------

#: UE 5.1+ local exposure (bilateral): contrast scales below 1 lift the
#: shadowed valley and hold the snow without moving the global exposure.
#: UNCALIBRATED: set by probe render on the render machine (the Matterhorn
#: north-face probe: valley floor and snowfield in one frame).
#:
#: Round 2 (2026-11-09, the first Windows renders): the HIGHLIGHT scale is 1
#: (the engine's own default, Engine/Private/Scene.cpp), so local exposure
#: never re-tones the sky. The bilateral grid adapts each pixel to the
#: blurred luminance of its neighbourhood (a kernel half the frame wide), and
#: a highlight scale below 1 pulled the sky band toward whatever the terrain
#: beside it was doing: a bank that swings the horizon moves the sky band's
#: tone frame to frame, which is exposure breathing by another name (Gate 6's
#: clause). Only the SHADOW side stays below 1: it lifts the shadowed valley
#: (darker than mid grey), which is what this lane is for, and the sky,
#: always above mid grey, is never on that side of the curve.
LOCAL_EXPOSURE: Dict[str, float] = {
    "LocalExposureHighlightContrastScale": 1.0,
    "LocalExposureShadowContrastScale": 0.8,
    "LocalExposureDetailStrength": 1.0,
    "LocalExposureBlurredLuminanceBlend": 0.6,
    "LocalExposureMiddleGreyBias": 0.0,
}

#: Lumen reflection settings for beauty (the GI and reflection METHOD
#: overrides are the V0 ones, unchanged). Round 5 (L1): the screen-space
#: reflection values are per world preset in :data:`ENGINE_LOOK` ``ssr``.
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
#: keeps what only it sets. UNCALIBRATED: set by probe render on the render
#: machine (the canopy probe: LumenSceneDetail 1 and 2 on head shot d).
REFLECTIONS: Dict[str, Any] = {
    "lumen_quality_owner": ("render-path lane: render.json "
                            "render_settings.beauty_path.lumen_capture_overrides"),
    "ssr_owner": "ENGINE_LOOK ssr (per world preset; beauty_look.applied.engine_look.ssr)",
    "LumenSceneDetail": 2.0,
    "LumenFrontLayerTranslucencyReflections": True,
}

# -- the engine look (visual round 5, lane L1) ----------------------------------

#: The world presets the engine look is keyed by: core/scene/world_beauty.py
#: PRESETS, chosen by the same selector the world lane draws with
#: (:func:`world_preset_for_card`). A plan with no card falls back through
#: the grade (:data:`GRADE_LOOK_PRESET`).
ENGINE_LOOK_PRESETS: Tuple[str, ...] = ("clear", "hazy", "overcast", "rain", "storm")
GRADE_LOOK_PRESET: Dict[str, str] = {
    "golden_hour": "clear", "desert_noon": "clear", "storm": "storm", "overcast": "overcast",
}

#: The refusal name for a ``-look-<name>=`` switch given a value it does not
#: take (Python and host).
LOOK_SWITCH_CONSTRAINT = "render.look_switch"

#: The switch words. An EFFECT switch takes on|off: ``off`` is the A/B
#: control, defined per effect by its ``off_means`` row (either the effect
#: off, or the frame as the earlier lanes drew it). A PROBE switch takes
#: auto|on|off: ``auto`` is off on the constrained GPU and on elsewhere,
#: so the Intel laptop sees it only when a run asks (-look-<name>=on on one
#: scene first; the hard limit on the cloud march is never touched by any
#: of them).
EFFECT_SWITCH_WORDS: Tuple[str, ...] = ("on", "off")
PROBE_SWITCH_WORDS: Tuple[str, ...] = ("auto", "on", "off")
LOOK_SWITCH_PREFIX = "-look-"

#: THE grain strength: the one constant L1 (this table) and L2 (the film
#: stock) share. The per-preset ``FilmGrainIntensity`` is this times the
#: preset's ``grain_scale``; a film stock scales it again through
#: :func:`film_grain_for` ``stock_scale`` (L2's per-stock number), never by
#: its own constant. UE's FilmGrainIntensity is 0..1 (0.03 reads as a fine
#: ISO-200 negative at 1080p). UNCALIBRATED: set by probe render on the
#: render machine (probe el-grain: #01 at 0.03 and 0.06 against a scanned
#: negative's grain at the same magnification).
GRAIN_STRENGTH = 0.03

# -- hl-exposure (2026-11-15): grain from the ISO the light asks for -----------
#
# A digital camera shows noise, not a constant grain: its visible amount
# follows the ISO the light forces. Model: the brief's daylight camera
# (core/capture/exposure.py DAYLIGHT_TRIPLE, f/8 1/500 s, EV100 14.97) keeps
# its aperture and shutter and raises ISO to meet the exposure target, so
# ISO_eq = 100 * 2^(14.97 - EV100), never below base ISO 100 (a brighter
# scene takes a faster shutter, not a lower ISO). Shot noise is Poisson
# (EMVA 1288 photon transfer): at a fixed output level the relative noise
# goes as sqrt(ISO). At base ISO a mid-grey pixel holds full_well / 7.8
# electrons: ISO 12232 puts the saturation-based speed at 78 / H_sat and
# the mid-grey exposure at 10 / S, so saturation sits 7.8x (2.96 stops)
# above mid-grey. With a ~50,000 e- full well (a 24 MP full-frame pixel,
# ~6 um pitch; photonstophotos.net / sensorgen.info measurements of that
# class) that is 6,410 e-, sigma/mu = 1.25 %, which the sRGB encoding's
# slope at 0.18 (1.195; the filmic curve maps 0.18 to 0.18) turns into
# 0.69 of an 8-bit code: below one code, i.e. invisible at base ISO. Grain
# is drawn only for the noise ABOVE one code, sigma_excess = sqrt(sigma^2 -
# 1) codes, so it is 0 up to ISO_GRAIN_VISIBLE (~213) and grows as sqrt(ISO)
# past it. GRAIN_STRENGTH is the UE intensity of one code of excess noise
# (its "fine ISO-200 negative" reading). ``-grain-model=preset`` keeps the
# round-5 per-preset grain (the old behaviour).
GRAIN_MODELS: Tuple[str, ...] = ("iso", "preset")
DEFAULT_GRAIN_MODEL = "iso"
GRAIN_MODEL_SWITCH = "-grain-model="
BASE_ISO = 100.0
SENSOR_FULL_WELL_E = 50000.0
ISO12232_SATURATION_OVER_MID = 78.0 / 10.0

#: A guard, not a match: the top of the auto-ISO range this model will
#: reach (a night or deep-storm target past it is not more grain, it is the
#: night lane's). UNCALIBRATED: set by probe render on the render machine
#: (probe hl-grain: #09 storm at -grain-model=iso and =preset, the noise
#: against a high-ISO photo of a storm at the same magnification).
ISO_GRAIN_CAP = 12800.0


def _srgb_slope(linear: float) -> float:
    """d(sRGB)/d(linear) of the IEC 61966-2-1 encoding at ``linear`` (> 0.0031308)."""
    return 1.055 / 2.4 * math.pow(linear, 1.0 / 2.4 - 1.0)


def grain_sigma_codes(iso: float) -> float:
    """Shot-noise sigma of a mid-grey pixel, in 8-bit sRGB codes, at ``iso``."""
    electrons = SENSOR_FULL_WELL_E / ISO12232_SATURATION_OVER_MID * (BASE_ISO / float(iso))
    return 0.18 / math.sqrt(electrons) * _srgb_slope(0.18) * 255.0


#: The ISO at which the mid-grey shot noise reaches one 8-bit code (~213).
ISO_GRAIN_VISIBLE = BASE_ISO / grain_sigma_codes(BASE_ISO) ** 2


def equivalent_iso(ev100_target: float) -> float:
    """The ISO the daylight camera (f/8, 1/500 s) needs for ``ev100_target``,
    clamped to [BASE_ISO, ISO_GRAIN_CAP]."""
    from core.capture.exposure import DAYLIGHT_TRIPLE, ev100 as _ev100

    iso = BASE_ISO * math.pow(2.0, _ev100(*DAYLIGHT_TRIPLE) - float(ev100_target))
    return min(max(iso, BASE_ISO), ISO_GRAIN_CAP)


def iso_grain_factor(iso: float) -> float:
    """The excess noise over one code, in codes: sqrt(max(0, sigma^2 - 1))."""
    sigma = grain_sigma_codes(iso)
    return math.sqrt(max(0.0, sigma * sigma - 1.0))

#: Lane A (2026-11-11): the SSAO radius, WORLD space, cm. Airframe scale: the
#: occlusion a real airframe has lives within a metre or two of the crease
#: (wing root, under the wing, engine pylons, intakes), so a 2 m kernel holds
#: it and leaves the open skin lit by the sky it sees. UNCALIBRATED: set by
#: probe render on the render machine (probe la-ssao: #06 and #01 at 1 / 2 /
#: 4 m, the belly and the wing root; docs/visual/PROBE_LOG.md "## lane A").
AO_RADIUS_WS_CM = 200.0

#: Every engine-look effect: its switch, whether it is a probe, what its
#: ``off`` means, which UE member or cvar each value is, and the value per
#: world preset. Keys in capitals are FPostProcessSettings members (Scene.h)
#: or light / fog component members, set verbatim by the host with their
#: bOverride_; ``cvars`` are renderer console variables set at code priority
#: for this process only and read back; ``cvars_constrained`` replace them on
#: the constrained GPU. ``stage`` says what a row touches: ``capture`` (the
#: beauty capture's post-process settings and show flags only) or ``scene``
#: (the sun, the fog, renderer cvars). The host applies every row in ONE
#: place, FFlightSimBeautyLook::ApplyEngineLook, after the render-path,
#: hero-lighting and no-lumen-fallback hooks (local exposure rides the
#: look's own post-process block, with its switch), so it is the owner of
#: record of what it sets and reads back what it does not. Every number is UNCALIBRATED: set by probe render
#: on the render machine (the probe named per row, docs/visual/PROBE_LOG.md
#: "## round-5 engine-look"); the A/B pair for each is the scene with the
#: effect on and with ``-look-<name>=off``.
ENGINE_LOOK: Dict[str, Dict[str, Any]] = {
    # 1. Screen-space GI: the stand-in for Lumen's bounce on a platform with
    # no Lumen GI (the no-lumen fallback already selects the ScreenSpace
    # method on it; this row sets its quality and the indirect intensity).
    "ssgi": {
        "switch": "ssgi", "probe": False, "stage": "scene",
        "off_means": ("DynamicGlobalIlluminationMethod None on the fallback path (the sky light "
                      "alone fills the shade); Lumen machines keep Lumen"),
        "cvars": {"r.SSGI.Quality": 4.0},
        "cvars_constrained": {"r.SSGI.Quality": 3.0},
        "per_preset": {
            "clear": {"IndirectLightingIntensity": 1.0},
            "hazy": {"IndirectLightingIntensity": 1.05},
            "overcast": {"IndirectLightingIntensity": 1.15},
            "rain": {"IndirectLightingIntensity": 1.15},
            "storm": {"IndirectLightingIntensity": 1.1},
        },
        "probe_name": "el-ssgi (#01 canyon shade and #09 belly, quality 3 and 4, on and off)",
    },
    # 2. Screen-space reflections: canopy glass, wet ground, the ocean.
    "ssr": {
        "switch": "ssr", "probe": False, "stage": "scene",
        "off_means": "ReflectionMethod None (sky light specular only)",
        "cvars": {"r.SSR.Quality": 4.0, "r.SSR.HalfResSceneColor": 0.0},
        "cvars_constrained": {"r.SSR.Quality": 3.0, "r.SSR.HalfResSceneColor": 0.0},
        "per_preset": {
            "clear": {"ScreenSpaceReflectionIntensity": 100.0, "ScreenSpaceReflectionQuality": 100.0,
                      "ScreenSpaceReflectionMaxRoughness": 0.6},
            "hazy": {"ScreenSpaceReflectionIntensity": 100.0, "ScreenSpaceReflectionQuality": 100.0,
                     "ScreenSpaceReflectionMaxRoughness": 0.6},
            "overcast": {"ScreenSpaceReflectionIntensity": 100.0, "ScreenSpaceReflectionQuality": 100.0,
                         "ScreenSpaceReflectionMaxRoughness": 0.6},
            "rain": {"ScreenSpaceReflectionIntensity": 100.0, "ScreenSpaceReflectionQuality": 100.0,
                     "ScreenSpaceReflectionMaxRoughness": 0.7},
            "storm": {"ScreenSpaceReflectionIntensity": 100.0, "ScreenSpaceReflectionQuality": 100.0,
                      "ScreenSpaceReflectionMaxRoughness": 0.7},
        },
        "per_preset_constrained": {"ScreenSpaceReflectionQuality": 80.0},
        "probe_name": "el-ssr (#13 ocean and #06 wet runway, on and off; the canopy in head shot d)",
    },
    # 3. SSAO: the darkening under wings, in intakes and along panel seams.
    # Lane A (2026-11-11): the radius is in WORLD space at the airframe's
    # scale (AO_RADIUS_WS_CM). It was view-space (locked to the 400-unit
    # view scale), a fixed share of the FRAME: on an airframe a few hundred
    # pixels wide that kernel spans whole wings, so the fuselage, wings and
    # tail occluded each other's sky light all over ("the planes are being
    # too shadowed"), most of all where the sky light is the only light
    # (under a deck, the shade side at golden hour). The Google tiles carry
    # their own baked occlusion, so they lose nothing they need.
    "ssao": {
        "switch": "ssao", "probe": False, "stage": "capture",
        "off_means": "AmbientOcclusionIntensity 0 (no SSAO)",
        "cvars": {"r.AmbientOcclusionMaxQuality": 100.0, "r.AmbientOcclusionLevels": -1.0},
        "cvars_constrained": {"r.AmbientOcclusionMaxQuality": 100.0, "r.AmbientOcclusionLevels": -1.0},
        "per_preset": {
            "clear": {"AmbientOcclusionIntensity": 0.6, "AmbientOcclusionRadius": AO_RADIUS_WS_CM,
                      "AmbientOcclusionQuality": 100.0, "AmbientOcclusionPower": 2.0,
                      "AmbientOcclusionStaticFraction": 1.0, "AmbientOcclusionMipBlend": 0.6,
                      "AmbientOcclusionTemporalBlendWeight": 0.1, "AmbientOcclusionRadiusInWS": True},
            "hazy": {"AmbientOcclusionIntensity": 0.55, "AmbientOcclusionRadius": AO_RADIUS_WS_CM,
                     "AmbientOcclusionQuality": 100.0, "AmbientOcclusionPower": 2.0,
                     "AmbientOcclusionStaticFraction": 1.0, "AmbientOcclusionMipBlend": 0.6,
                     "AmbientOcclusionTemporalBlendWeight": 0.1, "AmbientOcclusionRadiusInWS": True},
            "overcast": {"AmbientOcclusionIntensity": 0.7, "AmbientOcclusionRadius": AO_RADIUS_WS_CM,
                         "AmbientOcclusionQuality": 100.0, "AmbientOcclusionPower": 2.0,
                         "AmbientOcclusionStaticFraction": 1.0, "AmbientOcclusionMipBlend": 0.6,
                         "AmbientOcclusionTemporalBlendWeight": 0.1, "AmbientOcclusionRadiusInWS": True},
            "rain": {"AmbientOcclusionIntensity": 0.7, "AmbientOcclusionRadius": AO_RADIUS_WS_CM,
                     "AmbientOcclusionQuality": 100.0, "AmbientOcclusionPower": 2.0,
                     "AmbientOcclusionStaticFraction": 1.0, "AmbientOcclusionMipBlend": 0.6,
                     "AmbientOcclusionTemporalBlendWeight": 0.1, "AmbientOcclusionRadiusInWS": True},
            "storm": {"AmbientOcclusionIntensity": 0.65, "AmbientOcclusionRadius": AO_RADIUS_WS_CM,
                      "AmbientOcclusionQuality": 100.0, "AmbientOcclusionPower": 2.0,
                      "AmbientOcclusionStaticFraction": 1.0, "AmbientOcclusionMipBlend": 0.6,
                      "AmbientOcclusionTemporalBlendWeight": 0.1, "AmbientOcclusionRadiusInWS": True},
        },
        "probe_name": "el-ssao (head shot a under the wing and the intakes, 0.4 / 0.6 / 0.8 and off)",
    },
    # 4. Sun shadows. The scene builds the sun with 6 cascades over 20 km
    # (FlightSimVisualScene.cpp) and the no-lumen fallback packs 8 cascades
    # at exponent 4 over the same 20 km: at 1080p a cascade then spans
    # kilometres and the airframe's shadow on itself is mush ("plastic").
    # Here the cascades cover only the kilometres the camera resolves (the
    # Google tiles carry their own baked sun shading beyond), 4096-texel
    # maps, and PCSS (r.Shadow.FilterMethod 1) widens the penumbra with
    # distance from the caster from the sun's own LightSourceAngle (the
    # hero-lighting lane's 0.5357 deg disc, read back, never set here).
    # Distances in metres (the host multiplies by 100).
    "sun_shadows": {
        "switch": "sun-shadows", "probe": False, "stage": "scene",
        "off_means": ("the earlier lanes' sun shadows stand (the scene's 6 cascades over 20 km, or the "
                      "fallback's 8 at exponent 4), uniform PCF"),
        "cvars": {"r.Shadow.MaxResolution": 4096.0, "r.Shadow.MaxCSMResolution": 4096.0,
                  "r.Shadow.CSM.MaxCascades": 10.0, "r.Shadow.MaxSoftKernelSize": 40.0},
        "cvars_constrained": {"r.Shadow.MaxResolution": 4096.0, "r.Shadow.MaxCSMResolution": 4096.0,
                              "r.Shadow.CSM.MaxCascades": 10.0, "r.Shadow.MaxSoftKernelSize": 40.0},
        "per_preset": {
            "clear": {"DynamicShadowCascades": 8, "CascadeDistributionExponent": 3.5,
                      "DynamicShadowDistanceMovableLight_m": 6000.0,
                      "ShadowDistanceFadeoutFraction": 0.15, "CascadeTransitionFraction": 0.1,
                      "r.Shadow.FilterMethod": 1},
            "hazy": {"DynamicShadowCascades": 8, "CascadeDistributionExponent": 3.5,
                     "DynamicShadowDistanceMovableLight_m": 5000.0,
                     "ShadowDistanceFadeoutFraction": 0.15, "CascadeTransitionFraction": 0.1,
                     "r.Shadow.FilterMethod": 1},
            "overcast": {"DynamicShadowCascades": 6, "CascadeDistributionExponent": 3.0,
                         "DynamicShadowDistanceMovableLight_m": 4000.0,
                         "ShadowDistanceFadeoutFraction": 0.15, "CascadeTransitionFraction": 0.1,
                         "r.Shadow.FilterMethod": 0},
            "rain": {"DynamicShadowCascades": 6, "CascadeDistributionExponent": 3.0,
                     "DynamicShadowDistanceMovableLight_m": 3500.0,
                     "ShadowDistanceFadeoutFraction": 0.15, "CascadeTransitionFraction": 0.1,
                     "r.Shadow.FilterMethod": 0},
            "storm": {"DynamicShadowCascades": 6, "CascadeDistributionExponent": 3.0,
                      "DynamicShadowDistanceMovableLight_m": 3000.0,
                      "ShadowDistanceFadeoutFraction": 0.15, "CascadeTransitionFraction": 0.1,
                      "r.Shadow.FilterMethod": 0},
        },
        "probe_name": "el-csm (#01 fin shadow on the fuselage and the ridge shadow edge; PCF vs PCSS)",
    },
    # 5. Distance-field shadows: beyond the cascades, from static meshes with
    # a mesh distance field (DefaultEngine.ini r.GenerateMeshDistanceFields=
    # True since Phase 2, so measure renders already run with the fields
    # built; this row is beauty only, on the sun). Cesium tiles are runtime
    # meshes with no distance field, so these come from the aircraft alone.
    # A PROBE: an extra shadow pass, off on the constrained GPU by default.
    "df_shadows": {
        "switch": "df-shadows", "probe": True, "stage": "scene",
        "off_means": "bUseRayTracedDistanceFieldShadows false (shadows end at the cascades)",
        "cvars": {"r.DistanceFieldShadowing": 1.0},
        "cvars_constrained": {"r.DistanceFieldShadowing": 1.0},
        "per_preset": {
            "clear": {"bUseRayTracedDistanceFieldShadows": True, "DistanceFieldShadowDistance_m": 30000.0},
            "hazy": {"bUseRayTracedDistanceFieldShadows": True, "DistanceFieldShadowDistance_m": 30000.0},
            "overcast": {"bUseRayTracedDistanceFieldShadows": True, "DistanceFieldShadowDistance_m": 15000.0},
            "rain": {"bUseRayTracedDistanceFieldShadows": True, "DistanceFieldShadowDistance_m": 15000.0},
            "storm": {"bUseRayTracedDistanceFieldShadows": True, "DistanceFieldShadowDistance_m": 15000.0},
        },
        "probe_name": "el-dfs (#12 cockpit: the C172's shadow on the canyon floor beyond the cascades; frame time)",
    },
    # 6. Contact shadows on the sun, in SCREEN space (a fraction of the frame
    # per ray), replacing the hero-lighting lane's 150 cm world-space length
    # on beauty: the short rays ground pylons, intakes and the canopy frame
    # without a halo on the tiles. Smaller under a deck, where the sun is
    # wide and contact shadows read false.
    "contact_shadows": {
        "switch": "contact-shadows", "probe": False, "stage": "scene",
        "off_means": "the hero-lighting lane's 150 cm world-space contact shadows stand",
        "cvars": {"r.ContactShadows": 1.0},
        "cvars_constrained": {"r.ContactShadows": 1.0},
        "per_preset": {
            "clear": {"ContactShadowLength": 0.02, "ContactShadowLengthInWS": False,
                      "ContactShadowCastingIntensity": 1.0, "ContactShadowNonCastingIntensity": 0.0},
            "hazy": {"ContactShadowLength": 0.02, "ContactShadowLengthInWS": False,
                     "ContactShadowCastingIntensity": 1.0, "ContactShadowNonCastingIntensity": 0.0},
            "overcast": {"ContactShadowLength": 0.015, "ContactShadowLengthInWS": False,
                         "ContactShadowCastingIntensity": 1.0, "ContactShadowNonCastingIntensity": 0.0},
            "rain": {"ContactShadowLength": 0.015, "ContactShadowLengthInWS": False,
                     "ContactShadowCastingIntensity": 1.0, "ContactShadowNonCastingIntensity": 0.0},
            "storm": {"ContactShadowLength": 0.01, "ContactShadowLengthInWS": False,
                      "ContactShadowCastingIntensity": 1.0, "ContactShadowNonCastingIntensity": 0.0},
        },
        "probe_name": "el-contact (head shot a pylons and intakes at 0.02 / 0.05; no halo on the tiles)",
    },
    # 7. Local exposure, per preset. The HIGHLIGHT scale stays 1 on every
    # preset (round 2: below 1 it re-tones the sky band as the bank swings
    # the terrain through the bilateral grid's neighbourhood -- exposure
    # breathing by another name, Gate 6); the shadow side lifts the valley
    # and the belly, more under a deck where the frame is all shadow.
    "local_exposure": {
        "switch": "local-exposure", "probe": False, "stage": "capture",
        "off_means": "every scale 1 (the bilateral grid changes nothing)",
        "cvars": {}, "cvars_constrained": {},
        "per_preset": {
            "clear": {"LocalExposureHighlightContrastScale": 1.0, "LocalExposureShadowContrastScale": 0.75,
                      "LocalExposureDetailStrength": 1.1, "LocalExposureBlurredLuminanceBlend": 0.6,
                      "LocalExposureMiddleGreyBias": 0.0},
            "hazy": {"LocalExposureHighlightContrastScale": 1.0, "LocalExposureShadowContrastScale": 0.8,
                     "LocalExposureDetailStrength": 1.1, "LocalExposureBlurredLuminanceBlend": 0.6,
                     "LocalExposureMiddleGreyBias": 0.0},
            "overcast": {"LocalExposureHighlightContrastScale": 1.0, "LocalExposureShadowContrastScale": 0.8,
                         "LocalExposureDetailStrength": 1.0, "LocalExposureBlurredLuminanceBlend": 0.6,
                         "LocalExposureMiddleGreyBias": 0.0},
            "rain": {"LocalExposureHighlightContrastScale": 1.0, "LocalExposureShadowContrastScale": 0.85,
                     "LocalExposureDetailStrength": 1.0, "LocalExposureBlurredLuminanceBlend": 0.6,
                     "LocalExposureMiddleGreyBias": 0.0},
            "storm": {"LocalExposureHighlightContrastScale": 1.0, "LocalExposureShadowContrastScale": 0.85,
                      "LocalExposureDetailStrength": 1.0, "LocalExposureBlurredLuminanceBlend": 0.6,
                      "LocalExposureMiddleGreyBias": 0.0},
        },
        "probe_name": "el-local (#01 valley floor and snow in one frame; #09 belly; sky band held)",
    },
    # 8. Bloom: the standard sum-of-Gaussians, low. A real lens blooms a
    # little around the sun's glints and specular hits, not across the sky.
    "bloom": {
        "switch": "bloom", "probe": False, "stage": "capture",
        "off_means": "BloomIntensity 0 and the Bloom show flag off",
        "cvars": {}, "cvars_constrained": {},
        "per_preset": {
            "clear": {"BloomMethod": "BM_SOG", "BloomIntensity": 0.25, "BloomThreshold": -1.0, "BloomSizeScale": 4.0},
            "hazy": {"BloomMethod": "BM_SOG", "BloomIntensity": 0.3, "BloomThreshold": -1.0, "BloomSizeScale": 4.0},
            "overcast": {"BloomMethod": "BM_SOG", "BloomIntensity": 0.2, "BloomThreshold": -1.0, "BloomSizeScale": 4.0},
            "rain": {"BloomMethod": "BM_SOG", "BloomIntensity": 0.3, "BloomThreshold": -1.0, "BloomSizeScale": 4.0},
            "storm": {"BloomMethod": "BM_SOG", "BloomIntensity": 0.3, "BloomThreshold": -1.0, "BloomSizeScale": 4.0},
        },
        "probe_name": "el-bloom (#05 backlit glints at 0.2 / 0.4 and off)",
    },
    # 9. Convolution bloom: BM_FFT with the engine's default kernel
    # (/Engine/EngineMaterials/DefaultBloomKernel, loaded by the renderer when
    # BloomConvolutionTexture is null: SceneRendering.cpp). The intensity is
    # the bloom row's. A PROBE: two FFTs a frame, off on the constrained GPU
    # by default; -look-bloom-fft=on lands it on one scene first.
    "bloom_fft": {
        "switch": "bloom-fft", "probe": True, "stage": "capture",
        "off_means": "the bloom row's BM_SOG",
        "cvars": {}, "cvars_constrained": {},
        "per_preset": {
            "clear": {"BloomMethod": "BM_FFT", "BloomConvolutionSize": 1.0, "BloomConvolutionScatterDispersion": 1.0,
                      "BloomConvolutionPreFilterMin": 7.0, "BloomConvolutionPreFilterMax": 15000.0,
                      "BloomConvolutionPreFilterMult": 15.0, "BloomConvolutionBufferScale": 0.133},
            "hazy": {"BloomMethod": "BM_FFT", "BloomConvolutionSize": 1.0, "BloomConvolutionScatterDispersion": 1.2,
                     "BloomConvolutionPreFilterMin": 7.0, "BloomConvolutionPreFilterMax": 15000.0,
                     "BloomConvolutionPreFilterMult": 15.0, "BloomConvolutionBufferScale": 0.133},
            "overcast": {"BloomMethod": "BM_FFT", "BloomConvolutionSize": 1.0, "BloomConvolutionScatterDispersion": 1.0,
                         "BloomConvolutionPreFilterMin": 7.0, "BloomConvolutionPreFilterMax": 15000.0,
                         "BloomConvolutionPreFilterMult": 15.0, "BloomConvolutionBufferScale": 0.133},
            "rain": {"BloomMethod": "BM_FFT", "BloomConvolutionSize": 1.0, "BloomConvolutionScatterDispersion": 1.3,
                     "BloomConvolutionPreFilterMin": 7.0, "BloomConvolutionPreFilterMax": 15000.0,
                     "BloomConvolutionPreFilterMult": 15.0, "BloomConvolutionBufferScale": 0.133},
            "storm": {"BloomMethod": "BM_FFT", "BloomConvolutionSize": 1.0, "BloomConvolutionScatterDispersion": 1.3,
                      "BloomConvolutionPreFilterMin": 7.0, "BloomConvolutionPreFilterMax": 15000.0,
                      "BloomConvolutionPreFilterMult": 15.0, "BloomConvolutionBufferScale": 0.133},
        },
        "probe_name": "el-fft (#05 backlit: Gaussian vs FFT, and the frame time on the laptop)",
    },
    # 10. Lens flare: the image-based ghosts, low, with a high threshold, and
    # DRAWN ONLY when the sun is in or just outside the frame: the host
    # measures the angle between the camera axis and the sun on the first
    # frame (UpdatePerFrame) and keeps the flare when it is within the
    # frame's half-diagonal plus ``sun_in_frame_margin_deg``; otherwise the
    # intensity is 0 and the show flag off for the clip (decided once: no
    # flicker at the boundary). #05 (backlit) and a sun-in-frame still get
    # it; #04 (sun behind the camera) never does. The bokeh shape is the
    # engine's own (LensFlareBokehShape null: PostProcessLensFlares.cpp keeps
    # its analytic shape); a hexagonal iris texture is a later import.
    "lens_flare": {
        "switch": "lens-flare", "probe": False, "stage": "capture",
        "off_means": "LensFlareIntensity 0 and the LensFlares show flag off",
        "cvars": {"r.LensFlareQuality": 2.0}, "cvars_constrained": {"r.LensFlareQuality": 2.0},
        "per_preset": {
            "clear": {"LensFlareIntensity": 0.2, "LensFlareThreshold": 12.0, "LensFlareBokehSize": 3.0,
                      "sun_in_frame_margin_deg": 12.0},
            "hazy": {"LensFlareIntensity": 0.25, "LensFlareThreshold": 12.0, "LensFlareBokehSize": 3.0,
                     "sun_in_frame_margin_deg": 12.0},
            "overcast": {"LensFlareIntensity": 0.1, "LensFlareThreshold": 12.0, "LensFlareBokehSize": 3.0,
                         "sun_in_frame_margin_deg": 12.0},
            "rain": {"LensFlareIntensity": 0.15, "LensFlareThreshold": 12.0, "LensFlareBokehSize": 3.0,
                     "sun_in_frame_margin_deg": 12.0},
            "storm": {"LensFlareIntensity": 0.15, "LensFlareThreshold": 12.0, "LensFlareBokehSize": 3.0,
                      "sun_in_frame_margin_deg": 12.0},
        },
        "probe_name": "el-flare (#05 backlit on and off; #04 must show none)",
    },
    # 11. Film grain: the engine's grain texture (DefaultFilmGrainTexture,
    # loaded when FilmGrainTexture is null) at GRAIN_STRENGTH x grain_scale,
    # split by tone: a colour negative's grain shows in the midtones and
    # shadows, less in the clean highlights; it also hides the sky's 8-bit
    # banding. A dim or wet scene reads as a faster stock: more grain.
    "film_grain": {
        "switch": "film-grain", "probe": False, "stage": "capture",
        "off_means": "FilmGrainIntensity 0 and the Grain show flag off",
        "cvars": {"r.FilmGrain": 1.0}, "cvars_constrained": {"r.FilmGrain": 1.0},
        "per_preset": {
            "clear": {"grain_scale": 1.0, "FilmGrainIntensityShadows": 1.0, "FilmGrainIntensityMidtones": 1.0,
                      "FilmGrainIntensityHighlights": 0.7, "FilmGrainShadowsMax": 0.09,
                      "FilmGrainHighlightsMin": 0.5, "FilmGrainHighlightsMax": 1.0, "FilmGrainTexelSize": 1.0},
            "hazy": {"grain_scale": 1.1, "FilmGrainIntensityShadows": 1.0, "FilmGrainIntensityMidtones": 1.0,
                     "FilmGrainIntensityHighlights": 0.7, "FilmGrainShadowsMax": 0.09,
                     "FilmGrainHighlightsMin": 0.5, "FilmGrainHighlightsMax": 1.0, "FilmGrainTexelSize": 1.0},
            "overcast": {"grain_scale": 1.2, "FilmGrainIntensityShadows": 1.0, "FilmGrainIntensityMidtones": 1.0,
                         "FilmGrainIntensityHighlights": 0.7, "FilmGrainShadowsMax": 0.09,
                         "FilmGrainHighlightsMin": 0.5, "FilmGrainHighlightsMax": 1.0, "FilmGrainTexelSize": 1.0},
            "rain": {"grain_scale": 1.3, "FilmGrainIntensityShadows": 1.0, "FilmGrainIntensityMidtones": 1.0,
                     "FilmGrainIntensityHighlights": 0.7, "FilmGrainShadowsMax": 0.09,
                     "FilmGrainHighlightsMin": 0.5, "FilmGrainHighlightsMax": 1.0, "FilmGrainTexelSize": 1.1},
            "storm": {"grain_scale": 1.4, "FilmGrainIntensityShadows": 1.0, "FilmGrainIntensityMidtones": 1.0,
                      "FilmGrainIntensityHighlights": 0.7, "FilmGrainShadowsMax": 0.09,
                      "FilmGrainHighlightsMin": 0.5, "FilmGrainHighlightsMax": 1.0, "FilmGrainTexelSize": 1.2},
        },
        "probe_name": "el-grain (#01 and #09 at 1x and 2x GRAIN_STRENGTH, against a scanned negative)",
    },
    # 12. Volumetric fog: the droplet albedo per weather (sRGB 8-bit, the
    # component's FColor): water haze near white, dust and rain curtains a
    # little grey. The scattering distribution (g), the extinction scale and
    # the fog distance are the WORLD lane's per-row values
    # (core/scene/world_beauty.py, incl. the wet rows' extinction scaling and
    # its in-scatter compensation on the lights), and the sun's
    # VolumetricScatteringIntensity is the hero-lighting lane's: all read back
    # here, never set, so the one haze stays one haze.
    "volumetric_fog": {
        "switch": "volumetric-fog", "probe": False, "stage": "scene",
        "off_means": "VolumetricFogAlbedo white (the engine default every earlier round drew)",
        "cvars": {"r.VolumetricFog": 1.0}, "cvars_constrained": {"r.VolumetricFog": 1.0},
        "per_preset": {
            "clear": {"VolumetricFogAlbedo_srgb8": [235, 235, 235]},
            "hazy": {"VolumetricFogAlbedo_srgb8": [230, 228, 224]},
            "overcast": {"VolumetricFogAlbedo_srgb8": [240, 240, 240]},
            "rain": {"VolumetricFogAlbedo_srgb8": [232, 232, 234]},
            "storm": {"VolumetricFogAlbedo_srgb8": [225, 225, 228]},
        },
        "probe_name": "el-vfog (#06 rain haze and #05 dust at the albedo and at white)",
    },
    # 13. The volumetric fog grid. The fine grid (GridPixelSize 4, GridSizeZ
    # 128) is what the hero-lighting lane set and every passing round
    # rendered with on the laptop; the coarse grid is the engine's (8, 64).
    # A PROBE with ``auto`` = ON on both GPUs (no regression on the frames
    # that passed): its A/B is -look-fog-grid=off, the time the fine grid
    # costs. Costs are per fog voxel, not per cloud-march step.
    "fog_grid": {
        "switch": "fog-grid", "probe": True, "auto_on_constrained": True, "stage": "scene",
        "off_means": "the engine's coarse grid (r.VolumetricFog.GridPixelSize 8, GridSizeZ 64)",
        "cvars": {"r.VolumetricFog.GridPixelSize": 4.0, "r.VolumetricFog.GridSizeZ": 128.0},
        "cvars_constrained": {"r.VolumetricFog.GridPixelSize": 4.0, "r.VolumetricFog.GridSizeZ": 128.0},
        "cvars_off": {"r.VolumetricFog.GridPixelSize": 8.0, "r.VolumetricFog.GridSizeZ": 64.0},
        "per_preset": {p: {} for p in ("clear", "hazy", "overcast", "rain", "storm")},
        "probe_name": "el-fog-grid (#09 shaft banding fine vs coarse; frame time on the laptop)",
    },
    # 14. Stills: TSR with more warm-up and accumulation. A still's beauty
    # frame is the last of ``still_samples`` captures of one pose (the
    # render-path lane's RenderBeautyStillSamplesDefault 8) after
    # ``warmup_captures`` discarded ones (16): both raised here so TSR's
    # history (32 samples a pixel at 200 % of the output, the render-path
    # lane's cvars, read back) converges before the frame is kept. The
    # internal resolution is untouched (the constrained supersample cap
    # stands). Fewer on the constrained GPU: each capture is a drained frame.
    "tsr": {
        "switch": "tsr", "probe": False, "stage": "scene",
        "off_means": "the commandlet's own warm-up (16) and still samples (8)",
        "cvars": {}, "cvars_constrained": {},
        "per_preset": {p: {"warmup_captures": 24, "still_samples": 16}
                       for p in ("clear", "hazy", "overcast", "rain", "storm")},
        "per_preset_constrained": {"warmup_captures": 20, "still_samples": 12},
        "probe_name": "el-tsr (head shot a edge-aliasing number at 8 and 16 samples; seconds per still)",
    },
    # 15. The filmback: a full-frame 36 x 24 mm sensor. The width is what the
    # camera row already carries (it derives the focal length from the FOV);
    # the height is the 3:2 sensor's, of which a 16:9 frame uses 20.25 mm
    # (cropped top and bottom, the FOV unchanged). No anamorphic squeeze.
    "filmback": {
        "switch": "filmback", "probe": False, "stage": "capture",
        "off_means": "the camera row's sensor width alone (the pre-round-5 record)",
        "cvars": {}, "cvars_constrained": {},
        "per_preset": {p: {"sensor_width_mm": 36.0, "sensor_height_mm": 24.0, "DepthOfFieldSqueezeFactor": 1.0}
                       for p in ("clear", "hazy", "overcast", "rain", "storm")},
        "probe_name": "none: a record of the sensor, no pixel changes",
    },
}

#: switch word -> effect key, in table order.
ENGINE_LOOK_SWITCHES: Dict[str, str] = {row["switch"]: key for key, row in ENGINE_LOOK.items()}

# -- film stock (round 5, lane L2) --------------------------------------------------

#: The film LUTs' folder and index (scripts/make_film_luts.py writes both).
FILM_LUT_DIR = "assets/looks/film"
FILM_LUT_INDEX = "film_luts.json"
#: The stock per grade. A daylight colour negative, scanned, for the soft
#: low sun and the flat overcast; a slide for the hard clear noon; a
#: motion-picture print for the storm's muted palette. UNCALIBRATED: set
#: by probe render on the render machine (the round-5 A/B pairs, each
#: stock against the ungraded frame on #01 and #09).
FILM_STOCKS: Dict[str, str] = {
    "golden_hour": "kodak_portra_160",
    "desert_noon": "kodak_ektachrome_100d",
    "storm": "kodak_vision3_250d_2383",
    "overcast": "kodak_portra_160",
}
#: Whose grain the beauty frame carries. True: the engine's film grain
#: (LENSES FilmGrainIntensity, the look's L1 numbers) is the grain, and the
#: post-render pipeline (scripts/beauty_post.py) adds none on a look whose
#: FilmGrainIntensity is above 0. False: the engine's grain is for the
#: pipeline to add (seeded ffmpeg noise). One constant, read by both.
FILM_GRAIN_IN_ENGINE = True

_film_lut_index: Optional[Dict[str, Dict[str, Any]]] = None


def film_lut_index(repo: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """``{stock: entry}`` of assets/looks/film/film_luts.json (read once)."""
    global _film_lut_index
    if _film_lut_index is None or repo is not None:
        root = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]
        path = root / FILM_LUT_DIR / FILM_LUT_INDEX
        index = {entry["stock"]: entry for entry in
                 json.loads(path.read_text(encoding="utf-8")).get("luts", [])}
        if repo is not None:
            return index
        _film_lut_index = index
    return _film_lut_index


def film_stock_for(grade: Any) -> Dict[str, Any]:
    """The stock record for a grade: its name, the .cube's repo-relative
    path and sha256, where it is applied. An unknown grade or a stock
    without a LUT is refused (render.beauty_look)."""
    name = validate_grade(grade)
    stock = FILM_STOCKS[name]
    entry = film_lut_index().get(stock)
    if entry is None:
        raise BeautyLookError(CONSTRAINT, f"grade {name!r}: film stock {stock!r} has no LUT in "
                                          f"{FILM_LUT_DIR}/{FILM_LUT_INDEX}")
    return {
        "stock": stock,
        "cube": f"{FILM_LUT_DIR}/{entry['file']}",
        "sha256": entry["sha256"],
        "description": entry.get("description"),
        "space": "display-referred sRGB in and out, after the tonemapper",
        "applied_by": ("scripts/beauty_post.py (ffmpeg lut3d, tetrahedral) when "
                       "FLIGHTSIM_BEAUTY_POST=on; or in-engine via scripts/cube_to_ue_lut.py"),
        "grain_in_engine": FILM_GRAIN_IN_ENGINE,
    }


#: The constants a probe render must set, as the record lists them.
UNCALIBRATED: Tuple[str, ...] = (
    "EV100_BANDS", "GRADES", "GOLDEN_HOUR_BELOW_DEG", "LENSES", "LOCAL_EXPOSURE",
    "REFLECTIONS", "EXPOSURE_METER_TARGET_P90", "TONEMAP_HUE", "RELIT_SUN_CLOSE_SHARE",
    "ENGINE_LOOK", "GRAIN_STRENGTH", "ISO_GRAIN_CAP",
    "FILM_STOCKS", "SUBJECT_METER", "AO_RADIUS_WS_CM",
    "TONEMAP_CAMERA", "WHITE_BALANCE", "ILLUMINANT_MODEL", "CAMERA_RESPONSE",
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


def look_preset_for(world_preset: Optional[str], grade: str) -> Tuple[str, str]:
    """(engine-look preset, basis): the world preset when the card names one
    (:data:`ENGINE_LOOK_PRESETS`), else the grade's (:data:`GRADE_LOOK_PRESET`)."""
    word = str(world_preset) if world_preset is not None else ""
    if word in ENGINE_LOOK_PRESETS:
        return word, f"world preset {word} (core/scene/world_beauty.py select_preset)"
    fallback = GRADE_LOOK_PRESET[validate_grade(grade)]
    return fallback, f"no world preset: the {grade} grade's ({fallback})"


#: hl-sun (2026-11-15): ``-bloom-mode=sun|full``. UE's BloomThreshold -1
#: blooms every pixel by its share of BloomIntensity (a glow over the whole
#: frame, cloud tops and white paint included), which a real lens does not
#: show: its veiling glare is ~1-3 % (ISO 9358 veiling glare index of a coated
#: photographic lens) and is visible only around sources far above diffuse
#: white. ``sun`` (default) sets the threshold to BLOOM_SUN_THRESHOLD in
#: post-exposure luminance (PostProcessBloom.usf: Luminance x ExposureScale -
#: BloomThreshold, ramped over 2 units), 3.2 stops above a 0.8-albedo white at
#: mid grey 0.18 x 4.4 = 0.8; the solar disc (1.6e9 cd/m^2, Minnaert; ~7e4
#: after an EV15 exposure) and its water / metal glints (>= 2 % of the disc)
#: are 10+ stops over it, so the halo is the sun's, sized by the haze preset's
#: BloomIntensity / BloomSizeScale. Same number as the sun-shaft bloom
#: (core/scene/sun_shafts.py). ``full`` is the earlier -1.
BLOOM_MODES: Tuple[str, ...] = ("sun", "full")
DEFAULT_BLOOM_MODE = "sun"
BLOOM_MODE_SWITCH = "-bloom-mode="
BLOOM_SUN_THRESHOLD = 8.0
BLOOM_FULL_THRESHOLD = -1.0


def bloom_for(values: Dict[str, Any], mode: str = DEFAULT_BLOOM_MODE) -> Dict[str, Any]:
    """The bloom row with ``BloomThreshold`` for ``mode`` and both thresholds
    recorded so the host can take ``-bloom-mode=full`` without a recompile."""
    if mode not in BLOOM_MODES:
        raise BeautyLookError(CONSTRAINT, f"bloom mode {mode!r} is not one of {', '.join(BLOOM_MODES)}")
    row = dict(values)
    row["BloomThresholdFull"] = BLOOM_FULL_THRESHOLD
    row["BloomThresholdSun"] = BLOOM_SUN_THRESHOLD
    row["BloomThreshold"] = BLOOM_SUN_THRESHOLD if mode == "sun" else BLOOM_FULL_THRESHOLD
    row["bloom_mode"] = mode
    row["bloom_mode_switch"] = BLOOM_MODE_SWITCH + "|".join(BLOOM_MODES)
    return row


def film_grain_for(preset: str, stock_scale: float = 1.0, ev100: Optional[float] = None,
                   model: str = DEFAULT_GRAIN_MODEL) -> Dict[str, Any]:
    """The film-grain row for ``preset``. ``FilmGrainIntensityPreset`` is the
    round-5 number, :data:`GRAIN_STRENGTH` x the preset's ``grain_scale`` x
    ``stock_scale`` (L2's per-stock number; 1 for no stock). With ``ev100``
    (the exposure target) and ``model`` ``iso`` (hl-exposure, the default),
    ``FilmGrainIntensity`` is GRAIN_STRENGTH x :func:`iso_grain_factor` of
    :func:`equivalent_iso` x ``stock_scale``: 0 at and below ISO ~213, so a
    sunlit frame has none; the preset's ``grain_scale`` is then not used (the
    ISO owns the dimness). Without an EV100 it is the preset number. The
    host applies ``FilmGrainIntensityPreset`` under ``-grain-model=preset``."""
    if preset not in ENGINE_LOOK_PRESETS:
        raise BeautyLookError(CONSTRAINT, f"engine-look preset {preset!r} is not one of "
                                          f"{', '.join(ENGINE_LOOK_PRESETS)}")
    scale = float(stock_scale)
    if not math.isfinite(scale) or scale < 0.0:
        raise BeautyLookError(CONSTRAINT, f"a film stock's grain scale of {stock_scale!r} is not a "
                                          f"number of 0 or more")
    row = dict(ENGINE_LOOK["film_grain"]["per_preset"][preset])
    row["GrainStrength"] = GRAIN_STRENGTH
    row["stock_scale"] = scale
    preset_value = round(GRAIN_STRENGTH * float(row["grain_scale"]) * scale, 6)
    row["FilmGrainIntensity"] = preset_value
    if model not in GRAIN_MODELS:
        raise BeautyLookError(CONSTRAINT, f"grain model {model!r} is not one of {', '.join(GRAIN_MODELS)}")
    if model == "iso" and ev100 is not None:
        target = float(ev100)
        if not math.isfinite(target):
            raise BeautyLookError(CONSTRAINT, f"an exposure target of {ev100!r} has no ISO")
        iso = equivalent_iso(target)
        factor = iso_grain_factor(iso)
        row["FilmGrainIntensityPreset"] = preset_value
        row["FilmGrainIntensity"] = round(GRAIN_STRENGTH * factor * scale, 6)
        row["grain_model"] = "iso"
        row["equivalent_iso"] = round(iso, 1)
        row["iso_grain_factor"] = round(factor, 6)
    else:
        row["grain_model"] = "preset"
    return row


def engine_look_for(preset: str, stock_scale: float = 1.0,
                    ev100: Optional[float] = None) -> Dict[str, Any]:
    """The sidecar's ``engine_look`` block for one preset: per effect its
    switch, probe flag, ``off_means``, the values (``values``, and
    ``values_constrained`` where the constrained GPU takes different ones),
    the cvars (``cvars``, ``cvars_constrained``, ``cvars_off``) and the
    probe that sets them. The host chooses the constrained column itself
    (FFlightSimWorldBeauty::ConstrainedGpu) and records which it took."""
    if preset not in ENGINE_LOOK_PRESETS:
        raise BeautyLookError(CONSTRAINT, f"engine-look preset {preset!r} is not one of "
                                          f"{', '.join(ENGINE_LOOK_PRESETS)}")
    out: Dict[str, Any] = {"preset": preset, "switch_prefix": LOOK_SWITCH_PREFIX,
                           "switch_source": "the command line, then FLIGHTSIM_RENDER_SWITCHES"}
    for key, row in ENGINE_LOOK.items():
        values = (film_grain_for(preset, stock_scale, ev100) if key == "film_grain"
                  else dict(row["per_preset"][preset]))
        if key == "bloom":
            values = bloom_for(values)
        effect: Dict[str, Any] = {
            "switch": f"{LOOK_SWITCH_PREFIX}{row['switch']}",
            "switch_words": list(PROBE_SWITCH_WORDS if row["probe"] else EFFECT_SWITCH_WORDS),
            "probe": bool(row["probe"]),
            "stage": row["stage"],
            "off_means": row["off_means"],
            "values": values,
            "cvars": dict(row["cvars"]),
            "cvars_constrained": dict(row["cvars_constrained"]),
            "probe_name": row["probe_name"],
        }
        if row["probe"]:
            effect["auto"] = ("on on every GPU (the fine grid every passing round rendered with)"
                              if row.get("auto_on_constrained")
                              else "off on the constrained GPU, on elsewhere")
            effect["auto_on_constrained"] = bool(row.get("auto_on_constrained", False))
        if "per_preset_constrained" in row:
            effect["values_constrained"] = {**values, **row["per_preset_constrained"]}
        if "cvars_off" in row:
            effect["cvars_off"] = dict(row["cvars_off"])
        out[key] = effect
    return out


def parse_look_switches(text: Optional[str]) -> Dict[str, str]:
    """``{switch word: value}`` for every ``-look-<name>=<value>`` token in
    ``text`` (a command line or FLIGHTSIM_RENDER_SWITCHES), checked against
    the effect's words (:data:`EFFECT_SWITCH_WORDS`, or
    :data:`PROBE_SWITCH_WORDS` for a probe). An unknown name or a value the
    switch does not take raises BeautyLookError by name
    (:data:`LOOK_SWITCH_CONSTRAINT`), as the host refuses it. Unstated
    switches are left out (the host renders as planned)."""
    import re

    out: Dict[str, str] = {}
    for match in re.finditer(rf"(?:^|\s){re.escape(LOOK_SWITCH_PREFIX)}([A-Za-z0-9-]+)=(\S*)", text or ""):
        name, value = match.group(1), match.group(2)
        key = ENGINE_LOOK_SWITCHES.get(name)
        if key is None:
            raise BeautyLookError(LOOK_SWITCH_CONSTRAINT,
                                  f"{LOOK_SWITCH_CONSTRAINT}: {LOOK_SWITCH_PREFIX}{name}= is not a look switch; "
                                  f"the switches are {', '.join(ENGINE_LOOK_SWITCHES)}")
        words = PROBE_SWITCH_WORDS if ENGINE_LOOK[key]["probe"] else EFFECT_SWITCH_WORDS
        if value not in words:
            raise BeautyLookError(LOOK_SWITCH_CONSTRAINT,
                                  f"{LOOK_SWITCH_CONSTRAINT}: {LOOK_SWITCH_PREFIX}{name}={value} is not one of "
                                  f"{', '.join(words)}")
        out[name] = value
    return out


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
    from core.scene.world_beauty import card_wind_mps, is_storm_word, select_preset

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
    # hl-fixes (2026-11-16): ANY storm word, as the host's FlightSimClouds Build
    # and world_beauty.card_inputs read it. "== thunderstorm" made a tornado card
    # (#10, round 1410) a "clear" preset: under_deck False although its deck is
    # drawn, so the exposure took the clear-sky incident anchor (no frame meter,
    # no overcast fraction) and the frame rendered crushed (luma 0.018).
    storm = is_storm_word(str(weather.get("storm", ""))) or bool(weather_draws_cell)
    cover = 0.0
    layers = look.get("clouds")
    if isinstance(layers, list) and layers and isinstance(layers[0], Mapping):
        layer = layers[0]
        if num(layer, "top_m") > num(layer, "base_m"):
            cover = num(layer, "cover")
    visibility = num(look, "visibility_km")
    # Lane D: the card's wind (heavy rain in a strong wind is the storm look).
    wind = card_wind_mps(dict(card))
    inputs = {"storm": storm, "rain_rate_mmh": rain, "precipitation_rain": rain_word,
              "cloud_cover": cover, "visibility_km": visibility, "wind_mps": wind}
    return select_preset(storm, rain, rain_word, cover, visibility, wind), inputs


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


#: Visual round 2 (weather scenes, 2026-11-10): the rain rate from which the
#: commandlet draws a nimbostratus deck when the card states no layer
#: (FlightSimRenderCommandlet.cpp RainDeckMinMmh). Under it a ``rain`` world
#: has NO deck over the sun.
RAIN_DECK_MIN_MMH = 4.0


def deck_drawn_for_card(card: Optional[Mapping[str, Any]],
                        weather_draws_cell: bool = False) -> bool:
    """Whether the render draws a cloud deck over the sun for this card, read
    the way the commandlet builds the look's layers: a storm (the commandlet's
    storm deck, or the cell; a tornado keeps its storm exposure), a rain rate of
    :data:`RAIN_DECK_MIN_MMH` or more (its rain deck), or a stated layer of
    overcast cover (core/scene/world_beauty.py OVERCAST_COVER). Round 1's C172
    over Fuji at sunrise in 1 mm/h rain was exposed two stops open for a deck
    that light rain never draws, and rendered fully white."""
    from core.scene.world_beauty import OVERCAST_COVER

    preset, inputs = world_preset_for_card(card, weather_draws_cell)
    weather = card.get("weather_look") if isinstance(card, Mapping) else None
    word = str(weather.get("storm", "")) if isinstance(weather, Mapping) else ""
    if inputs["storm"] or preset == "storm" or word in STORM_EVENTS:
        return True
    if float(inputs["rain_rate_mmh"]) >= RAIN_DECK_MIN_MMH:
        return True
    return float(inputs["cloud_cover"]) >= OVERCAST_COVER


def scene_light(elevation_deg: float, altitude_m: float = 0.0, *,
                world_preset: Optional[str] = None,
                sun_intensity_scale: Optional[float] = None,
                sky_light_scale: Optional[float] = None,
                deck: Optional[bool] = None) -> Dict[str, Any]:
    """The light the scene actually gets, as a ratio of the clear-sky meter:
    under a cloud deck (:data:`DECK_PRESETS`) the overcast fraction of the
    clear sky (the direct beam is shadowed, so the lighting look's sun scale
    does not count again); otherwise the lighting look's sun scale on the
    direct beam plus its sky-fill scale on the diffuse. ``stops`` =
    log2(ratio), added to the band's EV100 (negative opens the exposure).
    ``deck``: whether the render really draws a deck (:func:`deck_drawn_for_card`);
    False keeps a deck preset (light rain) under the open sky it is drawn in;
    None reads the preset alone, as before."""
    from core.scene.hero_lighting import OVERCAST_ILLUMINANCE_FRACTION

    clear = clear_sky_horizontal_lux(elevation_deg, altitude_m)
    sun_scale = 1.0 if sun_intensity_scale is None else max(float(sun_intensity_scale), 0.0)
    sky_scale = 1.0 if sky_light_scale is None else max(float(sky_light_scale), 0.0)
    if clear <= 0.0:
        return {"ratio": 1.0, "stops": 0.0, "horizontal_lux": 0.0,
                "basis": "the sun is down: no clear-sky reference"}
    if under_deck(world_preset, deck):
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
        if world_preset in DECK_PRESETS:
            basis += f" (world preset {world_preset} with no deck drawn: the sun is not shadowed)"
    ratio = max(ratio, 1e-3)
    return {"ratio": round(ratio, 6), "stops": round(math.log2(ratio), 4),
            "horizontal_lux": round(clear * ratio, 1), "basis": basis}


def exposure_target(base_ev100: float, light: Mapping[str, Any], grade_offset: float,
                    brightness_ev: float) -> float:
    """THE beauty EV100, one formula for both bases: the base (the elevation
    band, or the -sky= plan's incident-meter EV100) moved by the scene's own
    light (:func:`scene_light`: the deck's overcast fraction, or the
    lighting look's sun and fill scales), the grade's offset, and the
    lighting look's brightness stops. Lower EV100 = more exposure: a dimmer
    scene opens by log2(ratio) stops."""
    return float(base_ev100) + float(light["stops"]) + float(grade_offset) - float(brightness_ev)


def under_deck(world_preset: Optional[str], deck: Optional[bool] = None) -> bool:
    """A deck preset whose deck is drawn (``deck`` None: the preset alone)."""
    return world_preset in DECK_PRESETS and (deck is None or bool(deck))


def exposure_meter(world_preset: Optional[str], deck_drawn: Optional[bool] = None) -> Dict[str, Any]:
    """The exposure meter's row (:data:`EXPOSURE_METER_TARGET_P90`): metered
    under a deck preset whose deck is drawn; otherwise only when the host finds
    no Lumen GI."""
    deck = under_deck(world_preset, deck_drawn)
    row: Dict[str, Any] = {
        "deck": deck,
        # hl-exposure: the no-Lumen meter under a clear sky (EXPOSURE_ANCHORS);
        # the host reads it and -exposure-anchor= overrides it.
        "clear_no_lumen_gi": DEFAULT_EXPOSURE_ANCHOR,
        "clear_no_lumen_gi_switch": EXPOSURE_ANCHOR_SWITCH + "incident|frame",
        "target_p90_luma": (EXPOSURE_METER_TARGET_P90[str(world_preset)] if deck
                            else EXPOSURE_METER_TARGET_P90["no_lumen_gi"]),
        "no_lumen_gi_target_p90_luma": EXPOSURE_METER_TARGET_P90["no_lumen_gi"],
        "when": ("always: a cloud deck's own darkness is measured, not guessed" if deck
                 else ("only when the host finds Lumen GI unsupported on its shader platform "
                       "AND -exposure-anchor=frame; by default (incident) a clear frame keeps "
                       "the incident meter's exposure")),
        "method": ("the beauty frame read back once before frame 0; the 90th percentile "
                   "of its sRGB luma opened to the target by AutoExposureBias, never "
                   "closed below this EV100 unless the frame clips (the host's highlight "
                   "guard, look_applied.storm_exposure.highlight_guard), constant over "
                   "the clip"),
    }
    return row


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


def pixel_effects(lens: Mapping[str, Any], width_px: int,
                  engine_look: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """What each beauty effect does to label agreement: ``moves`` (shifts
    pixels off the geometry the labels describe), ``softens`` (spreads
    edges, the centroid stays), ``none``. Masks, class, depth and boxes
    come from their own captures of the SAME frame, without these.
    ``engine_look`` (:func:`engine_look_for`) carries bloom, flare and
    grain since round 5; without it (a lens alone) they read as off."""
    blur_px = float(lens["MotionBlurMax"]) / 100.0 * int(width_px)

    def look_value(effect: str, key: str) -> float:
        if not engine_look:
            return 0.0
        return float(engine_look[effect]["values"][key])

    bloom = look_value("bloom", "BloomIntensity")
    flare = look_value("lens_flare", "LensFlareIntensity")
    grain = look_value("film_grain", "FilmGrainIntensity")
    effects = {
        "lens_distortion": {"on": False, "effect": "moves", "note": "not implemented"},
        "chromatic_aberration": {"on": float(lens["SceneFringeIntensity"]) > 0.0,
                                 "effect": "moves",
                                 "SceneFringeIntensity": float(lens["SceneFringeIntensity"])},
        "motion_blur": {"on": True, "effect": "softens",
                        "max_smear_px": round(blur_px, 2),
                        "stills": "off (SHUTTER_POLICY: the host turns it off on a still)",
                        "note": ("clips only: smears along screen velocity over one "
                                 "delivered frame, at most MotionBlurMax % of the width; "
                                 "the chase aircraft moves little on screen, the ground "
                                 "most; label captures render with motion blur off")},
        "depth_of_field": {"on": bool(lens["depth_of_field"]), "effect": "softens",
                           "note": "focused at the aircraft; the background softens"},
        "bloom": {"on": bloom > 0.0, "effect": "softens", "BloomIntensity": bloom,
                  "note": ("screen-space glow may lighten pixels just outside the mask; "
                           "ENGINE_LOOK bloom (per world preset; bloom_fft is a probe)")},
        "lens_flare": {"on": flare > 0.0, "effect": "none", "LensFlareIntensity": flare,
                       "note": ("image-based ghosts from bright pixels; no geometry; drawn only "
                                "with the sun in or just outside the frame (ENGINE_LOOK lens_flare)")},
        "vignette": {"on": float(lens["VignetteIntensity"]) > 0.0, "effect": "none"},
        "film_grain": {"on": grain > 0.0, "effect": "none", "FilmGrainIntensity": grain,
                       "note": "ENGINE_LOOK film_grain: GRAIN_STRENGTH x the preset's and the stock's scales"},
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
                     brightness_ev: Optional[float] = None,
                     camera_presets: Optional[Sequence[str]] = None,
                     sky_exposure: Optional[Mapping[str, Any]] = None,
                     unmetered_scales: Optional[Mapping[str, float]] = None,
                     deck_drawn: Optional[bool] = None,
                     stock_grain_scale: float = 1.0) -> Dict[str, Any]:
    """The complete ``beauty_look.json``. Pure: same inputs, same bytes.

    ``stock_grain_scale``: the film stock's grain scale (L2), applied to
    :data:`GRAIN_STRENGTH` through :func:`film_grain_for`; 1 for none.

    ``sensor_width_mm``: one per camera pass, in the card's camera order
    (the host picks by ``-camera-index=``). ``physical_sky``: the -sky= plan
    lights and exposes the scene, so the sun and exposure rows are left to
    it (stated, not silently dropped). ``world_preset``: the world lane's
    preset for the card (:func:`world_preset_for_card`); it chooses the
    grade and whether a deck shadows the beam. ``sun_intensity_scale``,
    ``sky_light_scale``, ``brightness_ev``: the lighting look's (webapp
    render_look_for), which the host applies to the light and which the
    exposure therefore meters (:func:`scene_light`) and adds.
    ``camera_presets``: one per camera, in the same order as the sensor
    widths; a camera inside the aircraft (:data:`INSIDE_PRESETS`) gets no
    depth of field (the host reads ``camera.focus_per_camera``).
    ``sky_exposure``: the -sky= plan's ``exposure`` block (core/sky/plan.py).
    With it, the beauty look OWNS the exposure on the physical-sky path too:
    the plan's incident-meter EV100 is the base, moved by the same deck and
    lighting stops as the band (:func:`exposure_target`), realised through
    the plan's own camera (the host changes only the compensation). Without
    it (no plan EV100 to start from) the plan's exposure stands, as before.
    ``unmetered_scales``: the lighting look's scales the host applies but the
    exposure deliberately does NOT meter (a user's or a preset's stated
    look, webapp.runs write_beauty_look_plan; round 2b). Recorded in the
    exposure row as ``lighting_scales_unmetered``; they move no number here.
    ``deck_drawn``: whether the render draws a deck over the sun
    (:func:`deck_drawn_for_card`); False keeps a deck preset with no deck
    drawn (light rain) exposed for the open sky it is lit by; None reads the
    preset alone (visual round 2)."""
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
    presets = [str(p or "chase") for p in (camera_presets or ["chase"] * len(sensors))]
    if len(presets) != len(sensors):
        raise BeautyLookError(CONSTRAINT, f"{len(presets)} camera presets for {len(sensors)} "
                                          f"sensor widths: one of each per camera")
    brightness = 0.0 if brightness_ev is None else float(brightness_ev)
    if not math.isfinite(brightness):
        raise BeautyLookError(CONSTRAINT, f"brightness_ev {brightness_ev!r} is not a number of stops")
    lens_row = LENSES[lens_name]
    grade_row = GRADES[grade_name]
    shutter = shutter_seconds(fps)
    aperture = float(lens_row["aperture_f"])
    cam_ev = camera_ev100(aperture, shutter)

    light = scene_light(elevation, altitude_m, world_preset=world_preset,
                        sun_intensity_scale=sun_intensity_scale,
                        sky_light_scale=sky_light_scale, deck=deck_drawn)
    horizontal = clear_sky_horizontal_lux(elevation, altitude_m)
    grade_offset = float(grade_row["ev100_offset"])
    if physical_sky:
        sun = {"lux": None, "source": "physical_sky",
               "transmittance": SUN_TRANSMITTANCE_OWNER,
               "basis": "the -sky= plan lights the scene (core/sky/plan.py)"}
        sky_ev, sky_camera = _sky_plan_exposure(sky_exposure)
        if sky_ev is None:
            exposure: Dict[str, Any] = {
                "ev100": None,
                "basis": ("the -sky= plan's EV100 (core/sky/plan.py) stands: no plan EV100 "
                          "was handed to the beauty look")}
        else:
            # ONE owner: the plan meters a CLEAR sky; the deck (and the
            # lighting look's scales) move it exactly as they move the band.
            # The plan's camera is kept (its f-number is part of the EV100);
            # only the compensation changes.
            sky_aperture, sky_shutter, sky_iso = sky_camera
            relit_open = relit_sun_open_stops(sky_exposure)
            target = exposure_target(sky_ev - relit_open, light, grade_offset, brightness)
            exposure = _exposure_row(
                target, base="sky_plan", base_ev100=sky_ev,
                base_basis=("the -sky= plan's incident-meter EV100 for a clear sky "
                            "(core/sky/plan.py ev100_for)"),
                light=light, grade_offset=grade_offset, brightness=brightness,
                world_preset=world_preset, aperture=sky_aperture, shutter=sky_shutter,
                iso=sky_iso, cam_ev=camera_ev100(sky_aperture, sky_shutter, sky_iso),
                horizontal=horizontal)
            exposure["over_sky_plan"] = True
            if relit_open > 0.0:
                exposure["relit_sun_open_stops"] = round(relit_open, 4)
                exposure["relit_sun_basis"] = (
                    f"the lighting block relit the sun: the plan's meter moved from EV100 "
                    f"{float(sky_exposure['relit_from_ev100']):g} to {sky_ev:g}; the exposure "
                    f"closes by RELIT_SUN_CLOSE_SHARE ({RELIT_SUN_CLOSE_SHARE:g}) of that gain "
                    f"(round 3, UNCALIBRATED)")
            exposure["camera_basis"] = ("the -sky= plan's physical camera, kept: the host "
                                        "changes only AutoExposureBias")
    else:
        sun = sun_lux_for(elevation, altitude_m, stated_sun_lux)
        band_ev, band_basis = ev100_band(elevation)
        target = exposure_target(band_ev, light, grade_offset, brightness)
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
        exposure = _exposure_row(
            target, base="band", base_ev100=band_ev, base_basis=band_basis, light=light,
            grade_offset=grade_offset, brightness=brightness, world_preset=world_preset,
            aperture=aperture, shutter=shutter, iso=CAMERA_ISO, cam_ev=cam_ev,
            horizontal=horizontal)
    if exposure.get("ev100") is not None:
        exposure["meter"] = exposure_meter(world_preset, deck_drawn)
    if unmetered_scales:
        exposure["lighting_scales_unmetered"] = {
            **{str(k): float(v) for k, v in sorted(unmetered_scales.items())},
            "basis": ("stated by the user or a lighting preset: applied to the light and "
                      "left unmetered, so the frame shows the look asked for (round 2b)")}

    post = {key: value for key, value in lens_row.items()
            if key[0].isupper()}
    white_balance = white_balance_for(elevation, grade_name, world_preset, deck_drawn, altitude_m)
    look_preset, look_preset_basis = look_preset_for(world_preset, grade_name)
    engine_look = engine_look_for(look_preset, stock_grain_scale, exposure.get("ev100"))
    engine_look["preset_basis"] = look_preset_basis
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
        "tonemap": {"tonemapper": ("UE filmic (ACES-fitted), engine 5.7 curve defaults "
                                   "stated; the camera's shoulder over them (TONEMAP_CAMERA); "
                                   "BlueCorrection raised (TONEMAP_HUE)"),
                    **TONEMAP, **TONEMAP_CAMERA, **TONEMAP_HUE},
        # hyperreal-grade: the grade's colour rows, the white point the white
        # balance owner's (white_balance_for), never the grade's own.
        "color_grade": {**{key: grade_row[key] for key in GRADE_KEYS},
                        "WhiteTemp": white_balance["WhiteTemp"], "WhiteTint": white_balance["WhiteTint"]},
        "white_balance": white_balance,
        # The post pipeline's camera response (scripts/beauty_post.py step
        # camera); the host reads no such key.
        "camera_response": camera_response_for(),
        # Round 5 (L2): the film LUT the post-render pipeline applies after
        # the tonemapper; the host reads no such key.
        "film_stock": film_stock_for(grade_name),
        "camera": {
            "aperture_f": aperture,
            "depth_of_field": bool(lens_row["depth_of_field"]),
            "focus": ("per frame: |capture - aircraft actor| (the poses the manifest "
                      "records)") if lens_row["depth_of_field"] else "off (focal distance 0)",
            # Per camera (the -camera-index= order): "subject" focuses on the
            # aircraft each frame; "off" is a camera inside it (no DOF).
            "focus_per_camera": [
                ("off" if p in INSIDE_PRESETS else "subject") if lens_row["depth_of_field"]
                else "off" for p in presets],
            "camera_presets": presets,
            "sensor_width_mm": sensors,
            "fov": "the pose solver's, unchanged; focal length derived from it",
            "shutter_angle_deg": SHUTTER_ANGLE_DEG,
            "MotionBlurAmount": SHUTTER_ANGLE_DEG / 360.0,
            "MotionBlurTargetFPS": int(round(float(fps))),
            "fps": float(fps),
            "shutter_policy": dict(SHUTTER_POLICY),
        },
        "lens_post": post,
        # Round 5: per world preset (ENGINE_LOOK local_exposure); the host
        # applies this row and the engine_look row names the switch.
        "local_exposure": {"LocalExposureMethod": "Bilateral",
                           **engine_look["local_exposure"]["values"]},
        "reflections": dict(REFLECTIONS),
        "engine_look": engine_look,
        "pixel_effects": pixel_effects(lens_row, width_px, engine_look),
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


def relit_sun_open_stops(block: Optional[Mapping[str, Any]]) -> float:
    """The stops a relit sun's exposure opens back (round 3): the share
    1 - :data:`RELIT_SUN_CLOSE_SHARE` of the meter gain the relight added
    (core.sky.plan.relight records the instant's own EV100 as
    ``relit_from_ev100``). 0 for a plan the lighting block did not relight,
    and for a relight to a lower sun (the meter opens for it in full)."""
    if not block or block.get("relit_from_ev100") is None:
        return 0.0
    try:
        gain = float(block["ev100"]) - float(block["relit_from_ev100"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BeautyLookError(CONSTRAINT, f"the -sky= plan's relit exposure is unreadable "
                                          f"({exc!r})") from exc
    if not math.isfinite(gain) or gain <= 0.0:
        return 0.0
    return gain * (1.0 - RELIT_SUN_CLOSE_SHARE)


def _sky_plan_exposure(block: Optional[Mapping[str, Any]]
                       ) -> Tuple[Optional[float], Tuple[float, float, float]]:
    """(EV100, (f-number, shutter s, ISO)) from a -sky= plan's ``exposure``
    block, or (None, ...) when there is none; a block that is there but
    unreadable refuses by name rather than quietly keeping the plan's."""
    if not block:
        return None, (0.0, 0.0, 0.0)
    try:
        ev = float(block["ev100"])
        cam = block["camera"]
        aperture, per_s, iso = float(cam["fstop"]), float(cam["shutter_per_s"]), float(cam["iso"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BeautyLookError(CONSTRAINT, f"the -sky= plan's exposure block is unreadable "
                                          f"({exc!r}); it needs ev100 and camera "
                                          f"{{fstop, shutter_per_s, iso}}") from exc
    if (not all(math.isfinite(v) for v in (ev, aperture, per_s, iso))
            or min(aperture, per_s, iso) <= 0.0):
        raise BeautyLookError(CONSTRAINT, f"the -sky= plan's exposure (EV100 {ev!r}, f/{aperture!r}, "
                                          f"1/{per_s!r} s, ISO {iso!r}) is not a physical camera")
    return ev, (aperture, 1.0 / per_s, iso)


def _exposure_row(target: float, *, base: str, base_ev100: float, base_basis: str,
                  light: Mapping[str, Any], grade_offset: float, brightness: float,
                  world_preset: Optional[str], aperture: float, shutter: float, iso: float,
                  cam_ev: float, horizontal: float) -> Dict[str, Any]:
    """The sidecar's exposure block: the same keys on both bases."""
    return {
        "ev100": round(target, 4),
        "owner": "beauty_look (core/scene/beauty_look.py exposure_target)",
        "base": base,
        "base_ev100": base_ev100,
        # The first name of the base, kept for records written before round 2.
        "band_ev100": base_ev100 if base == "band" else None,
        "grade_ev100_offset": grade_offset,
        "scene_light_stops": light["stops"],
        "scene_light_basis": light["basis"],
        "brightness_ev": brightness,
        "world_preset": world_preset,
        "basis": base_basis,
        "method": "manual (physical camera + compensation), constant over the clip",
        "aperture_f": aperture,
        "shutter_s": round(shutter, 8),
        "shutter_angle_deg": SHUTTER_ANGLE_DEG,
        "iso": iso,
        "camera_ev100": round(cam_ev, 4),
        "AutoExposureBias": round(cam_ev - target, 4),
        "meter_ev100_reference": (round(meter_ev100(horizontal), 3)
                                  if horizontal > 0.0 else None),
        # The CLEAR-sky reference (hero_lighting reads it and applies its
        # own overcast fraction); the scene's own light is the next key.
        "meter_horizontal_lux_reference": round(horizontal, 1),
        "meter_horizontal_lux_scene": light["horizontal_lux"],
    }


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
