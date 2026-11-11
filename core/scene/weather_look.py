"""The weather look the renderer draws: one card block from the spec.

The engine side of the weather the physics already flies
(FlightSimVisualScene.cpp ``ApplyWeatherLook``). Absent-canonical: a spec
that states none of it writes no block and its card is unchanged. VISUAL
ONLY -- nothing here enters the flight model; every value is read from a
spec field the physics or the look already carries:

* ``surface`` -- the spec's ground-cover word (core/environment/surface.py
  SURFACE_CLASSES), or None when unspecified. On the flat scene the host
  draws the ground with ``M_Ground_<Surface>`` (procedural, or the fetched
  Poly Haven texture: scripts/fetch_ground_textures.py); a georeferenced
  scene keeps its imagery and ignores the word.
* ``storm`` -- ``thunderstorm`` / ``tornado`` from ``weather_event``, or
  None: storm clouds (a low, thick, dense layer when the look carries
  none), rain shafts under the cell and lightning flashes, all beauty-only.
* ``rain_rate_mmh`` -- the stated ``environment.precipitation_rate_mmh``;
  under a thunderstorm with no stated rate, STORM_RAIN_MMH (a stated
  visual default, recorded as such in ``rain_source``). Drives the lens
  drops and the shafts' density.
* ``wetness`` -- 0..1 for the ground materials' puddles and the terrain's
  existing Wetness scalar: ``min(1, rate / WET_AT_MMH)`` (a stated
  mapping: a surface is fully wet from 4 mm/h), or the rain block's
  stated runway condition (``wet`` 0.8, ``standing_water`` 1.0).
* ``ice_eta_max`` -- the icing block's resolved eta_max (0 = none); the
  host scales the aircraft's ice overlay by eta(t) / ICE_FULL_ETA per step.
* ``seed`` -- the spec's seed: the lightning schedule and the shafts'
  placement are deterministic in it (Gate 10-R).

Not claimed: any of these looks is measured against a photograph; the
lightning schedule is not a model of charge; the shafts are not a model
of the rain field; the ice overlay is not an accretion shape.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

CARD_KEYS = ("surface", "storm", "rain_rate_mmh", "rain_source", "wetness", "ice_eta_max",
             "seed")
#: The thunderstorm's visual rain rate when the spec states none (heavy rain).
STORM_RAIN_MMH = 40.0
#: A surface reads fully wet from this rate (stated).
WET_AT_MMH = 4.0
#: The runway words' wetness (the rain block, core/environment/rain.py).
RUNWAY_WETNESS = {"dry": 0.0, "wet": 0.8, "standing_water": 1.0}
#: eta at which the ice overlay is fully opaque (icing's "severe" word).
ICE_FULL_ETA = 0.30
STORMS = ("thunderstorm", "tornado")


def _surface(spec) -> Optional[str]:
    word = str(getattr(spec.surface, "value", "unspecified"))
    return None if word in ("", "unspecified", "None") else word


def _storm(spec) -> Optional[str]:
    event = str(getattr(spec.weather_event, "value", "none"))
    return event if event in STORMS else None


def _ice(spec) -> float:
    block = getattr(spec, "icing", None)
    if block is None or block.is_default():
        return 0.0
    return float(block.resolved()["eta_max"].value or 0.0)


def weather_look_card_block(spec) -> Optional[Dict[str, Any]]:
    """The ``weather_look`` block, keys in CARD_KEYS order, or None when
    the spec states no surface, storm, rain, wet runway or ice."""
    surface = _surface(spec)
    storm = _storm(spec)
    rate = spec.precipitation_rate_mmh.value
    source = "environment.precipitation_rate_mmh" if rate is not None else None
    if rate is None and storm == "thunderstorm":
        rate, source = STORM_RAIN_MMH, "thunderstorm visual default"
    wetness = 0.0 if rate is None else min(1.0, float(rate) / WET_AT_MMH)
    rain_block = getattr(spec, "rain", None)
    if rain_block is not None and not rain_block.is_default():
        word = rain_block.runway_condition.value
        if word in RUNWAY_WETNESS:
            wetness = max(wetness, RUNWAY_WETNESS[word])
    ice = _ice(spec)
    if surface is None and storm is None and rate is None and wetness == 0.0 and ice == 0.0:
        return None
    block = {"surface": surface, "storm": storm,
             "rain_rate_mmh": None if rate is None else float(rate), "rain_source": source,
             "wetness": wetness, "ice_eta_max": ice, "seed": int(spec.seed.value)}
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"weather_look card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    return block


# -- round-2b weather-fx (2026-11-09): the BEAUTY rain, shafts and funnel -- begin ----
#
# Round 0 (docs/visual/round_0/07, heavy rain from the tower) drew a full-frame
# wall of vertical streaks: every one of the card's PARTICLE_BUDGET drops in the
# 20 x 20 x 16 m box was drawn at every rate, each a 1/15 s cinematic streak (60 cm
# at 9 m/s), so a drop 1 m from the lens ran the frame's height, and the opacity
# weight x the web app's -rain-gain=4 x the beauty readability gain clamped each
# streak opaque. The beauty capture now draws the rain a camera shows
# (FlightSimWeather.cpp FFlightSimWeather::BeautyRainShape is the C++ twin;
# tests/test_weather_fx.py pins the two): the drawn count follows the rate, the
# streak's angular length is capped (a near drop cannot cross the frame), the
# drops near the lens are thinned, each streak's coverage is capped below opaque
# and fades with range. BEAUTY ONLY: FFlightSimWeather::ApplyBeautyRainReadability
# (FFlightSimWorldBeauty, -quality=beauty) is the only caller; M_RainDrops's
# defaults (Density 1, NearThin 0, MaxStreak 0, MaxCoverage 1, DepthFade 0) are
# the measure path's shader, value for value. Every number is UNCALIBRATED: set
# by probe render on the render machine (docs/visual/PROBE_LOG.md
# ## round-2b weather-fx).

#: Streaks drawn in the rain box per mm/h of rain (lane D: a 40 mm/h storm draws
#: 160 000 of the card's 262 144; 2 mm/h draws 8 000).
BEAUTY_RAIN_DROPS_PER_MMH = 4000.0
#: The fewest drawn, as a share of the card's particles (light rain still reads).
BEAUTY_RAIN_MIN_SHARE = 0.01
#: Drops nearer than this (m) are thinned by (range / this)^2: 1 m keeps 1 in 16.
BEAUTY_RAIN_NEAR_THIN_M = 4.0
#: The streak's longest angular length (rad) at the light and the heavy rate,
#: log-interpolated between and held outside (heavier rain, longer streaks).
BEAUTY_RAIN_STREAK_RAD_LIGHT = 0.012
BEAUTY_RAIN_STREAK_RAD_HEAVY = 0.045
BEAUTY_RAIN_LIGHT_MMH = 1.0
BEAUTY_RAIN_HEAVY_MMH = 50.0
#: The most one streak covers (never an opaque sheet).
BEAUTY_RAIN_MAX_COVERAGE = 0.22
#: Coverage x exp(-range / this): the far drops of the box fade into the rain's veil.
BEAUTY_RAIN_DEPTH_FADE_M = 12.0
# Lane D (2026-11-11, the round-4 review: "sparse, thin, straight white lines that
# read as scratches on the lens; real rain is dense, soft, varied in length and
# brightness, and lit by the background"). Three more beauty terms, each a no-op
# at its material default (M_RainDrops generation 6):
# * softness: the streak drawn (1 + softness) x wider with a Gaussian profile
#   across it and tapered ends (the profiles are normalised to a mean of 1, so a
#   soft streak carries the hard one's light, spread out: motion blur, not a line);
# * variation: each drop's streak length x 0.45..1.55 and its coverage x 0.4..1.0,
#   from a hash of its index (the drop's own: deterministic, Gate 10-R);
# * radiance: the drops' base colour x this (SkyRadianceScale): the translucency
#   volume lights a drop with the sun the deck shadows on the ground; a drop is the
#   mean of its surroundings (Garg & Nayar), under a deck a little above the
#   background, never a white line.
# With the softer, fainter streak the drawn count rises (1500 -> 4000 per mm/h:
# 40 000 at 10 mm/h, 160 000 at 40 mm/h of the card's 262 144) and one streak's
# cap falls (0.35 -> 0.22): many faint streaks, a sheet of rain, not scratches.
#: Streak softness (0: the measure path's hard quad).
BEAUTY_RAIN_SOFTNESS = 1.0
#: Per-drop length and brightness variation (0: every drop alike).
BEAUTY_RAIN_VARIATION = 0.8
#: The drops' radiance scale (SkyRadianceScale; 1: the measure path's).
BEAUTY_RAIN_RADIANCE = 0.7
BEAUTY_RAIN_KEYS = ("density_share", "near_thin_m", "max_streak_rad", "max_coverage",
                    "depth_fade_m", "softness", "variation", "radiance")


def beauty_rain_shape(rate_mmh: float, particles: int) -> Dict[str, float]:
    """The beauty rain's shape for the card's rain rate and drawn particle
    count, keys in BEAUTY_RAIN_KEYS order (the C++ twin's fields)."""
    import math

    rate = max(float(rate_mmh), 0.0)
    count = max(int(particles), 1)
    share = min(1.0, max(BEAUTY_RAIN_MIN_SHARE, BEAUTY_RAIN_DROPS_PER_MMH * rate / count))
    if rate <= BEAUTY_RAIN_LIGHT_MMH:
        t = 0.0
    elif rate >= BEAUTY_RAIN_HEAVY_MMH:
        t = 1.0
    else:
        t = math.log(rate / BEAUTY_RAIN_LIGHT_MMH) / math.log(BEAUTY_RAIN_HEAVY_MMH
                                                              / BEAUTY_RAIN_LIGHT_MMH)
    streak = BEAUTY_RAIN_STREAK_RAD_LIGHT + t * (BEAUTY_RAIN_STREAK_RAD_HEAVY
                                                 - BEAUTY_RAIN_STREAK_RAD_LIGHT)
    return {"density_share": share, "near_thin_m": BEAUTY_RAIN_NEAR_THIN_M,
            "max_streak_rad": streak, "max_coverage": BEAUTY_RAIN_MAX_COVERAGE,
            "depth_fade_m": BEAUTY_RAIN_DEPTH_FADE_M, "softness": BEAUTY_RAIN_SOFTNESS,
            "variation": BEAUTY_RAIN_VARIATION, "radiance": BEAUTY_RAIN_RADIANCE}


#: The weather look's rain shafts in beauty (M_RainShaft's ShaftSoftEdge and
#: ShaftLight; 0 and 1 are the measure path's hard, unlit-grey cones). Round 0's
#: #09 drew them as two hard-edged glowing cones under the 747. Under the storm
#: weather (the web app's default) they stand down for the storm cell
#: (SceneOptions.bSkipStormLook); this is the -weather-backend=off path.
BEAUTY_SHAFT_SOFT_EDGE = 1.0
BEAUTY_SHAFT_LIGHT = 0.35
#: The tornado funnel's beauty material (M_TornadoFunnel's FunnelColour): a
#: grey-brown condensation-and-debris albedo, linear. It replaces the engine's
#: default grid material in beauty only (no vertex colour: NEXT.md gotcha 26).
BEAUTY_FUNNEL_COLOUR = (0.30, 0.28, 0.26)
# -- round-2b weather-fx -- end ---------------------------------------------------------

# -- visual round 6 (2026-11-10): the funnel's shape and its wall cloud -- begin -------
#
# Round 4's #10 drew no tornado (the axis was out of the chase frame: tornado.py
# abeam_placement), and the funnel mesh itself ran from the ground to the wind
# model's top_m (1500 m) with no cloud over it: a 1.5 km condensation funnel
# standing in clear air. FlightSimScenarioWorld.cpp now draws, on EVERY render
# quality (the labels see the same meshes as the beauty: both are the scenario
# world's, not beauty-only actors):
#
# * the dust skirt at the ground (unchanged: 2.2 core radii, 5.5 % of top_m);
# * the condensation funnel from the ground to FUNNEL_TOP_SHARE x top_m (750 m
#   at the model's 1500 m: a low cloud base, the sense of a tornadic storm, and
#   low enough that the flyby's hazard-slot chase camera, 485 m from the axis
#   with a 68 deg vertical field (core/scenario/camera.py HAZARD_CHASE_*),
#   sees the ground contact, the whole funnel and the wall cloud's underside),
#   concave, narrow at the ground, FUNNEL_TOP_RADII core radii at its top, the
#   mesh spinning at the core's solid-body rate v_max / r_core (unchanged);
# * a WALL CLOUD: a ragged lowered lens from the funnel's top to
#   WALL_TOP_SHARE x top_m (1200 m), WALL_RADII core radii across (675 m: its
#   footprint covers the track, 150 m and more above a 600 m flyby), its own
#   actor ("TornadoWallCloud") spinning at the Rankine EXTERIOR rate at its
#   own radius, omega x (r_core / r_wall)^2 (0.9 deg/s at 4.5 radii: a wall
#   cloud turns slowly, the funnel fast; both from the one model).
#
# The wind model (core/environment/tornado.py) is untouched: top_m and
# fade_top_m still fade the WIND; these shares only say how much of that
# column condenses. The beauty gives both meshes M_TornadoFunnel
# (FlightSimWeatherLook.cpp ApplyBeautyWeatherLook): the funnel
# BEAUTY_FUNNEL_COLOUR, the wall cloud BEAUTY_WALL_CLOUD_COLOUR (darker: a
# rain-free base in its own shadow). UNCALIBRATED: set by probe render on the
# render machine (#10 first). tests/test_visual_round6.py pins the C++.
FUNNEL_TOP_SHARE = 0.5
FUNNEL_TOP_RADII = 1.3
WALL_TOP_SHARE = 0.8
WALL_RADII = 4.5
BEAUTY_WALL_CLOUD_COLOUR = (0.16, 0.16, 0.17)


def wall_cloud_omega_scale(wall_radii: float = WALL_RADII) -> float:
    """The wall cloud's spin as a share of the core's omega = v_max / r_core:
    the Rankine exterior's angular rate at r_wall = wall_radii x r_core is
    v_t / r_wall = v_max r_core / r_wall^2 = omega / wall_radii^2."""
    return 1.0 / (float(wall_radii) ** 2)
# -- visual round 6 -- end ---------------------------------------------------------------
