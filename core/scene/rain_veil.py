"""The beauty rain veil: the rain curtain at depth and the fast scud (lane D).

Lane D, 2026-11-11. The owner: "the hurricane does not look real" (#15, the 747 in
strong wind, severe turbulence and heavy rain). The round-4 review: #07 (a tower
view in heavy rain) is a flat grey void with no depth layering and no rain curtain;
the rain everywhere reads as scratches on the lens. A photograph from inside a
tropical storm shows the rain in layers: dense streaks close by, a falling grey
curtain behind them, the distance gone in a few hundred metres; under the dark deck
low, torn scud races past. The rain box (M_RainDrops, 20 x 20 x 16 m around the
lens) draws only the first of these. This module is the Python twin of
FlightSimWeather.cpp's ``ApplyBeautyRainVeil`` / ``StepBeautyRainVeil``:

* the CURTAIN: three open cylinders round the camera (VEIL_SHELL_RADII_M) in
  M_RainCurtain (rain_curtain.hlsl): each the rain of the slab of air it stands
  for -- a grey veil 1 - exp(-beta x slab) (beta the rain's extinction, a stated
  fit of visibility in rain, :func:`rain_extinction_per_km`) and streaks falling
  along the drops' path through the wind, one pixel-scale streak cell wide at
  every shell's radius (the same angular size at every depth: layered, not
  scaled copies). Lit like the drops (translucency volume, per vertex), so the
  veil is the colour of the light under the deck, not a painted grey;
* the SCUD: SCUD_CARDS camera-facing torn cloud cards (M_ScudCard,
  scud_card.hlsl: an eroded fbm, soft edges, a depth fade) in a band from
  SCUD_BAND_BELOW_M under the aircraft to SCUD_DECK_GAP_M under the drawn deck,
  in a box SCUD_BOX_HALF_M round the aircraft that the air carries at the wind
  at cloud base. From a 747 at 128 m/s they stream past: the "fast" of fast scud
  is the aircraft's own motion through still-drifting rags. No card within
  SCUD_CAMERA_CLEAR_M of the camera (the lens is never inside a rag).

Every card is a pure function of (seed, index, run time): deterministic in the
step (Gate 10-R). BEAUTY ONLY: FFlightSimWorldBeauty (-quality=beauty) is the
only caller; the actors are in FFlightSimWeather::BeautyOnlyActors, which every
label capture hides (ConfigureLabelCapture), so the masks, classes, depth and
boxes are byte-identical with the veil on and off. ``-rain-veil=off`` /
FLIGHTSIM_RAIN_VEIL=off draws nothing (an A/B), recorded.

Not claimed: the veil is not a radiative-transfer model of rain; the scud is not
a model of the boundary layer under a tropical cyclone. UNCALIBRATED: every
number is set by probe render on the render machine (#15, #09, #07 first).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from core.scene.rain_field import unit

#: The curtain's shells round the camera (m): near, middle, far.
VEIL_SHELL_RADII_M: Tuple[float, ...] = (25.0, 80.0, 250.0)
#: Segments round each shell (a 24-gon is within 1 % of the circle at its radius).
VEIL_SEGMENTS = 24
#: Each shell spans this many of its radii above and below the camera (cut at the
#: ground in the shader).
VEIL_HEIGHT_RADII = 1.5
#: beta = VEIL_BETA_A x R^VEIL_BETA_B per km (R mm/h): 1.6 /km (Koschmieder
#: visibility 2.4 km) at 10 mm/h, 4.0 /km (1 km) at 40 mm/h -- the order of the
#: visibility in heavy and in tropical rain. A STATED fit, not a measurement.
VEIL_BETA_A = 0.35
VEIL_BETA_B = 0.66
#: The streak cell's width in PIXELS (the shader's StreakRad is set per frame as this x
#: the view's pixel angle: round 9's #07 through a 250 mm lens drew a fixed 0.0015 rad
#: as 14 px bars).
VEIL_STREAK_PIXELS = 2.0
#: A streak cell is this many widths long (before the per-streak length draw).
VEIL_STREAK_ASPECT = 60.0
#: The share of streak cells that hold a streak: STREAK_DENSITY_A x sqrt(R), capped.
VEIL_STREAK_DENSITY_A = 0.08
VEIL_STREAK_DENSITY_MAX = 0.6
#: One curtain streak's most coverage (fainter than a box streak: it is far).
VEIL_STREAK_ALPHA = 0.25

#: The scud cards.
SCUD_CARDS = 40
SCUD_BOX_HALF_M = 2500.0
SCUD_BAND_BELOW_M = 300.0
SCUD_DECK_GAP_M = 50.0
#: Without a drawn deck above the aircraft, the band's top is this far above it.
SCUD_NO_DECK_TOP_M = 400.0
SCUD_WIDTH_M = (150.0, 450.0)
SCUD_ASPECT = (0.3, 0.6)
SCUD_ALPHA = (0.35, 0.75)
SCUD_CAMERA_CLEAR_M = 120.0
#: Cards fade in over this share of the box at its faces (no pop at the wrap).
SCUD_EDGE_SHARE = 0.15
#: Rain rate (mm/h) at and above which the scud is drawn: the severe-rain look's
#: (world_beauty.SEVERE_RAIN_MMH) -- or any storm.
SCUD_MIN_RAIN_MMH = 8.0
SCUD_SEED_SALT = 0x5C0D

#: Round 12's #15 (lane D follow-up): the veil and the scud drew WHITE -- lit per pixel
#: by the sun the deck should hide (forward shading takes the directional light) --
#: "bright white cartoon cumulus puffs" in a pale fog. Their base colour is scaled by
#: Shade: under a drawn deck (the light there is the deck's diffuse transmission) and
#: in the open rain. UNCALIBRATED.
#: Round 26 (generation 4: the veil is UNLIT, its colour the luminance of the scene
#: behind it x Shade -- veil_tone.hlsl): Shade is now the veil's tone RELATIVE TO THE
#: SCENE'S LOCAL MEAN, not a lit albedo: a little darker under a deck, the mean in the
#: open. Neutral by construction (r31/r32: the lit veil carried #10's green).
VEIL_SHADE_UNDER_DECK = 0.85
#: Round 26: 0.8 in the open (#07's streaks drew darker than the grey behind them).
VEIL_SHADE_OPEN = 1.0
#: Round 26 (#07's flat grey field): the veil varied by falling curtains, x (1 +
#: VEIL_VARY x (2n - 1)) over a smooth noise a fifth of the shell's radius across.
VEIL_VARY = 0.6
#: Round 47 (round 44's #07 still a flat grey field): the curtain cells are an ANGLE
#: (a fifth of the radius across, 0.8 tall: 11.3 x 38.7 deg at every shell), so through
#: #07's 250 mm lens (8.2 x 4.6 deg) one cell covered the frame and the veil was one
#: value. The cells now scale like the streak cap (:func:`streak_cap_rad`), never above
#: this; -veil-lens-cells=off keeps generation 5's (the A/B). M_RainCurtain 6.
VEIL_VARY_SCALE_MAX = 1.0
#: Round 19 (#15 and #09 still drew white puffs): the scud card is now MODULATE
#: (M_ScudCard 3): the scene behind it x lerp(1, SCUD_TONE, rag). Under a deck a rag
#: keeps half the light behind it; in open rain 0.7.
#: Round 82 (r69's #15: black ink blotches over the deck; the owner, 2026-11-13: "the
#: clouds dont look that realistic"): scud is grey, a little darker than the haze
#: behind it, not a hole in it: 0.75 under a deck, 0.85 in the open. UNCALIBRATED.
SCUD_TONE_UNDER_DECK = 0.9
SCUD_TONE_OPEN = 0.95
#: The beauty's cinematic rain keeps this share of the camera's own motion: round 12's
#: #15 flew INTO the wind, so the wind lay along the view and the cinematic streaks
#: (the camera's motion left out) fell straight down. A little of the aircraft's
#: 128 m/s (19 m/s) tilts every streak away from the direction of travel, as rain
#: rushes past in a photograph from an aircraft; the measure path's style is unchanged.
BEAUTY_CAMERA_MOTION_SHARE = 0.15
#: The beauty streak cap (weather_look.beauty_rain_shape max_streak_rad) is an angle at
#: this pixel angle (54 deg over 1280 px); a longer lens scales it down with the pixel,
#: so round 9's #07 (250 mm) draws streaks of the same on-screen length, not bars.
BEAUTY_REFERENCE_PIXEL_RAD = 2.0 * math.tan(math.radians(27.0)) / 1280.0
#: Under a drawn storm deck the height fog's light (round 12: a pale white fog): the
#: physical sky lights the fog by the SkyAtmosphere's ambient (FlightSimSky.cpp:
#: SkyAtmosphereAmbientContributionColorScale white), the CLEAR sky above the deck, and
#: by the sun's directional inscattering lobe, neither of which the deck shadows. The
#: beauty scales the ambient to the deck's diffuse transmission (a cool grey), turns the
#: sun lobe off, and cuts the sun's share of the volumetric fog's light. UNCALIBRATED.
#: Round 36 (#10 still green: the scaled ambient keeps its hue, the grassland's
#: bounce): the ambient contribution is OFF under a storm deck and the fog's own
#: inscattering is a neutral grey of STORM_FOG_INSCATTER_NITS (cd/m^2, the physical sky's
#: units: an overcast storm base, ~1000-3000 nits; a stated value). UNCALIBRATED.
STORM_FOG_AMBIENT_RGB = (0.0, 0.0, 0.0)
STORM_FOG_INSCATTER_NITS = 1500.0
STORM_SUN_FOG_SHARE = 0.15

#: The windscreen's water film (M_WindshieldRain 3, windshield_film.hlsl: the
#: pinned CC0 ambientCG "Leaking 019 C" maps) on a cockpit camera's beauty glass:
#: set with the veil (beauty only), 0 on every other render.
BEAUTY_WINDSHIELD_FILM = 1.0

#: Round 6's #15 (lane D follow-up): under the rain preset's 0.6 deck the frame was
#: a blue sky and a bright ground at 2000 m; the scene's height fog (the rain look's
#: haze, lighting.RAIN_ANCHORS) halves every 1 / (falloff / 10) m -- 50 m at the
#: engine's 0.2 -- so at a chase camera 2 km up the rain made no haze at all. In a
#: STORM preset with rain and no stated visibility, the beauty makes the rain's own
#: haze: the fog's falloff opened so it halves over the column from the fog's base to
#: the deck (RAIN_HAZE_FALLOFF_COLUMN = 1: once over the column), and its density
#: set so the extinction AT THE CAMERA'S HEIGHT is the rain's (rain_extinction_per_km),
#: by the project's law beta = FogDensity x FOG_BETA_PER_DENSITY per metre
#: (core/scene/world_beauty.py's WET_VFOG note: 0.1 ln(2)^2). Never thinner than the
#: scene's own fog. UNCALIBRATED: #15 and #09 first.
FOG_BETA_PER_DENSITY = 0.1 * math.log(2.0) ** 2
RAIN_HAZE_FALLOFF_COLUMN = 1.0
#: The column is never taken as shorter than this (m): a deck 300 m over the fog
#: would otherwise make the fog a thin slab.
RAIN_HAZE_MIN_COLUMN_M = 1000.0

CARD_KEYS = ("east_m", "north_m", "up_m", "width_m", "height_m", "alpha")


def rain_extinction_per_km(rate_mmh: float) -> float:
    """The rain's extinction (1/km) for a rate (VEIL_BETA_A x R^VEIL_BETA_B)."""
    rate = max(float(rate_mmh), 0.0)
    return VEIL_BETA_A * rate ** VEIL_BETA_B if rate > 0.0 else 0.0


def shell_veil_alpha(rate_mmh: float, shell: int,
                     radii: Sequence[float] = VEIL_SHELL_RADII_M) -> float:
    """The grey veil of shell ``shell``: 1 - exp(-beta x the slab it stands for)
    (from the previous shell's radius, or the camera, to its own)."""
    inner = float(radii[shell - 1]) if shell > 0 else 0.0
    slab_km = (float(radii[shell]) - inner) / 1000.0
    return 1.0 - math.exp(-rain_extinction_per_km(rate_mmh) * slab_km)


def streak_density(rate_mmh: float) -> float:
    """The share of the curtain's streak cells that hold a streak."""
    return min(VEIL_STREAK_DENSITY_MAX, VEIL_STREAK_DENSITY_A * math.sqrt(max(float(rate_mmh), 0.0)))


def scud_drawn(rate_mmh: float, storm: bool) -> bool:
    """The scud is drawn in a storm preset or in rain of SCUD_MIN_RAIN_MMH or more."""
    return bool(storm) or float(rate_mmh) >= SCUD_MIN_RAIN_MMH


def scud_band(aircraft_up_m: float, deck_base_m: Optional[float]) -> Tuple[float, float]:
    """(bottom, top) of the scud band (m above the datum): from SCUD_BAND_BELOW_M
    under the aircraft to SCUD_DECK_GAP_M under a deck drawn above it, else to
    SCUD_NO_DECK_TOP_M above the aircraft."""
    bottom = float(aircraft_up_m) - SCUD_BAND_BELOW_M
    if deck_base_m is not None and float(deck_base_m) > float(aircraft_up_m):
        top = float(deck_base_m) - SCUD_DECK_GAP_M
    else:
        top = float(aircraft_up_m) + SCUD_NO_DECK_TOP_M
    return bottom, max(top, bottom + 1.0)


def _wrap(v: float, half: float) -> float:
    return v - 2.0 * half * math.floor((v + half) / (2.0 * half))


def _smoothstep(e0: float, e1: float, x: float) -> float:
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def scud_card(seed: int, index: int, t: float, centre_enu_m: Sequence[float],
              camera_enu_m: Sequence[float], wind_en_mps: Sequence[float],
              band: Tuple[float, float]) -> Dict[str, float]:
    """One card at run time t, keys in CARD_KEYS order: its centre (ENU metres of
    the frame the host measures in), size and alpha. The card's air moves at the
    wind; its place is wrapped into the box round ``centre_enu_m`` (the
    aircraft); it fades at the box's faces and inside SCUD_CAMERA_CLEAR_M of the
    camera (0 there)."""
    s = int(seed) ^ SCUD_SEED_SALT
    half = SCUD_BOX_HALF_M
    e0 = (2.0 * unit(s, index, 0) - 1.0) * half + float(wind_en_mps[0]) * t
    n0 = (2.0 * unit(s, index, 1) - 1.0) * half + float(wind_en_mps[1]) * t
    de = _wrap(e0 - float(centre_enu_m[0]), half)
    dn = _wrap(n0 - float(centre_enu_m[1]), half)
    up = band[0] + (band[1] - band[0]) * unit(s, index, 2)
    width = SCUD_WIDTH_M[0] + (SCUD_WIDTH_M[1] - SCUD_WIDTH_M[0]) * unit(s, index, 3)
    height = width * (SCUD_ASPECT[0] + (SCUD_ASPECT[1] - SCUD_ASPECT[0]) * unit(s, index, 4))
    alpha = SCUD_ALPHA[0] + (SCUD_ALPHA[1] - SCUD_ALPHA[0]) * unit(s, index, 5)
    edge = half * SCUD_EDGE_SHARE
    alpha *= _smoothstep(half, half - edge, abs(de)) * _smoothstep(half, half - edge, abs(dn))
    east = float(centre_enu_m[0]) + de
    north = float(centre_enu_m[1]) + dn
    to_camera = math.sqrt((east - float(camera_enu_m[0])) ** 2 + (north - float(camera_enu_m[1])) ** 2
                          + (up - float(camera_enu_m[2])) ** 2)
    clear = SCUD_CAMERA_CLEAR_M + 0.5 * width
    alpha *= _smoothstep(clear, clear * 1.5, to_camera)
    return {"east_m": east, "north_m": north, "up_m": up, "width_m": width, "height_m": height,
            "alpha": alpha}


def scud_cards(seed: int, t: float, centre_enu_m: Sequence[float], camera_enu_m: Sequence[float],
               wind_en_mps: Sequence[float], band: Tuple[float, float],
               count: int = SCUD_CARDS) -> List[Dict[str, float]]:
    """Every card at run time t (:func:`scud_card` for index 0 .. count - 1)."""
    return [scud_card(seed, i, t, centre_enu_m, camera_enu_m, wind_en_mps, band) for i in range(count)]


def rain_haze_fog(rate_mmh: float, camera_above_fog_m: float, column_m: float,
                  fog_density: float, fog_falloff: float) -> Dict[str, float]:
    """The storm's rain haze on the height fog: ``falloff`` (the engine's
    FogHeightFalloff: density x 2^(-falloff / 10 x metres above the fog)) opened to
    halve once over the column, and ``density`` so the camera's height sees the
    rain's extinction. Neither is ever below / above the scene's own (density at
    least ``fog_density``, falloff at most ``fog_falloff``)."""
    column = max(float(column_m), RAIN_HAZE_MIN_COLUMN_M)
    falloff = min(float(fog_falloff), 10.0 * RAIN_HAZE_FALLOFF_COLUMN / column)
    beta_per_m = rain_extinction_per_km(rate_mmh) / 1000.0
    above = max(float(camera_above_fog_m), 0.0)
    density = beta_per_m / FOG_BETA_PER_DENSITY * 2.0 ** (falloff / 10.0 * above)
    return {"density": max(float(fog_density), density), "falloff": falloff}


def veil_shade(deck_above: bool) -> float:
    """The veil's and the scud's base-colour scale: VEIL_SHADE_UNDER_DECK under a drawn
    deck, VEIL_SHADE_OPEN otherwise."""
    return VEIL_SHADE_UNDER_DECK if deck_above else VEIL_SHADE_OPEN


def streak_cap_rad(max_streak_rad: float, pixel_angle_rad: float) -> float:
    """The beauty streak cap for a view: scaled by the pixel angle below the reference
    (a long lens), held above it."""
    return float(max_streak_rad) * min(1.0, float(pixel_angle_rad) / BEAUTY_REFERENCE_PIXEL_RAD)


def scud_tone(deck_above: bool) -> float:
    """The modulate scud's tone: SCUD_TONE_UNDER_DECK under a drawn deck, else SCUD_TONE_OPEN."""
    return SCUD_TONE_UNDER_DECK if deck_above else SCUD_TONE_OPEN


def veil_vary_scale(pixel_angle_rad: float, lens_cells: bool = True) -> float:
    """The curtain cells' scale (M_RainCurtain's VaryScale) for a view: the pixel angle
    over BEAUTY_REFERENCE_PIXEL_RAD below the reference (a long lens), VEIL_VARY_SCALE_MAX
    at it and wider, and always VEIL_VARY_SCALE_MAX with ``lens_cells`` off."""
    angle = float(pixel_angle_rad)
    if not lens_cells or angle <= 0.0:
        return VEIL_VARY_SCALE_MAX
    return min(VEIL_VARY_SCALE_MAX, angle / BEAUTY_REFERENCE_PIXEL_RAD)
