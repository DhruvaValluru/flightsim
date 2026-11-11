"""The world's beauty look: atmosphere depth, cloud shapes, the tiles' grade and
wet response, the lightning's sky pulse, and the ground scatter's placement law.

Visual overhaul, world lane (2026-11-09). Everything here is BEAUTY ONLY:
``-quality=measure`` (every render Gate 6 passed on) never reaches it; the
render commandlet calls ``FFlightSimWorldBeauty::Build`` only under
``-quality=beauty`` (FlightSimClouds.cpp). Nothing here reaches an equation of
motion.

This module is the Python twin of the pure block in
``ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp``
(between ``FLIGHTSIM-WORLD-PURE-BEGIN`` and ``FLIGHTSIM-WORLD-PURE-END``) and of
the placement law in ``FlightSimGroundDetail.cpp`` (its own pure block).
``tests/test_world_beauty.py`` compiles those blocks with the machine's C++
compiler and checks them against this file, number for number, so the two
cannot drift.

EVERY look value below is UNCALIBRATED: set by probe render on the render
machine. They were chosen on a Mac that cannot compile or render the bridge
(Xcode above UE 5.7's cap, no Cesium), from the literature's orders of
magnitude and the engine's own defaults, never from a frame. The probe that
should set each one is named in ``docs/visual/PROBE_LOG.md`` (## world). The
render records the row it used (``look_applied.world_beauty``), so a frame is
always traceable to its numbers, and ``-world-beauty-overrides=<json>``
replaces any of them at run time for a probe sweep without a rebuild
(``validate_overrides`` is the schema).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import tiles_delight
from .rain_field import MASK64, splitmix64, unit
from .weather_look import STORMS

# -- the atmosphere presets -------------------------------------------------------

#: The look presets, in the C++ enum's order (EFlightSimWorldPreset).
PRESETS: Tuple[str, ...] = ("clear", "hazy", "overcast", "rain", "storm")

#: Selection thresholds (select_preset). UNCALIBRATED: set by probe render on
#: the render machine.
HAZY_VISIBILITY_KM = 15.0
OVERCAST_COVER = 0.75

#: Koschmieder's contrast threshold: beta = 3.912 / V (Middleton 1952).
KOSCHMIEDER = 3.912
#: The engine's default Rayleigh extinction at its green channel (1/km,
#: SkyAtmosphereComponent.cpp: 0.013558), the part of the Koschmieder beta the
#: atmosphere already carries before any aerosol is added.
RAYLEIGH_GREEN_PER_KM = 0.013558
#: The engine's default Mie single-scattering albedo: 0.003996 / (0.003996 +
#: 0.000444) = 0.9 (SkyAtmosphereComponent.cpp). Kept, so only the amount of
#: aerosol changes, not its kind.
MIE_SINGLE_SCATTER_ALBEDO = 0.9
#: The shortest visibility the split is evaluated at (km); a fog bank below it
#: stays the height fog's.
MIN_VISIBILITY_KM = 0.05

#: Field order of one atmosphere row: the C++ FFlightSimAtmosphereRow's order.
ATMOSPHERE_FIELDS: Tuple[str, ...] = (
    "mie_scale_height_km",          # SetMieExponentialDistribution (engine default 1.2)
    "mie_anisotropy",               # SetMieAnisotropy (engine default 0.8)
    "mie_share",                    # share of the haze extinction moved from fog to Mie
    "mie_cap_per_km",               # the Mie extinction never exceeds this (1/km)
    "aerial_perspective_scale",     # SetAerialPespectiveViewDistanceScale (engine 1.0)
    "vfog_distance_m",              # SetVolumetricFogDistance
    "vfog_scattering_distribution", # SetVolumetricFogScatteringDistribution (g)
    "vfog_extinction_scale",        # SetVolumetricFogExtinctionScale
    "cloud_bottom_occlusion",       # SetSkyLightCloudBottomOcclusion
    "rain_readability_gain",        # x the weather rain's weight (beauty only)
    "wetness_floor",                # the tiles' wetness at least this under the preset
    "tiles_detail_strength",        # near-field detail normal strength
    "lightning_sky_gain",           # sky light x (1 + gain x flash) at a flash
)

#: Visual round 3 (round 2's #07, a tower view of an A320 at 1000 m in 10 mm/h
#: rain: a flat grey frame, the airframe ~30 px at 1.2-1.5 km and within a few
#: levels of the grey around it). The rain look's haze is FogDensity 0.012
#: (lighting.RAIN_ANCHORS, 5x the default). The scene's analytic fog draws it as
#: beta = FogDensity x 0.1 ln(2)^2 per metre (the law weather_visuals and the
#: tiles' fog depth use) and starts 1500 m out; the beauty's volumetric fog
#: (on inside vfog_distance_m, from the camera) draws FogDensity / 1000 per cm,
#: 0.1 x FogDensity per metre [engine convention, unverified here]: about twice
#: the analytic beta, over the whole subject range. At 0.0012 /m the airframe
#: kept exp(-1.8) = 17 % of its contrast. The wet rows scale the volumetric
#: fog's extinction by ln(2)^2, so it draws the analytic beta: one haze, no seam
#: at the hand-off, and the subject at 1.5 km keeps ~42 %. Rain and storm only
#: (their haze is 3-10x a clear day's). UNCALIBRATED: set by probe render.
#: Round 4 (round 3's #08 and head shot c went much darker: the C172 a near-black
#: silhouette, the forest near black): the engine's volumetric fog scatters
#: Albedo x Extinction, so the 0.48 cut the rain haze's IN-SCATTER with its
#: extinction: the veil that lifted the dark near slope, forest and airframe
#: (optically thin there, in-scatter ~ sigma x distance) fell to 48 %. The
#: albedo is already white (an 8-bit colour: no headroom), so the in-scatter is
#: put back on the lights instead (:func:`vfog_scattering_compensation`): the
#: sun's and the sky light's VolumetricScatteringIntensity x 1 / 0.48. Only the
#: extinction is scaled: the near veil is round 2's again, and #07's airframe
#: still keeps ~42 % of its own light through the 1.5 km of rain (not 17 %).
#: Stated, not hidden: the saturated airlight (beyond ~3 km) is then 1 / 0.48
#: of a conserving fog's, which the beauty meter normalises away, so against it
#: the 1.5 km airframe's contrast is ~0.42 / 2.08 = 0.2 of its clear-air
#: contrast (round 2: 0.17, round 3: 0.47). What makes #07 read is the 250 mm
#: lens (scripts/run_test_scenarios.py), 7x the pixels, not the haze.
WET_VFOG_EXTINCTION_SCALE = 0.48

#: UNCALIBRATED: set by probe render on the render machine (every number).
#: Fix pass (2026-11-09): the rows no longer carry the planet's ground albedo
#: (one law of the card's surface and wetness: ground_albedo_srgb) nor the
#: tiles' dehaze and saturation (properties of the tileset's imagery, not of
#: the weather: TILES_DEHAZE, TILES_SATURATION; the frame-wide weather grade is
#: beauty_look's alone). The hazy look is a larger Mie share, not an aerial
#: perspective scale (which multiplied only the opaque surfaces' haze, so the
#: Koschmieder beta stopped being the one total). The detail normal is a
#: 4-6 degree micro relief (0.12), not a 23 degree one.
ATMOSPHERE: Dict[str, Dict[str, float]] = {
    "clear": dict(mie_scale_height_km=1.2, mie_anisotropy=0.80, mie_share=0.6, mie_cap_per_km=0.25,
                  aerial_perspective_scale=1.0, vfog_distance_m=8000.0, vfog_scattering_distribution=0.75,
                  vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.5, rain_readability_gain=1.0,
                  wetness_floor=0.0, tiles_detail_strength=0.12, lightning_sky_gain=0.0),
    "hazy": dict(mie_scale_height_km=1.6, mie_anisotropy=0.76, mie_share=0.7, mie_cap_per_km=0.6,
                 aerial_perspective_scale=1.0, vfog_distance_m=8000.0, vfog_scattering_distribution=0.7,
                 vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.5, rain_readability_gain=1.0,
                 wetness_floor=0.0, tiles_detail_strength=0.12, lightning_sky_gain=0.0),
    "overcast": dict(mie_scale_height_km=1.4, mie_anisotropy=0.70, mie_share=0.4, mie_cap_per_km=0.6,
                     aerial_perspective_scale=1.0, vfog_distance_m=6000.0, vfog_scattering_distribution=0.4,
                     vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.75, rain_readability_gain=1.0,
                     wetness_floor=0.0, tiles_detail_strength=0.12, lightning_sky_gain=0.0),
    "rain": dict(mie_scale_height_km=1.0, mie_anisotropy=0.65, mie_share=0.3, mie_cap_per_km=0.8,
                 aerial_perspective_scale=1.0, vfog_distance_m=4000.0, vfog_scattering_distribution=0.3,
                 vfog_extinction_scale=WET_VFOG_EXTINCTION_SCALE, cloud_bottom_occlusion=0.85, rain_readability_gain=1.5,
                 wetness_floor=0.6, tiles_detail_strength=0.12, lightning_sky_gain=0.0),
    "storm": dict(mie_scale_height_km=1.8, mie_anisotropy=0.65, mie_share=0.3, mie_cap_per_km=0.8,
                  aerial_perspective_scale=1.0, vfog_distance_m=4000.0, vfog_scattering_distribution=0.3,
                  vfog_extinction_scale=WET_VFOG_EXTINCTION_SCALE, cloud_bottom_occlusion=0.9, rain_readability_gain=1.5,
                  wetness_floor=0.85, tiles_detail_strength=0.12, lightning_sky_gain=3.0),
}


#: The storm words: ONE list, core/scene/weather_look.STORMS (the grade's
#: beauty_look.STORM_EVENTS is the same tuple; the C++ pure block's StormWord
#: table is pinned to it by tests/test_world_beauty.py). A tornado is a storm
#: for the world look exactly as it is for the grade.
STORM_WORDS: Tuple[str, ...] = tuple(STORMS)


def is_storm_word(word: Optional[str]) -> bool:
    """True when ``weather_look.storm`` names a storm (any of STORM_WORDS)."""
    return word in STORM_WORDS


#: Visual round 6 (2026-11-10): the deck SHADOWS the beam. Round 4's #10 ("c172
#: near a tornado over the Flint Hills") drew the prairie red (ground R/G 2.2
#: under a neutral grey sky, measured on the JPEG) with black creek valleys: the
#: web app's STORM_LOOK puts a storm's sun at 10 deg elevation, the engine's
#: per-pixel transmittance reddens that grazing beam, and the beauty's
#: nimbostratus deck did NOT shadow it -- the sun's cloud-shadow switch was
#: "left as the scene set it" (off), while beauty_look.scene_light metered the
#: frame as if "a cloud deck shadows the beam". The light under an overcast is
#: the deck's diffuse transmission, neutral grey; the beam does not reach the
#: ground. So in beauty, under a deck preset whose drawn layer covers at least
#: DECK_SHADOW_MIN_COVER, the sun casts the volumetric cloud's shadow
#: (UDirectionalLightComponent::bCastCloudShadows, the switch the stated fair
#: layer already turns on): the deck shadows the tiles, the fog and the
#: aircraft; its holes (cover < 1) still let beams through. Cost: the engine's
#: cloud shadow map (one low-resolution march per capture, not the per-pixel
#: view march). ``-deck-shadow=off`` (the command line or
#: FLIGHTSIM_RENDER_SWITCHES) keeps the scene's switch for an A/B; recorded in
#: world_beauty.clouds.deck_shadow. UNCALIBRATED: probe #10 first.
DECK_SHADOW_PRESETS: Tuple[str, ...] = ("storm", "rain", "overcast")
DECK_SHADOW_MIN_COVER = 0.5


def deck_shadows_beam(preset: str, layer_covers: Sequence[float]) -> bool:
    """Whether the beauty turns the sun's cloud shadows on: a deck preset with a
    drawn layer of cover >= DECK_SHADOW_MIN_COVER."""
    return preset in DECK_SHADOW_PRESETS and any(
        float(cover) >= DECK_SHADOW_MIN_COVER for cover in layer_covers)


def select_preset(storm: bool, rain_rate_mmh: float, precipitation_rain: bool,
                  cloud_cover: float, visibility_km: float) -> str:
    """The look preset for a card: a drawn or stated storm (is_storm_word) is ``storm``;
    any stated rain rate or a ``rain`` word is ``rain``; a deck of
    OVERCAST_COVER or more is ``overcast``; air under HAZY_VISIBILITY_KM is
    ``hazy``; anything else is ``clear``. A visibility of 0 or less means
    "not stated" and never selects ``hazy``."""
    if storm:
        return "storm"
    if rain_rate_mmh > 0.0 or precipitation_rain:
        return "rain"
    if cloud_cover >= OVERCAST_COVER:
        return "overcast"
    if 0.0 < visibility_km < HAZY_VISIBILITY_KM:
        return "hazy"
    return "clear"


def _look_value(card: Dict[str, Any], key: str, kinds: Tuple[type, ...]) -> Any:
    """One look key, read key by key: the card's W3 ``look`` block when it
    carries the key as a value of ``kinds`` (its ``precipitation`` is an
    object there, never the word), else ``randomization.look``."""
    for look in ((card.get("look") or {}), ((card.get("randomization") or {}).get("look") or {})):
        if isinstance(look, dict) and key in look:
            value = look[key]
            if isinstance(value, kinds) and not isinstance(value, bool):
                return value
    return None


def card_inputs(card: Dict[str, Any]) -> Dict[str, Any]:
    """What FFlightSimWorldBeauty::Build reads from a card (the Python twin of
    its look block): per key, card.look when it states the key as a value,
    else card.randomization.look, so a W3 look block (night, precipitation
    object, cloud drift) never hides the sampled haze, cloud layer or wetness.
    ``storm`` is the card's word only (the host also counts a drawn storm cell)."""
    weather_look = card.get("weather_look") or {}
    visibility = _look_value(card, "visibility_km", (int, float))
    rate = _look_value(card, "precipitation_rate_mmh", (int, float))
    word = _look_value(card, "precipitation", (str,))
    wetness = _look_value(card, "wetness", (int, float))
    clouds = _look_value(card, "clouds", (list,))
    cover = base = top = None
    if clouds and isinstance(clouds[0], dict):
        layer = clouds[0]
        if float(layer.get("top_m", 0.0)) > float(layer.get("base_m", 0.0)):
            cover = float(layer.get("cover", 0.0))
            base, top = float(layer["base_m"]), float(layer["top_m"])
    return {
        "visibility_km": float(visibility) if visibility is not None else 0.0,
        "rain_rate_mmh": max(float(rate or 0.0), float(weather_look.get("rain_rate_mmh") or 0.0)),
        "precipitation_rain": word == "rain",
        "storm": is_storm_word(weather_look.get("storm")),
        "card_cover": cover,
        "base_m": base,
        "top_m": top,
        "wetness": max(float(wetness or 0.0), float(weather_look.get("wetness") or 0.0)),
        "seed": int(weather_look.get("seed", card.get("seed", 0)) or 0),
        "surface": weather_look.get("surface"),
    }


def card_preset(card: Dict[str, Any], draws_cell: bool = False) -> str:
    """select_preset on card_inputs (the host's own call)."""
    i = card_inputs(card)
    return select_preset(i["storm"] or draws_cell, i["rain_rate_mmh"], i["precipitation_rain"],
                         i["card_cover"] or 0.0, i["visibility_km"])


def mie_split(visibility_km: float, share: float, cap_per_km: float) -> Dict[str, float]:
    """Move ``share`` of the air's haze from the height fog into the sky
    atmosphere's Mie layer, so distance turns hazy through the atmosphere's
    own scattering (the sun's forward glow, the bluing of far ridges) instead
    of a flat fog colour.

    beta = 3.912 / V (1/km, Koschmieder); the haze is beta less the Rayleigh the
    atmosphere already carries; Mie extinction = min(share x haze, cap), split
    by the engine's own single-scattering albedo. The fog keeps the rest of
    the HAZE: its density times ``fog_factor`` = (beta - Rayleigh - mie) /
    beta, so Rayleigh (the atmosphere's own) + Mie + fog = beta at the ground:
    the visibility's extinction counted once. (Fix pass 2026-11-09: the fog
    used to keep 1 - mie / beta, Rayleigh included, while the atmosphere drew
    its Rayleigh too.) Returns 1/km values and the factor."""
    visibility = max(float(visibility_km), MIN_VISIBILITY_KM)
    beta = KOSCHMIEDER / visibility
    haze = max(beta - RAYLEIGH_GREEN_PER_KM, 0.0)
    mie = min(max(float(share), 0.0) * haze, max(float(cap_per_km), 0.0))
    return {
        "beta_per_km": beta,
        "mie_extinction_per_km": mie,
        "mie_scattering_per_km": mie * MIE_SINGLE_SCATTER_ALBEDO,
        "mie_absorption_per_km": mie * (1.0 - MIE_SINGLE_SCATTER_ALBEDO),
        "fog_factor": max(haze - mie, 0.0) / beta if beta > 0.0 else 0.0,
    }


#: The analytic height fog's sun lobe is pow(cos, n) / 4 pi beyond the
#: volumetric fog's distance (the project keeps r.SupportExpFogMatchesVolumetricFog
#: at 0, so the measure renders' fog is untouched); its exponent is fitted so the
#: lobe's mean cosine (n+1)/(n+2) is the volumetric fog's g: one haze, one phase.
FOG_EXPONENT_MIN = 1.0
FOG_EXPONENT_MAX = 64.0


def vfog_scattering_compensation(preset: str) -> float:
    """The lights' volumetric-fog scattering factor for a world preset: a
    row that scales the volumetric fog's extinction below 1 (the wet rows,
    :data:`WET_VFOG_EXTINCTION_SCALE`) puts the in-scatter back by its
    inverse, so only the extinction is scaled; 1 everywhere else. The C++
    twin is FlightSimWorldPure::VFogScatteringCompensation."""
    scale = float(ATMOSPHERE[preset]["vfog_extinction_scale"])
    return 1.0 / scale if 0.0 < scale < 1.0 else 1.0


def fog_directional_exponent(g: float) -> float:
    """The analytic fog's DirectionalInscatteringExponent for a volumetric g."""
    gc = min(max(float(g), 0.0), 0.99)
    n = (2.0 * gc - 1.0) / (1.0 - gc)
    return min(max(n, FOG_EXPONENT_MIN), FOG_EXPONENT_MAX)


#: The sun's transmittance model the world look sets on a scene without a
#: -sky= plan: True, the engine's per-pixel atmosphere transmittance (the beam
#: reddened and dimmed along the true slant path). The ONE flag both lanes
#: read: core/scene/beauty_look.py must then put the outer-space illuminance
#: on the light and leave its colour neutral (the engine does the reddening);
#: FlightSimWorldPure::SunPerPixelTransmittance is pinned to it.
SUN_PER_PIXEL_TRANSMITTANCE = True


# -- the planet's ground albedo ------------------------------------------------------

#: The sky atmosphere's ground albedo is its MULTIPLE-SCATTERING ground bounce
#: (the engine's multi-scattering LUT is the only pass that reads it; the main
#: view's sky ray march and aerial perspective draw no albedo-lit ground), so
#: it is the mean colour of the ground under the sky, never a horizon fill.
#: One row per surface word (core/environment/surface.py; card weather_look.
#: surface), sRGB bytes. UNCALIBRATED: set by probe render on the render
#: machine (the mean of a clear-noon nadir frame of the tiles at each surface).
GROUND_ALBEDO_SRGB: Dict[str, Tuple[int, int, int]] = {
    "default": (92, 96, 78),
    "desert": (156, 124, 92),
    "forest": (62, 74, 52),
    "grassland": (96, 108, 70),
    "snow": (206, 210, 216),
    "bare": (120, 110, 96),
    "city": (104, 104, 100),
    "ocean": (40, 52, 60),
}


def _srgb_to_linear(byte: float) -> float:
    c = max(min(byte / 255.0, 1.0), 0.0)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb_byte(c: float) -> int:
    c = max(min(c, 1.0), 0.0)
    s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055
    return int(math.floor(s * 255.0 + 0.5))


def ground_albedo_srgb(surface: Optional[str], wetness: float) -> Tuple[int, int, int]:
    """The planet's ground albedo: the surface's row, darkened in linear light
    by the tiles' own wet law (x (1 - WET_DARKENING x wetness)), so the sky's
    ground bounce and the tiles darken together."""
    row = GROUND_ALBEDO_SRGB.get(surface or "default", GROUND_ALBEDO_SRGB["default"])
    k = 1.0 - WET_DARKENING * max(min(float(wetness), 1.0), 0.0)
    return tuple(_linear_to_srgb_byte(_srgb_to_linear(b) * k) for b in row)


# -- the cloud presets -------------------------------------------------------------

CLOUD_PRESETS: Tuple[str, ...] = ("cumulus", "stratocumulus", "overcast", "nimbostratus")

#: Selection thresholds (select_cloud). UNCALIBRATED.
CLOUD_OVERCAST_COVER = 0.85
STRATOCUMULUS_MAX_THICKNESS_M = 900.0
STRATOCUMULUS_MIN_COVER = 0.5

CLOUD_FIELDS: Tuple[str, ...] = (
    "extinction_per_m",   # the cloud's extinction inside a full cell (1/m)
    "shape_scale_km",     # the base shape noise's feature size
    "detail_scale_km",    # the erosion noise's feature size
    "detail_erosion",     # how much the detail noise eats the edges (0..1)
    "bottom_softness",    # share of the layer's thickness the base fades over
    "top_rounding",       # share of the layer's thickness the top rounds over
    "coverage_contrast",  # how hard the coverage threshold cuts
    "default_cover",      # the cover a layer gets when the card states none (fair mode)
)

#: UNCALIBRATED: set by probe render on the render machine. The extinctions are
#: the literature's order for water clouds (0.02 to 0.1 /m: sigma = 3 LWC /
#: (2 rho r_e) with LWC 0.2 to 0.5 g/m^3, r_e 5 to 10 um), below the storm
#: tower's 0.19 /m (core/scene/storm_cell.py).
CLOUDS: Dict[str, Dict[str, float]] = {
    "cumulus": dict(extinction_per_m=0.05, shape_scale_km=2.5, detail_scale_km=0.35,
                    detail_erosion=0.35, bottom_softness=0.08, top_rounding=0.6,
                    coverage_contrast=1.6, default_cover=0.35),
    "stratocumulus": dict(extinction_per_m=0.04, shape_scale_km=4.0, detail_scale_km=0.5,
                          detail_erosion=0.25, bottom_softness=0.15, top_rounding=0.3,
                          coverage_contrast=1.3, default_cover=0.6),
    "overcast": dict(extinction_per_m=0.03, shape_scale_km=8.0, detail_scale_km=0.8,
                     detail_erosion=0.15, bottom_softness=0.2, top_rounding=0.15,
                     coverage_contrast=1.0, default_cover=0.95),
    "nimbostratus": dict(extinction_per_m=0.045, shape_scale_km=6.0, detail_scale_km=0.6,
                         detail_erosion=0.2, bottom_softness=0.1, top_rounding=0.4,
                         coverage_contrast=1.2, default_cover=0.98),
}

#: The fair-weather layer ``-beauty-clouds=fair`` adds when the card states no
#: cloud (a stated stylisation, recorded; never the default). UNCALIBRATED.
FAIR_LAYER = {"cover": 0.35, "base_m": 1500.0, "top_m": 2700.0}

#: Round 3 (2026-11-10): the cover a RAIN world's layer gets when the card states
#: none. The rain preset draws nimbostratus, whose default cover (0.98) is a solid
#: sheet: round 1's #06 (A320 over SFO at 3000 m, moderate rain, no cloud on the
#: card) showed cloud-top white and sky and no ground at all. A card that states a
#: cover (an overcast word, a sampled deck) keeps it; a storm keeps its deck. 0.6
#: is the low end of METAR "broken" (5/8): the layer reads as rain cloud and the
#: ground reads through its gaps. UNCALIBRATED: set by probe render on the render
#: machine (#06's lower half should show the bay and the city between clouds).
RAIN_DEFAULT_COVER = 0.6

#: The seeded noise offset spans this many km, so two seeds never share a sky.
CLOUD_SEED_SPAN_KM = 1000.0
#: The extinction scale on the material (1 = the row's 1/m read as the engine's
#: unit); the WX.4-style probe sets it. UNCALIBRATED.
CLOUD_EXTINCTION_SCALE = 1.0
#: A frame whose camera-to-aircraft path through a layer leaves less than this
#: estimated transmittance is flagged ``cloud_occludes_aircraft``. UNCALIBRATED.
OCCLUSION_FLAG_TRANSMITTANCE = 0.5

# -- clouds-sky round 2 (2026-11-09): the march, the default layer, the sky ------------
# The first real renders (Intel iGPU, D3D11) banded shot d's clouds: 96 x 2 view
# samples over an 80 km trace (400 m steps through 0.05/m cloud) and 10
# UNJITTERED quadratic shadow samples over 15 km (the engine disables the shadow
# jitter: VolumetricCloud.usf), so a cloud's light came in contours and most of
# it went unlit (the dark navy veil over the sky). The C++ twin is
# FlightSimClouds.cpp's pure block (CloudMarch, CloudShadowTracingKm,
# CloudCappedTopM, SkyMultiScattering). UNCALIBRATED: set by probe render on
# the render machine (every number).

#: The march by GPU class (GRHIDeviceIsIntegrated): the component's view and
#: shadow sample-count scales (the engine's 96 and 10 samples times these,
#: under its caps 768 and 80) and the trace's max distance inside the layer.
#: The "integrated" row is the CONSTRAINED GPU class (C++ CloudConstrainedGpu: an
#: integrated adapter or any feature level below SM6, e.g. D3D11 SM5) and is
#: ef361bd6's march exactly (192 view, 10 shadow, 80 km, a fixed 15 km shadow
#: march, no default-layer thinning, no multiple-scattering change): round 1
#: (2026-11-09) deadlocked every beauty run on the render laptop's Intel iGPU in
#: the sky light capture and git bisect named this lane's round-2 commit.
#:
#: Clouds round 6 (2026-11-10): the march samples a layer in FIXED altitude
#: slices (the engine's StepT is the slab path over the sample count, so sample
#: k sits at NormAlt (k + jitter) / N for every pixel), and at extinction_per_m
#: x StepT of about 4 each slice is opaque. The engine hides the slices with a
#: per-pixel, per-capture blue-noise start offset that TSR averages over the
#: still's sub-frames; a rendering COMMANDLET gets a constant one instead
#: (BlueNoise.cpp's 1x1 dummy, or a texture still building answering as a
#: default stand-in), which is why round 3's clear-sky frames drew horizontal
#: strata, pancake ledges and topographic contours with no grain in them. The
#: render commandlet now loads and builds the two blue-noise textures before
#: its first capture and records render_settings.beauty_path.blue_noise
#: (cloud_march_jittered). No row here changes: the fix adds no march cost.
CLOUD_MARCH_FIELDS: Tuple[str, ...] = ("view_sample_count_scale", "shadow_sample_count_scale",
                                       "tracing_max_distance_km")
CLOUD_MARCH: Dict[str, Dict[str, float]] = {
    "discrete": dict(view_sample_count_scale=6.0, shadow_sample_count_scale=6.0, tracing_max_distance_km=50.0),
    "integrated": dict(view_sample_count_scale=2.0, shadow_sample_count_scale=1.0, tracing_max_distance_km=80.0),
}
#: The engine's base samples and caps (VolumetricCloudComponent.h, VolumetricCloudRendering.cpp).
ENGINE_CLOUD_BASE_VIEW_SAMPLES = 96.0
ENGINE_CLOUD_BASE_SHADOW_SAMPLES = 10.0
ENGINE_CLOUD_VIEW_SAMPLE_CAP = 768.0
ENGINE_CLOUD_SHADOW_SAMPLE_CAP = 80.0
#: The shadow march spans the layer it lights, not 15 km: km per km of thickness, clamped.
CLOUD_SHADOW_KM_PER_KM = 1.0
CLOUD_SHADOW_MIN_KM = 1.0
CLOUD_SHADOW_MAX_KM = 4.0
#: The constrained class's shadow march: ef361bd6's fixed 15 km.
CLOUD_SHADOW_CONSTRAINED_KM = 15.0
#: The default layer (the -sky= plan's VISUAL ONLY 3 km slab, never a card's
#: stated layer) is thinned to the shape's depth; 0 keeps the layer as built.
CLOUD_MAX_THICKNESS_M: Dict[str, float] = {"cumulus": 2000.0, "stratocumulus": 0.0,
                                           "overcast": 2000.0, "nimbostratus": 0.0}
#: USkyAtmosphereComponent::MultiScatteringFactor per preset (engine 1): the
#: clear and hazy skies take a little more multiple scattering (paler and
#: brighter towards the horizon from altitude); the weather presets keep 1.
SKY_MULTI_SCATTERING: Dict[str, float] = {"clear": 1.25, "hazy": 1.15, "overcast": 1.0, "rain": 1.0,
                                          "storm": 1.0}


def cloud_march(integrated: bool) -> Dict[str, float]:
    """The march row for the GPU class, with the engine's sample counts."""
    row = dict(CLOUD_MARCH["integrated" if integrated else "discrete"])
    row["view_samples_max"] = min(ENGINE_CLOUD_BASE_VIEW_SAMPLES * row["view_sample_count_scale"],
                                  ENGINE_CLOUD_VIEW_SAMPLE_CAP)
    row["shadow_samples"] = min(ENGINE_CLOUD_BASE_SHADOW_SAMPLES * row["shadow_sample_count_scale"],
                                ENGINE_CLOUD_SHADOW_SAMPLE_CAP)
    return row


def cloud_shadow_tracing_km_for(constrained: bool, thickness_m: float) -> float:
    """The shadow march for the GPU class (constrained: ef361bd6's fixed 15 km)."""
    return CLOUD_SHADOW_CONSTRAINED_KM if constrained else cloud_shadow_tracing_km(thickness_m)


def cloud_shadow_tracing_km(thickness_m: float) -> float:
    """The shadow march's length for a layer of this thickness."""
    km = max(float(thickness_m), 0.0) / 1000.0 * CLOUD_SHADOW_KM_PER_KM
    return min(max(km, CLOUD_SHADOW_MIN_KM), CLOUD_SHADOW_MAX_KM)


def cloud_capped_top_m(shape: str, base_m: float, top_m: float, stated: bool) -> float:
    """The drawn top: the default layer thinned to CLOUD_MAX_THICKNESS_M[shape];
    a stated layer (the card's, or the -beauty-clouds=fair one) as built."""
    cap = CLOUD_MAX_THICKNESS_M.get(shape, 0.0)
    if stated or cap <= 0.0 or top_m - base_m <= cap:
        return top_m
    return base_m + cap


# -- visual round 5, lane L3 (2026-11-10): the distant 2D cloud sheet -----------------------
# Round 3's frames (#03, #06, #09, #13) drew thin, streaky volumetric clouds
# that stopped a few tens of kilometres out and an EMPTY horizon. UE 5.7 still
# ships /Engine/EngineSky/BP_Sky_Sphere with its panning-cloud materials
# (M_Sky_Panning_Clouds, M_Sky_Panning_Clouds2, T_Sky_Clouds_M), but a sky sphere
# covers the SkyAtmosphere, so the far deck is OUR sheet: one large disc drooping
# with the earth's curvature at the cloud layer's altitude, an unlit translucent
# material (assets/shaders/world/distant_clouds.hlsl) drawing the SAME
# Perlin-Worley shape as the volumetric layer at its mid-altitude slice, with
# cheap fake lighting. No depth write, no custom depth, hidden on every label
# capture (BeautyOnlyActors), zero march cost. On the constrained GPU the
# volumetric march's TracingMaxDistance shrinks to the near field where the
# sheet takes over (distant_tracing_max_km): the engine's sample count is
# SampleCountMax x saturate(path / r.VolumetricCloud.DistanceToSampleMaxCount),
# non-decreasing in the path, so a shorter trace never adds a sample and only
# shortens the step. The C++ twin is FlightSimClouds.cpp's pure block
# (DistantSheet*, DistantLook). UNCALIBRATED: set by probe render on the render
# machine (every number).

#: The disc: radius, tessellation (rings densify towards the centre: ring i at
#: radius x (i / rings)^2), the earth's radius for the droop.
DISTANT_RADIUS_KM = 300.0
DISTANT_RINGS = 48
DISTANT_SEGMENTS = 96
DISTANT_EARTH_RADIUS_KM = 6371.0
#: The hand-over: the sheet fades in over DISTANT_FADE_KM ending at the volumetric
#: march's trace distance; on the constrained GPU, with the sheet drawn, that
#: trace shrinks to DISTANT_NEAR_FIELD_KM (never above the class's own row).
DISTANT_FADE_KM = 8.0
DISTANT_NEAR_FIELD_KM = 32.0
#: The sheet is off with the camera inside the layer's slab and fades in over
#: this many metres outside it (the volumetric layer draws the inside).
DISTANT_INSIDE_RAMP_M = 200.0
#: The fake lighting's constants (the material's scalar parameters). UNCALIBRATED.
DISTANT_LOOK: Dict[str, float] = {
    "RimFadeShare": 0.2,      # the sheet fades out over the outer share of the radius
    "Albedo": 0.9,
    "AmbientGain": 1.0,       # x the sky's distant scattered luminance
    "SunWrap": 0.3,           # the N.L wrap
    "BaseDarkening": 0.55,    # a base's ambient as a share of a top's
    "BaseSunShare": 0.15,     # the sun's share through a base's thin parts
    "SilverLining": 0.6,      # the thin edge's forward-scattered sun gain
    "RimPower": 8.0,          # the forward lobe's exponent
    "NormalStrength": 1.5,    # the relief's slope per unit thickness per km
}
#: The cover the sheet takes under a drawn storm cell with no redrawn layer:
#: the nimbostratus row's default (the storm's own deck).
DISTANT_STORM_SHAPE = "nimbostratus"


def distant_clouds_mode(environ: Optional[Dict[str, str]] = None) -> str:
    """The sheet's switch as the host reads it (``-distant-clouds=`` else
    ``FLIGHTSIM_DISTANT_CLOUDS``): ``on`` (the default) or ``off``; any other
    word is the host's refusal ``world_beauty.distant_clouds``."""
    import os
    word = ((os.environ if environ is None else environ).get("FLIGHTSIM_DISTANT_CLOUDS") or "").strip() or "on"
    if word not in ("on", "off"):
        raise ValueError(f"world_beauty.distant_clouds: -distant-clouds={word} is not on or off")
    return word


def distant_storm_cover() -> float:
    """The sheet's cover under a drawn storm cell with no redrawn layer."""
    return CLOUDS[DISTANT_STORM_SHAPE]["default_cover"]


def distant_disc_vertex_count(rings: int = DISTANT_RINGS, segments: int = DISTANT_SEGMENTS) -> int:
    """A centre vertex, then rings x segments."""
    return 1 + rings * segments


def distant_disc_triangle_count(rings: int = DISTANT_RINGS, segments: int = DISTANT_SEGMENTS) -> int:
    """The fan about the centre, then two triangles per ring quad."""
    return segments + 2 * (rings - 1) * segments


def distant_ring_radius_km(ring: int, rings: int = DISTANT_RINGS, radius_km: float = DISTANT_RADIUS_KM) -> float:
    """Ring ``ring`` of ``rings`` sits at radius x (ring / rings)^2: metre-fine
    near the camera, kilometre-coarse at the rim."""
    share = min(max(float(ring) / float(max(rings, 1)), 0.0), 1.0)
    return radius_km * share * share


def distant_droop_m(horizontal_km: float, earth_radius_km: float = DISTANT_EARTH_RADIUS_KM) -> float:
    """The sheet's drop below its altitude at a horizontal distance: the
    earth's curvature, d^2 / 2R (metres, negative downward)."""
    d = float(horizontal_km)
    return -(d * d / (2.0 * earth_radius_km)) * 1000.0


def distant_droop_at_rim_m() -> float:
    return distant_droop_m(DISTANT_RADIUS_KM)


def distant_sheet_altitude_m(camera_m: float, base_m: float, top_m: float) -> Dict[str, Any]:
    """Where the sheet sits for this frame: a camera below the slab's middle
    sees cloud BASES (the sheet at the base), above it cloud TOPS (the sheet at
    the top); ``fade`` is 0 inside the slab, 1 past DISTANT_INSIDE_RAMP_M outside."""
    mid = 0.5 * (float(base_m) + float(top_m))
    above = float(camera_m) >= mid
    altitude = float(top_m) if above else float(base_m)
    if float(camera_m) < float(base_m):
        outside = float(base_m) - float(camera_m)
    elif float(camera_m) > float(top_m):
        outside = float(camera_m) - float(top_m)
    else:
        outside = 0.0
    fade = min(max(outside / DISTANT_INSIDE_RAMP_M, 0.0), 1.0)
    return {"altitude_m": altitude, "from_above": above, "fade": fade}


def distant_tracing_max_km(constrained: bool, sheet_drawn: bool, row_km: float) -> float:
    """The volumetric march's trace with the sheet: on the constrained GPU, with
    the sheet drawn, the near field (never above the class's own row); every
    other case keeps the row. Lowers the march's cost, never raises it."""
    if constrained and sheet_drawn:
        return min(float(row_km), DISTANT_NEAR_FIELD_KM)
    return float(row_km)


def distant_handover_km(trace_km: float) -> float:
    """Where the sheet starts fading in: the trace's end less the fade's width."""
    return max(float(trace_km) - DISTANT_FADE_KM, 0.0)


#: Visual round 2 (weather scenes, 2026-11-10): BEAUTY ONLY, the aircraft is
#: never drawn INSIDE a cloud deck. Round 1's tower view in heavy rain (an A320
#: at 1000 m in the 800-3000 m rain deck) and its 747 in a thunderstorm (2000 m
#: in the 1200-2700 m storm deck) drew the airframe behind hundreds of metres of
#: 0.02-0.045 /m cloud: a flat grey or flat blue frame where the mask shows an
#: aircraft. A deck whose slab, widened by this clearance, holds the aircraft is
#: moved clear of it, its thickness kept: a rain or storm deck goes ABOVE (the
#: rain falls from it onto the aircraft), any other deck to the nearer side. The
#: measure quality never builds the world look, so its decks stand.
#: UNCALIBRATED: set by probe render on the render machine.
AIRCRAFT_LAYER_CLEARANCE_M = 400.0


def aircraft_clear_layer(base_m: float, top_m: float, aircraft_m: float,
                         clearance_m: float = AIRCRAFT_LAYER_CLEARANCE_M,
                         rain_deck: bool = False) -> Dict[str, Any]:
    """The drawn slab of a deck kept clear of the aircraft (heights above the
    scene datum): ``{base_m, top_m, moved, above}``. Unmoved when the aircraft
    is more than ``clearance_m`` outside [base, top] or the slab is empty. The
    C++ twin is FlightSimWorldPure::AircraftClearLayer (FlightSimClouds.cpp)."""
    base, top, z = float(base_m), float(top_m), float(aircraft_m)
    clear = max(float(clearance_m), 0.0)
    thick = top - base
    out = {"base_m": base, "top_m": top, "moved": False, "above": True}
    if not thick > 0.0 or z < base - clear or z > top + clear:
        return out
    above = bool(rain_deck) or (z - base) <= (top - z) or z - clear <= 0.0
    if above:
        new_base = z + clear
        out.update(base_m=new_base, top_m=new_base + thick)
    else:
        new_top = z - clear
        out.update(base_m=max(new_top - thick, 0.0), top_m=new_top)
    out.update(moved=True, above=above)
    return out


def select_cloud(cover: float, thickness_m: float, preset: str) -> str:
    """The cloud shape for a layer: the storm and rain presets draw
    nimbostratus; a deck of CLOUD_OVERCAST_COVER or more is overcast; a thin
    (<= STRATOCUMULUS_MAX_THICKNESS_M), broken (>= STRATOCUMULUS_MIN_COVER)
    layer is stratocumulus; anything else is cumulus."""
    if preset in ("storm", "rain"):
        return "nimbostratus"
    if cover >= CLOUD_OVERCAST_COVER:
        return "overcast"
    if thickness_m <= STRATOCUMULUS_MAX_THICKNESS_M and cover >= STRATOCUMULUS_MIN_COVER:
        return "stratocumulus"
    return "cumulus"


def layer_cover_and_shape(card_cover: Optional[float], thickness_m: float, preset: str,
                          fair: bool) -> Tuple[float, str]:
    """The cover a redrawn layer gets and its shape (FlightSimClouds.cpp
    LayerCoverAndShape, the cover the occlusion row then uses): the fair layer
    is FAIR_LAYER's cover; a card's cover is kept; a rain world's unstated
    layer is RAIN_DEFAULT_COVER (broken, round 3); otherwise the default cover
    of the shape a cover-0 layer of this thickness would be. The shape is then
    chosen again from the cover in force. ``card_cover`` None (or below 0)
    means the card states none."""
    stated = card_cover is not None and card_cover >= 0.0
    guess = select_cloud(float(card_cover) if stated else 0.0, thickness_m, preset)
    if fair:
        cover = FAIR_LAYER["cover"]
    elif stated:
        cover = float(card_cover)
    elif preset == "rain":
        cover = RAIN_DEFAULT_COVER
    else:
        cover = CLOUDS[guess]["default_cover"]
    return cover, select_cloud(cover, thickness_m, preset)


# -- the drawn coverage (cloud_layers.hlsl) ---------------------------------------------

#: Round 2 (clouds-sky, 2026-11-09): the shape noise is a Perlin-Worley field
#: (cloud_shape), not the 4-octave value noise the first renders drew as
#: smeared paint. It bunches around its mean like any fbm, so the shader cuts
#: at the noise's QUANTILE: threshold = CLOUD_FBM_MEAN + CLOUD_FBM_SIGMA x
#: probit(1 - cover) (the shape is near enough normal: the drawn share is
#: within 10 % of the cover at 0.2..0.95, tests/test_world_beauty.py). The two
#: moments are the noise's own (measured on cloud_shape below, re-measured by
#: the test); they are properties of the noise, not look values.
CLOUD_FBM_MEAN = 0.779
CLOUD_FBM_SIGMA = 0.05
#: The cut's soft edge is CLOUD_FBM_SIGMA / coverage_contrast wide.
#: The shaping constants of cloud_layers.hlsl (UNCALIBRATED: set by probe
#: render on the render machine): the top rounds by raising the cut to
#: TOP_CUT_SIGMAS above the mean (domes, flat bases); the soft edge starts
#: EROSION_CUT_SHARE x detail_erosion of its width below the quantile, which
#: the erosion takes back on average (the drawn cover stays the stated one);
#: the erosion is wispy (the detail noise) under CLOUD_WISP_HEIGHT of the
#: layer and billowy (its inverse) above.
CLOUD_TOP_CUT_SIGMAS = 3.5
CLOUD_EROSION_CUT_SHARE = 0.5
CLOUD_WISP_HEIGHT = 0.25
_M32 = 0xFFFFFFFF


def probit_approx(p: float) -> float:
    """The normal quantile, Tukey's lambda approximation (lambda 0.14, scale
    4.91: within 0.01 sigma over 0.003..0.997), the form cloud_layers.hlsl
    evaluates. p is clamped to [1e-4, 1 - 1e-4]."""
    p = min(max(float(p), 1e-4), 1.0 - 1e-4)
    return 4.91 * (p ** 0.14 - (1.0 - p) ** 0.14)


def coverage_threshold(cover: float) -> float:
    """The shape value at the (1 - cover) quantile (before the erosion's
    early start, cloud_density)."""
    return CLOUD_FBM_MEAN + CLOUD_FBM_SIGMA * probit_approx(1.0 - min(max(float(cover), 0.0), 1.0))


def _pcg(v: int) -> int:
    v &= _M32
    state = (v * 747796405 + 2891336453) & _M32
    word = (((state >> ((state >> 28) + 4)) ^ state) * 277803737) & _M32
    return ((word >> 22) ^ word) & _M32


def _hash3(ix: int, iy: int, iz: int, seed: int) -> int:
    """cloud_layers.hlsl FWorldCloud::Hash3: one PCG round over a
    multiply-xor mix of the cell (32-bit, two's complement)."""
    return _pcg(((ix * 0x8DA6B343) & _M32) ^ ((iy * 0xD8163841) & _M32)
                ^ ((iz * 0xCB1AB31F) & _M32) ^ (seed & _M32))


def _fade(t: float) -> float:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _grad(h: int, x: float, y: float, z: float) -> float:
    h &= 15
    u = x if h < 8 else y
    v = y if h < 4 else (x if h in (12, 14) else z)
    return (u if (h & 1) == 0 else -u) + (v if (h & 2) == 0 else -v)


def _perlin3(x: float, y: float, z: float, seed: int) -> float:
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    u, v, w = _fade(fx), _fade(fy), _fade(fz)

    def g(a, b, c):
        return _grad(_hash3(ix + a, iy + b, iz + c, seed), fx - a, fy - b, fz - c)

    return _lerp(_lerp(_lerp(g(0, 0, 0), g(1, 0, 0), u), _lerp(g(0, 1, 0), g(1, 1, 0), u), v),
                 _lerp(_lerp(g(0, 0, 1), g(1, 0, 1), u), _lerp(g(0, 1, 1), g(1, 1, 1), u), v), w)


def _perlin_fbm(x: float, y: float, z: float, seed: int) -> float:
    """FWorldCloud::PerlinFbm: four octaves of gradient noise, 0..1."""
    total, amp = 0.0, 0.5
    for octave in range(4):
        total += amp * _perlin3(x, y, z, (seed + octave * 101) & _M32)
        x, y, z = x * 2.03 + 17.1, y * 2.03 + 31.7, z * 2.03 + 7.3
        amp *= 0.5
    return min(max(0.5 + 0.5 * total / 0.9375, 0.0), 1.0)


def _worley(x: float, y: float, z: float, seed: int) -> float:
    """FWorldCloud::Worley: 1 - F1 over the 27 nearest cells, clamped to 0..1."""
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    best = 9.0
    for dz in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                cx, cy, cz = ix + dx, iy + dy, iz + dz
                h = _hash3(cx, cy, cz, seed)
                d = ((cx + (h & 1023) / 1024.0 - x) ** 2 + (cy + ((h >> 10) & 1023) / 1024.0 - y) ** 2
                     + (cz + ((h >> 20) & 1023) / 1024.0 - z) ** 2)
                best = min(best, d)
    return 1.0 - min(math.sqrt(best), 1.0)


def _remap(v: float, lo: float, hi: float) -> float:
    return min(max((v - lo) / max(hi - lo, 1e-4), 0.0), 1.0)


def _smoothstep(e0: float, e1: float, x: float) -> float:
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def cloud_shape(x: float, y: float, z: float, seed: int) -> float:
    """cloud_layers.hlsl FWorldCloud::Shape, number for number (double here):
    the gradient fbm dilated by an inverted Worley cell, then cut by a
    two-octave Worley fbm (Schneider's Perlin-Worley base shape)."""
    perlin = _perlin_fbm(x, y, z, seed)
    cells = _worley(x, y, z, (seed + 211) & _M32)
    pw = _remap(perlin, cells - 1.0, 1.0)
    fbm = (0.75 * _worley(x * 2.03, y * 2.03, z * 2.03, (seed + 307) & _M32)
           + 0.25 * _worley(x * 4.1, y * 4.1, z * 4.1, (seed + 401) & _M32))
    return _remap(pw, fbm - 1.0, 1.0)


def cloud_detail(x: float, y: float, z: float, seed: int) -> float:
    """cloud_layers.hlsl FWorldCloud::Detail: the erosion's three-octave Worley fbm."""
    return (0.625 * _worley(x, y, z, seed) + 0.25 * _worley(x * 2.03, y * 2.03, z * 2.03, (seed + 97) & _M32)
            + 0.125 * _worley(x * 4.1, y * 4.1, z * 4.1, (seed + 193) & _M32))


def cloud_density(km: Tuple[float, float, float], norm_alt: float, cover: float, row: Dict[str, float]) -> float:
    """cloud_layers.hlsl's density (before x extinction), the Python replica
    the coverage test samples: the quantile cut on the shape (started early by
    the erosion's share, raised over the top's rounding), the soft edge, the
    erosion (only inside the cloud, as the shader's branch), the base fade."""
    h = min(max(norm_alt, 0.0), 1.0)
    base = _smoothstep(0.0, max(row["bottom_softness"], 1e-3), h)
    top = 1.0 - _smoothstep(1.0 - max(row["top_rounding"], 1e-3), 1.0, h)
    scale = max(row["shape_scale_km"], 1e-3)
    shape = cloud_shape(km[0] / scale, km[1] / scale, km[2] * 2.0 / scale, 7)
    soft = CLOUD_FBM_SIGMA / max(row["coverage_contrast"], 1e-3)
    thr = coverage_threshold(cover) - CLOUD_EROSION_CUT_SHARE * row["detail_erosion"] * soft
    cut = _lerp(CLOUD_FBM_MEAN + CLOUD_TOP_CUT_SIGMAS * CLOUD_FBM_SIGMA, thr, top)
    density = _remap(shape, cut, cut + soft)
    if density > 0.0:
        dscale = max(row["detail_scale_km"], 1e-3)
        detail = cloud_detail(km[0] / dscale, km[1] / dscale, km[2] / dscale, 13)
        wisp = _lerp(detail, 1.0 - detail, min(max(h / CLOUD_WISP_HEIGHT, 0.0), 1.0))
        density = _remap(density, row["detail_erosion"] * wisp, 1.0)
    return density * base


def cloud_seed_offset_km(seed: int) -> Tuple[float, float, float]:
    """The noise offset of a seeded sky: three uniforms of the card's seed
    (rain_field.unit, index 0, channels 0..2) times CLOUD_SEED_SPAN_KM."""
    return tuple(unit(int(seed), 0, channel) * CLOUD_SEED_SPAN_KM for channel in range(3))


def slab_path_m(a_z_m: float, b_z_m: float, length_m: float, base_m: float, top_m: float) -> float:
    """The length (m) of a straight segment of ``length_m`` from height a to
    height b that lies inside the slab [base, top]."""
    if not top_m > base_m or length_m <= 0.0:
        return 0.0
    if a_z_m == b_z_m:
        return length_m if base_m <= a_z_m <= top_m else 0.0
    t0 = (base_m - a_z_m) / (b_z_m - a_z_m)
    t1 = (top_m - a_z_m) / (b_z_m - a_z_m)
    lo, hi = min(t0, t1), max(t0, t1)
    lo, hi = max(lo, 0.0), min(hi, 1.0)
    return max(hi - lo, 0.0) * length_m


def occlusion(a_z_m: float, b_z_m: float, length_m: float, base_m: float, top_m: float,
              cover: float, extinction_per_m: float, extinction_scale: float,
              flag_transmittance: float = OCCLUSION_FLAG_TRANSMITTANCE) -> Dict[str, float]:
    """The ESTIMATED transmittance of the cloud layer between the camera and
    the aircraft: the path inside the slab times the cover (the expected
    share of it in cloud) times the extinction. An estimate of the mean, not
    the drawn noise's value; recorded per frame so a consumer can drop frames
    whose mask shows an aircraft the beauty hides."""
    path = slab_path_m(a_z_m, b_z_m, length_m, base_m, top_m)
    tau = path * max(cover, 0.0) * max(extinction_per_m, 0.0) * max(extinction_scale, 0.0)
    transmittance = math.exp(-tau)
    return {"path_m": path, "tau": tau, "transmittance": transmittance,
            "flagged": transmittance < flag_transmittance}


#: The lightning's sky pulse: flash power at the camera normalised by this
#: illuminance (lux) reads as a full flash. UNCALIBRATED.
LIGHTNING_REFERENCE_LUX = 50.0


def sky_pulse_scale(flash_norm: float, gain: float) -> float:
    """The sky light's multiplier during a flash: 1 + gain x clamp(flash, 0, 1)."""
    return 1.0 + max(gain, 0.0) * min(max(flash_norm, 0.0), 1.0)


# -- the tiles' look (the material parameter collection) ----------------------------

#: MPC_FlightSimWorld's scalars: the contract between
#: scripts/ue_create_materials.py (the collection and M_FlightSimTilesBeauty),
#: assets/shaders/world/tiles_*.hlsl and FlightSimClouds.cpp. Defaults are what
#: a material reads before the render sets anything (dry, ungraded: the look
#: Cesium's own material has). The detail constants are UNCALIBRATED.
#: DetailFadeM 400 m keeps the 2 m detail wavelength above about 4 px at 1080p
#: and a 60 degree view (fix pass 2026-11-09: 1500 m shimmered).
WORLD_MPC = "MPC_FlightSimWorld"
WORLD_MPC_SCALARS: Dict[str, float] = {
    "Wetness": 0.0,
    "PuddleAmount": 0.0,
    "Dehaze": 0.0,
    "Saturation": 1.0,
    "DetailStrength": 0.0,
    "DetailFadeM": 400.0,
    "DetailScaleM": 2.0,
    # tiles-delight (core/scene/tiles_delight.py): 0 is a pass-through.
    "DelightAmount": 0.0,
    "DelightBlueGate": 4.0,
    # lane B terrain detail (2026-11-11): the engine origin's orthometric
    # height, so tiles_detail_*.hlsl's snowline is an altitude. Set by
    # FlightSimClouds.cpp from the tiles' origin; Known 0 = unset (no snowline).
    "GroundAltitudeM": 0.0,
    "GroundAltitudeKnown": 0.0,
}
#: How much of the wetness becomes standing water on flat ground. UNCALIBRATED.
PUDDLE_SHARE_OF_WETNESS = 0.5

#: The tileset's imagery correction: properties of the photogrammetry (the haze
#: and the colour loss baked in when it was captured), not of today's weather,
#: so ONE value for every preset (the weather's haze is the atmosphere's and
#: the fog's; the weather's desaturation is beauty_look's frame grade).
#: TILES_DEHAZE is the share of TILES_HAZE_RGB taken off, by the soft-toe law
#: of tiles_base_colour.hlsl: removal h x a / (a + k), k = h / (1 - TOE), then
#: renormalised so white stays white. About h comes off a bright texel; a dark
#: one keeps at least TILES_DEHAZE_TOE of its value in every channel, so a
#: shadow never clips and dark vegetation keeps its blue. TILES_HAZE_RGB is a
#: dark-object level (linear), not a sky colour.
#: UNCALIBRATED: set by probe render on the render machine (a clear-noon nadir
#: frame of the tiles, PROBE_LOG.md ## world).
TILES_DEHAZE = 0.8
TILES_HAZE_RGB: Tuple[float, float, float] = (0.010, 0.015, 0.022)
TILES_SATURATION = 1.05
TILES_DEHAZE_TOE = 0.5

#: The wet-ground law, ONE source for the tiles (tiles_base_colour.hlsl,
#: tiles_roughness.hlsl), the scatter (scatter_surface.hlsl, M_FlightSimScatter)
#: and the planet's ground albedo (ground_albedo_srgb); tests/test_world_beauty.py
#: pins every shader's copy to these. WET_DARKENING follows Lekner & Dorf 1988's
#: order (a wet porous surface's albedo falls by about a third); the rest are
#: UNCALIBRATED: set by probe render on the render machine.
WET_DARKENING = 0.30
PUDDLE_DARKENING = 0.55
ROUGHNESS_DRY = 0.92
ROUGHNESS_WET = 0.25
ROUGHNESS_PUDDLE = 0.05


def tiles_dehaze(albedo: Sequence[float], dehaze: float = TILES_DEHAZE) -> Tuple[float, ...]:
    """tiles_base_colour.hlsl's dehaze, channel by channel (linear)."""
    out = []
    for a, haze in zip(albedo, TILES_HAZE_RGB):
        a = max(float(a), 0.0)
        h = max(float(dehaze), 0.0) * haze
        k = h / (1.0 - TILES_DEHAZE_TOE)
        out.append((a - h * a / max(a + k, 1e-6)) / (1.0 - h / (1.0 + k)))
    return tuple(out)


def tiles_parameters(preset: str, card_wetness: float) -> Dict[str, float]:
    """The collection's values for a preset and the card's wetness (the larger
    of the card's and the preset's floor)."""
    row = ATMOSPHERE[preset]
    wet = max(min(max(card_wetness, 0.0), 1.0), row["wetness_floor"])
    out = dict(WORLD_MPC_SCALARS)
    out.update({"Wetness": wet, "PuddleAmount": wet * PUDDLE_SHARE_OF_WETNESS,
                "Dehaze": TILES_DEHAZE, "Saturation": TILES_SATURATION,
                "DetailStrength": row["tiles_detail_strength"],
                # tiles-delight: the preset's de-light amount (tiles_delight.DELIGHT_DEFAULTS).
                "DelightAmount": tiles_delight.amount_for(preset),
                "DelightBlueGate": tiles_delight.DELIGHT_BLUE_GATE})
    return out


# -- run-time overrides -------------------------------------------------------------

OVERRIDE_SECTIONS = {"atmosphere": (PRESETS, ATMOSPHERE_FIELDS),
                     "clouds": (CLOUD_PRESETS, CLOUD_FIELDS)}
OVERRIDE_CONSTANTS = ("cloud_extinction_scale", "occlusion_flag_transmittance",
                      "lightning_reference_lux", "detail_fade_m", "detail_scale_m",
                      "puddle_share_of_wetness", "tiles_dehaze", "tiles_saturation")


def validate_overrides(doc: Dict[str, Any]) -> List[str]:
    """The names an overrides file may carry (``-world-beauty-overrides=``):
    {"atmosphere": {preset: {field: number}}, "clouds": {shape: {field: number}},
    "constants": {name: number}}. Returns every problem, by name; [] is valid.
    The host refuses a file with any (world_beauty.overrides)."""
    problems: List[str] = []
    if not isinstance(doc, dict):
        return ["the overrides file is not a JSON object"]
    for key in doc:
        if key not in OVERRIDE_SECTIONS and key != "constants":
            problems.append(f"unknown section {key!r}")
    for section, (rows, fields) in OVERRIDE_SECTIONS.items():
        block = doc.get(section, {})
        if not isinstance(block, dict):
            problems.append(f"{section} is not an object")
            continue
        for row, values in block.items():
            if row not in rows:
                problems.append(f"{section}.{row} is not one of {list(rows)}")
                continue
            if not isinstance(values, dict):
                problems.append(f"{section}.{row} is not an object")
                continue
            for field, value in values.items():
                if field not in fields:
                    problems.append(f"{section}.{row}.{field} is not a field")
                elif not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.append(f"{section}.{row}.{field} is not a number")
    constants = doc.get("constants", {})
    if not isinstance(constants, dict):
        problems.append("constants is not an object")
    else:
        for name, value in constants.items():
            if name not in OVERRIDE_CONSTANTS:
                problems.append(f"constants.{name} is not one of {list(OVERRIDE_CONSTANTS)}")
            elif not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"constants.{name} is not a number")
    return problems


# -- the ground scatter (FlightSimGroundDetail.cpp) ----------------------------------

SCATTER_FORMAT = "flightsim.ground_scatter"
SCATTER_VERSION = 1
#: Licences a scatter asset may carry: redistributable, no NC (the project rule).
SCATTER_LICENCES = ("CC0-1.0", "CC-BY-4.0")
#: The most instances one sidecar may place, over all species (the host's cap too).
MAX_TOTAL_INSTANCES = 100000
#: Where the pins live (scripts/fetch_scatter_assets.py writes their sha256s).
PINS_PATH = Path(__file__).resolve().parents[2] / "assets" / "scatter" / "polyhaven_pins.json"

#: Per-biome species, density and size. UNCALIBRATED: set by probe render
#: (a nadir density probe against WorldCover tree fraction is V4's clause).
#: The meshes are the paths scripts/ue_import_scatter.py (TODO, recorded)
#: imports the pinned glTFs to.
BIOMES: Dict[str, Dict[str, Any]] = {
    "forest": {
        "species": [
            {"id": "fir_tree_01", "density_per_ha": 25.0, "scale_min": 0.8, "scale_max": 1.25,
             "cull_end_m": 4000.0},
            {"id": "jacaranda_tree", "density_per_ha": 4.0, "scale_min": 0.8, "scale_max": 1.1,
             "cull_end_m": 4000.0},
            {"id": "shrub_02", "density_per_ha": 60.0, "scale_min": 0.7, "scale_max": 1.3,
             "cull_end_m": 1200.0},
            {"id": "rock_moss_set_01", "density_per_ha": 3.0, "scale_min": 0.6, "scale_max": 1.4,
             "cull_end_m": 1500.0},
            {"id": "grass_medium_01", "density_per_ha": 200.0, "scale_min": 0.8, "scale_max": 1.2,
             "cull_end_m": 400.0},
        ],
    },
    "desert": {
        "species": [
            {"id": "quiver_tree_01", "density_per_ha": 1.5, "scale_min": 0.8, "scale_max": 1.2,
             "cull_end_m": 3000.0},
            {"id": "searsia_lucida", "density_per_ha": 6.0, "scale_min": 0.7, "scale_max": 1.2,
             "cull_end_m": 1500.0},
            {"id": "wild_rooibos_bush", "density_per_ha": 20.0, "scale_min": 0.6, "scale_max": 1.3,
             "cull_end_m": 900.0},
            {"id": "namaqualand_boulder_02", "density_per_ha": 2.0, "scale_min": 0.5,
             "scale_max": 1.5, "cull_end_m": 2000.0},
        ],
    },
}
#: The sidecar's placement constants (FlightSimGroundDetail.cpp reads each).
#: UNCALIBRATED. Fix pass 2026-11-09: the re-snap radius is each species' own
#: cull_end_m (every drawn instance is re-traced onto the level of detail the
#: frame streamed), and an instance fades from cull_start_share x cull_end_m
#: (M_FlightSimScatter dithers on the per-instance fade) instead of popping.
SCATTER_DEFAULTS: Dict[str, float] = {
    "half_east_m": 1500.0,
    "half_north_m": 1500.0,
    "exclusion_radius_m": 150.0,   # nothing within this of the start (the runway, the takeoff)
    "max_slope_deg": 32.0,         # steeper hits are rejected
    "step_reject_m": 2.5,          # a probe ring spanning more than this is a roof or cliff edge
    "probe_offset_m": 4.0,         # the probe ring's radius
    "sink_m": 0.3,                 # every instance sinks this far (no floating roots)
    "cull_start_share": 0.7,       # instances fade (dithered) from this share of cull_end_m
    "trace_up_m": 3000.0,
    "trace_down_m": 3000.0,
}


#: The scatter's material: reads MPC_FlightSimWorld's Wetness and Saturation by
#: the tiles' own laws (scatter_surface.hlsl), so a wet run's trees are wet
#: with the ground under them. scripts/ue_import_scatter.py (pending) parents
#: every imported glTF material to it; the host records a species whose
#: material is not an instance of it as "dry: not the world material".
SCATTER_MATERIAL = "/Game/FlightSim/M_FlightSimScatter.M_FlightSimScatter"


def scatter_biome_for(surface: Optional[str]) -> Optional[str]:
    """The scatter biome a card's surface (weather_look.surface) draws: the
    surface itself when it is a biome, else None (no scatter: snow, ocean,
    city, ... carry no species). The host refuses a sidecar whose biome is not
    this (ground_scatter.biome)."""
    return surface if surface in BIOMES else None


def species_seed(seed: int, species_index: int) -> int:
    """One species' stream: splitmix64(seed + index + 1)."""
    return splitmix64((int(seed) + int(species_index) + 1) & MASK64)


def instance_count(density_per_ha: float, half_east_m: float, half_north_m: float,
                   max_instances: int) -> int:
    """round(density x area / 1 ha), at most max_instances."""
    area_m2 = 4.0 * max(half_east_m, 0.0) * max(half_north_m, 0.0)
    count = int(math.floor(max(density_per_ha, 0.0) * area_m2 / 1.0e4 + 0.5))
    return max(min(count, int(max_instances)), 0)


def placement(seed: int, species_index: int, index: int, half_east_m: float, half_north_m: float,
              scale_min: float, scale_max: float) -> Tuple[float, float, float, float]:
    """(east m, north m, yaw deg, scale) of one instance, relative to the
    region's centre: uniforms 0..3 of the species' stream."""
    key = species_seed(seed, species_index)
    east = (2.0 * unit(key, index, 0) - 1.0) * half_east_m
    north = (2.0 * unit(key, index, 1) - 1.0) * half_north_m
    yaw = 360.0 * unit(key, index, 2)
    scale = scale_min + (scale_max - scale_min) * unit(key, index, 3)
    return east, north, yaw, scale


def excluded(east_m: float, north_m: float, centre_east_m: float, centre_north_m: float,
             radius_m: float) -> bool:
    return math.hypot(east_m - centre_east_m, north_m - centre_north_m) < radius_m


def placements(sidecar: Dict[str, Any], species_index: int) -> List[Tuple[float, float, float, float]]:
    """Every kept (east, north, yaw, scale) of one species, region-relative,
    before the trace (the host then drops slopes, edges and misses)."""
    region = sidecar["region"]
    species = sidecar["species"][species_index]
    exclusion = sidecar.get("exclusion", {})
    count = instance_count(species["density_per_ha"], region["half_east_m"],
                           region["half_north_m"], species.get("max_instances", MAX_TOTAL_INSTANCES))
    out = []
    for i in range(count):
        east, north, yaw, scale = placement(sidecar["seed"], species_index, i, region["half_east_m"],
                                            region["half_north_m"], species["scale_min"],
                                            species["scale_max"])
        if excluded(east + region.get("centre_east_m", 0.0), north + region.get("centre_north_m", 0.0),
                    exclusion.get("centre_east_m", 0.0), exclusion.get("centre_north_m", 0.0),
                    exclusion.get("radius_m", 0.0)):
            continue
        out.append((east, north, yaw, scale))
    return out


def load_pins(path: Path = PINS_PATH) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pin_complete(pin: Dict[str, Any]) -> bool:
    """A pin is usable when its licence is allowed and every file it names
    (the root glTF and each include) carries a sha256."""
    if pin.get("licence") not in SCATTER_LICENCES:
        return False
    files = [pin.get("root", {})] + list(pin.get("includes", {}).values())
    return all(isinstance(f.get("sha256"), str) and len(f["sha256"]) == 64 for f in files)


def scatter_sidecar(biome: str, seed: int, pins: Optional[Dict[str, Any]] = None,
                    region: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """The sidecar the host's -ground-scatter= reads. Each species carries its
    pin (source URL, licence, the root's sha256) and ``pinned``: the host
    draws only pinned species and records the rest as not drawn (no asset
    without a pinned source, sha256 and licence)."""
    if biome not in BIOMES:
        raise ValueError(f"biome {biome!r} is not one of {sorted(BIOMES)}")
    pins = load_pins() if pins is None else pins
    reg = {"centre_east_m": 0.0, "centre_north_m": 0.0,
           "half_east_m": SCATTER_DEFAULTS["half_east_m"],
           "half_north_m": SCATTER_DEFAULTS["half_north_m"]}
    reg.update(region or {})
    species = []
    total = 0
    for row in BIOMES[biome]["species"]:
        pin = pins["assets"].get(row["id"])
        if pin is None:
            raise ValueError(f"species {row['id']!r} has no pin in {PINS_PATH.name}")
        count = instance_count(row["density_per_ha"], reg["half_east_m"], reg["half_north_m"],
                               MAX_TOTAL_INSTANCES)
        budget = max(MAX_TOTAL_INSTANCES - total, 0)
        total += min(count, budget)
        species.append({
            "id": row["id"],
            "mesh": f"/Game/FlightSim/Scatter/{row['id']}/{row['id']}",
            "density_per_ha": row["density_per_ha"],
            "scale_min": row["scale_min"],
            "scale_max": row["scale_max"],
            "cull_end_m": row["cull_end_m"],
            "resnap_radius_m": row["cull_end_m"],
            "max_instances": budget,
            "source_url": pin["root"]["url"],
            "licence": pin["licence"],
            "sha256": pin["root"].get("sha256"),
            "pinned": pin_complete(pin),
        })
    return {
        "format": SCATTER_FORMAT,
        "version": SCATTER_VERSION,
        "biome": biome,
        "seed": int(seed),
        "region": reg,
        "exclusion": {"centre_east_m": 0.0, "centre_north_m": 0.0,
                      "radius_m": SCATTER_DEFAULTS["exclusion_radius_m"]},
        **{k: v for k, v in SCATTER_DEFAULTS.items()
           if k not in ("half_east_m", "half_north_m", "exclusion_radius_m")},
        "species": species,
        "material": SCATTER_MATERIAL,
        "visual_only": True,
        "not_claimed": [
            "no collision: the flight model and the ground callback never see these",
            "positions are a seeded uniform scatter, not the land cover's trees",
            "instances may stand on flat roofs or water the tiles carry (no land-cover mask yet)",
        ],
    }


def sidecar_sha256(sidecar: Dict[str, Any]) -> str:
    """The digest of the sidecar as written (sorted keys, the file's bytes)."""
    return hashlib.sha256(dumps(sidecar).encode("utf-8")).hexdigest()


def dumps(sidecar: Dict[str, Any]) -> str:
    return json.dumps(sidecar, indent=2, sort_keys=True) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write a ground-scatter sidecar (-ground-scatter=).")
    parser.add_argument("--biome", required=True, choices=sorted(BIOMES))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--half-m", type=float, default=SCATTER_DEFAULTS["half_east_m"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    sidecar = scatter_sidecar(args.biome, args.seed,
                              region={"half_east_m": args.half_m, "half_north_m": args.half_m})
    args.out.write_text(dumps(sidecar), encoding="utf-8")
    unpinned = [s["id"] for s in sidecar["species"] if not s["pinned"]]
    print(f"wrote {args.out} ({args.biome}, seed {args.seed}); "
          + (f"NOT pinned yet (drawn as nothing): {unpinned}; run scripts/fetch_scatter_assets.py"
             if unpinned else "every species pinned"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
