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
#: The most one streak covers (never an opaque sheet). Hyperreal rain: this caps the
#: streak's MEAN coverage under the soft profile (generation 6 capped the profile itself
#: at 0.22, a flat bar). The per-drop brightness (0.4..1, mean 0.76 at variation 0.8)
#: now survives the cap, so the capped mean is 0.76 x this: 0.137, 0.62x generation
#: 6's bar; the Gaussian's centre of the brightest capped drop 2.27 x 1.31 x this: 0.53,
#: a bright core, see-through round it (rain_drop_twin.py; the test pins both).
BEAUTY_RAIN_MAX_COVERAGE = 0.18
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
# Hyperreal rain (2026-11-14; the still-"fake" rain of #06, #07, #09: "a flat grey screen
# with sparse, short, opaque streaks" / "scratches"). The causes, in the code:
# * the streak's length was the card camera's exposure on every frame (core/scenario/
#   camera.py: the documented daylight default 1/500 s -- 1.8 cm of streak for a 9 m/s
#   drop, 2-6 px: dashes, not streaks), while a beauty CLIP's camera is the 180-degree
#   shutter at the clip's frame rate (core/scene/beauty_look.py shutter_seconds: 1/48 s
#   at 24 fps; the host's MotionBlurAmount over MotionBlurTargetFPS). On a clip the
#   streaks are now exposed over that motion-blur shutter (beauty_rain_streak_shutter_s;
#   FFlightSimWeatherView::MotionBlurShutterSeconds, set by the commandlet from the
#   capture), so the length is fall speed x shutter / range: 13 cm for the median drop,
#   85 px at 2 m and 8 px at 20 m through the 54 deg lens, and the coverage D / (v t)
#   falls with it (a longer exposure is a fainter streak: Garg & Nayar). A beauty STILL
#   has motion blur OFF (beauty_look.SHUTTER_POLICY: one instant, the airframe tack
#   sharp), so its drops, like everything else in it, keep the view's shutter -- a still
#   never carries a 1/48 s streak over a sharp scene. The lightning's window and the
#   windscreen keep the view's shutter on every frame; the measure path is unchanged;
# * nothing defocused a near drop: a lens focused on the scene images a drop 3 m away as
#   the pupil's disc (f / N: BEAUTY_RAIN_SENSOR_MM / (2 tan(fov / 2)) / BEAUTY_RAIN_F_NUMBER,
#   the standard beauty lens's f/4 on the documented 36 mm sensor, beauty_look.LENSES).
#   M_RainDrops's Aperture is the smear the beauty draws (beauty_rain_defocus_cm: the
#   pupil x BEAUTY_RAIN_DEFOCUS_SHARE, the shader holding it to BEAUTY_RAIN_DEFOCUS_MAX_PX
#   pixels at the drop's range); the quad grows along the streak by it and across to the
#   greater of the soft width and the sharp width plus it, the same light spread over the
#   smear: near drops larger and softer, far ones thin -- the depth layering;
# * the coverage cap was applied after the soft profile, flattening every near streak to
#   a bar (rain_drop_opacity.hlsl: the cap is now on the mean, the profile over it);
# * the drop was a lit white surface, and under a storm deck the translucency lighting
#   volume carries the unshadowed sun: white lines over a dark scene. BEAUTY_RAIN_SCENE_LIT
#   of the drop's radiance is now the scene's luminance behind it (SceneLit,
#   drop_scene_tone.hlsl), the rest the lit sky term (Garg & Nayar: a drop is the mean of
#   its surroundings).
# Each is a no-op at its material default. CALIBRATED NUMERICALLY, not on a frame:
# core/scene/rain_drop_twin.py evaluates the shaders' arithmetic for generation 6 and
# this one, and tests/test_hyperreal_rain.py pins a near drop's mean coverage on a still
# within 0.5x..1.5x of generation 6 (the defocus share and the cap are the knobs), the
# streak wider and longer with its Gaussian core kept.
#: The beauty CLIP's streak exposure the numbers above are quoted at: the 180-degree
#: shutter at 24 fps (beauty_look.shutter_seconds(24)). The host takes the actual one
#: from the capture (MotionBlurAmount / MotionBlurTargetFPS); this is its reference.
BEAUTY_RAIN_CLIP_SHUTTER_S = 1.0 / 48.0
#: The beauty lens for the drops' defocus: f-number and sensor width (mm).
BEAUTY_RAIN_F_NUMBER = 4.0
BEAUTY_RAIN_SENSOR_MM = 36.0
#: The share of the geometric pupil the beauty smears a near drop over (1: the full
#: disc, a drop focused at infinity; the standard lens draws the scene with no depth of
#: field, so the full disc would make the rain the one defocused thing in a sharp frame,
#: and 0.35 keeps a near drop's mean coverage within 0.64x..1x of generation 6's).
BEAUTY_RAIN_DEFOCUS_SHARE = 0.25
#: The smear is at most this many pixels at the drop's range (a 250 mm lens's 6 cm pupil
#: would otherwise smear a 3 m drop over 60 px into nothing; the shader's RainDefocusMaxPx).
BEAUTY_RAIN_DEFOCUS_MAX_PX = 2.0
#: The share of a drop's radiance taken from the scene behind it (0: the lit surface only).
BEAUTY_RAIN_SCENE_LIT = 0.6
BEAUTY_RAIN_KEYS = ("density_share", "near_thin_m", "max_streak_rad", "max_coverage",
                    "depth_fade_m", "softness", "variation", "radiance",
                    "f_number", "sensor_mm", "defocus_share", "scene_lit")


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
            "variation": BEAUTY_RAIN_VARIATION, "radiance": BEAUTY_RAIN_RADIANCE,
            "f_number": BEAUTY_RAIN_F_NUMBER, "sensor_mm": BEAUTY_RAIN_SENSOR_MM,
            "defocus_share": BEAUTY_RAIN_DEFOCUS_SHARE, "scene_lit": BEAUTY_RAIN_SCENE_LIT}


def beauty_rain_streak_shutter_s(view_shutter_s: float, motion_blur_shutter_s: float = 0.0,
                                 cinematic: bool = False,
                                 cinematic_shutter_s: float = 1.0 / 15.0) -> float:
    """The exposure the beauty's streaks are drawn over (the C++ twin:
    FFlightSimWeather::Advance's StreakShutter). The cinematic style's stated
    1/15 s; else the capture's motion-blur shutter when it has one (a beauty
    CLIP: MotionBlurAmount / MotionBlurTargetFPS); else the view's shutter --
    a beauty STILL (motion blur off, beauty_look.SHUTTER_POLICY), a measure
    render, a card render. The lightning's window is always the view's."""
    if cinematic:
        return float(cinematic_shutter_s)
    blur = float(motion_blur_shutter_s)
    if blur > 0.0:
        return blur
    return max(float(view_shutter_s), 1.0e-5)


def beauty_rain_aperture_cm(horizontal_fov_deg: float, f_number: float = BEAUTY_RAIN_F_NUMBER,
                            sensor_mm: float = BEAUTY_RAIN_SENSOR_MM) -> float:
    """The beauty lens's entrance pupil (cm) for a view: the focal length the
    sensor and the horizontal field give (sensor / (2 tan(fov / 2))) over the
    f-number (the C++ twin: FFlightSimWeather::BeautyApertureCm). 0 for a
    pinhole (f_number 0) or no field."""
    import math

    fov = float(horizontal_fov_deg)
    if not (f_number > 0.0) or not (sensor_mm > 0.0) or not (0.0 < fov < 180.0):
        return 0.0
    focal_mm = float(sensor_mm) / (2.0 * math.tan(math.radians(fov) * 0.5))
    return focal_mm / float(f_number) / 10.0


def beauty_rain_defocus_cm(horizontal_fov_deg: float, f_number: float = BEAUTY_RAIN_F_NUMBER,
                           sensor_mm: float = BEAUTY_RAIN_SENSOR_MM,
                           share: float = BEAUTY_RAIN_DEFOCUS_SHARE) -> float:
    """M_RainDrops's Aperture for a view: the smear the beauty draws a near
    drop over, the pupil x ``share`` (the C++ twin: BeautyDefocusCm, set per
    frame in Advance). The shader holds it to BEAUTY_RAIN_DEFOCUS_MAX_PX pixels
    at the drop's range (rain_drop_twin.defocus_blur_cm)."""
    return beauty_rain_aperture_cm(horizontal_fov_deg, f_number, sensor_mm) * max(float(share), 0.0)


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
#: Lane C (2026-11-11): a cool condensation grey (round 5 read it as a tan cone).
BEAUTY_FUNNEL_COLOUR = (0.24, 0.245, 0.26)
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
#: Lane C: near-black, a rain-free base under a storm deck.
BEAUTY_WALL_CLOUD_COLOUR = (0.10, 0.105, 0.115)


def wall_cloud_omega_scale(wall_radii: float = WALL_RADII) -> float:
    """The wall cloud's spin as a share of the core's omega = v_max / r_core:
    the Rankine exterior's angular rate at r_wall = wall_radii x r_core is
    v_t / r_wall = v_max r_core / r_wall^2 = omega / wall_radii^2."""
    return 1.0 / (float(wall_radii) ** 2)
# -- visual round 6 -- end ---------------------------------------------------------------


# -- visual push lane C (2026-11-11): the tornado in BEAUTY -- begin --------------------
#
# Round 5 (f7232cc7) drew #10's tornado as a tan cone on a faceted octagonal base
# filling the frame. The scenario world's markers above are drawn on EVERY quality and
# measure must stay byte-identical, so the beauty refines them in place instead
# (FlightSimTornadoBeauty.cpp FFlightSimScenarioWorld::BuildBeautyTornado, called by the
# render commandlet under -quality=beauty only): a smooth, tapered, ragged funnel with a
# soft sheath, a broad wall-cloud underside whose rim thins into the storm deck (both
# depth-writing, M_TornadoFunnel generation 4: a torn clip of each vertex's coverage;
# the funnel's soft edge a translucent sheath, M_TornadoFunnelSoft), and camera-facing smoke puffs (Kenney's CC0 puffs, assets/looks/tornado/)
# for the swirling dust cloud at the ground and the scud under the wall cloud
# (translucent, beauty-only actors, as every cloud). The wind model is untouched.
# These are the C++'s constants, pinned by tests/test_tornado_look.py. UNCALIBRATED.
BEAUTY_TORNADO_FUNNEL = {
    "segments": 64, "rings": 96, "base_radii": 0.16, "taper_power": 2.6,
    "ground_coverage": 0.25, "contact_share": 0.12, "bend_radii": 0.12,
    "sheath_scale": 1.35, "sheath_pad_radii": 0.08, "sheath_coverage": 0.4,
}
#: The wall cloud's beauty profile: (height share of its depth, radius in core radii,
#: coverage, ragged), from the funnel's top outward, up into the deck and closed.
BEAUTY_TORNADO_WALL_PROFILE = (
    (0.00, 1.30, 1.00, 0.3), (0.04, 2.00, 1.00, 0.6), (0.10, 2.90, 1.00, 1.0),
    (0.18, 3.70, 0.90, 1.4), (0.28, 4.40, 0.60, 1.8), (0.40, 5.00, 0.30, 2.2),
    (0.55, 5.40, 0.00, 2.5), (0.75, 4.20, 0.00, 1.0), (1.00, 2.50, 1.00, 0.8),
    (1.06, 0.40, 1.00, 0.3),
)
BEAUTY_TORNADO_WALL_SEGMENTS = 64
#: The puffs: dust at the ground contact, debris up the funnel's foot, scud about the
#: wall cloud's base (counts, core-radii ranges, sizes in m, opacities, colours).
#: Round 7 fix: round 7 drew the dust as one beige blob wider than the funnel is
#: tall (36 puffs of 60-200 m out to 2.4 core radii). It is now a low, ragged, darker
#: WHIRL: 64 small puffs on 3 log-spiral arms (0.75 turn from 0.15 to 1.3 core radii,
#: jittered 0.18 radii), centres within 35 m of the ground, spun at the core rate.
BEAUTY_TORNADO_PUFFS = {
    "dust": {"count": 64, "arms": 3, "spiral_turns": 0.75, "jitter_radii": 0.18,
             "radii": (0.15, 1.3), "size_m": (22.0, 70.0),
             "top_m": 35.0, "opacity": (0.35, 0.70), "colour": (0.15, 0.125, 0.10)},
    "debris": {"count": 10, "radii": (0.2, 0.5), "share": (0.02, 0.06), "size_m": (18.0, 40.0)},
    "scud": {"count": 28, "radii": (1.6, 5.0), "band_m": 40.0, "size_m": (120.0, 260.0),
             "opacity": (0.50, 0.85), "colour": (0.09, 0.09, 0.10)},
}
#: The dust cloud turns at the Rankine exterior rate at this radius (omega / radii^2).
BEAUTY_TORNADO_DUST_SPIN_RADII = 1.0
#: The funnel's translucent sheath (M_TornadoFunnelSoft's FunnelColour): the funnel's grey.
BEAUTY_TORNADO_SHEATH_COLOUR = BEAUTY_FUNNEL_COLOUR
#: 2026-11-15 (hyperreal tornado-shape, repaired): the lane's first cut added a fourth puff
#: set, a 40-puff "debris ring" of 80-170 m puffs 1.8 wide for their height from 1.0 to 2.6
#: core radii, under its own key. At RCore 150 m that is a band about 1.09 km across and up
#: to 170 m tall around a 750 m funnel, about 5 puffs deep per line of sight at 0.30-0.55:
#: a near-opaque brown band hiding the whirl and the flipbook's rope foot, i.e. round 7's
#: "one blob wider than the funnel is tall" again at a larger scale. A ring OUTSIDE the
#: whirl cannot sit under the round-7 pin (the whirl already reaches 1.48 radii, 444 m
#: across, against the pin's 450 m), and one inside it is just more whirl, so the ring was
#: dropped: the puff sets are exactly these three, pinned by tests/test_tornado_look.py.
BEAUTY_TORNADO_PUFF_SETS = ("dust", "debris", "scud")
#: The flipbook card (-tornado-look=vdb): its tint (darker than the sheath grey: condensation
#: lit from inside the storm, between the sheath's grey and the wall cloud's near-black) and
#: its height as a share of the funnel's, the card's top up inside the wall cloud so that
#: M_TornadoFlipbook's top fade (scripts/ue_create_materials.py TORNADO_FLIPBOOK_TOP_FADE)
#: completes about the wall cloud's base: the funnel hangs DOWN from the deck.
BEAUTY_TORNADO_FLIPBOOK_COLOUR = (0.15, 0.155, 0.17)
BEAUTY_TORNADO_FLIPBOOK_HEIGHT_SHARE = 1.40
#: 2026-11-15 (hyperreal light lane tornado): -tornado-shade=funnel (the default), the
#: card shaded as a condensation funnel (M_TornadoFlipbook 3; FlightSimTornadoBeauty.cpp
#: BeautyFlipbookFunnel*, where each number's source is stated). colour: a cloud's two-stream
#: albedo (1 - g) tau / (2 + (1 - g) tau) at g 0.85, tau 7.5 (tornado_flipbook_albedo);
#: shade_floor, sheath_lift, contrast and the 100 m chord tuned by eye on the Mac look-dev
#: still of #10 (2026-11-15: 0.43 / 0.55 / 0.25 read paper-white against the storm base);
#: -tornado-shade=smoke keeps BEAUTY_TORNADO_FLIPBOOK_COLOUR and the material's generation-2
#: defaults. UNCALIBRATED.
BEAUTY_TORNADO_FLIPBOOK_FUNNEL = {
    "colour": (0.36, 0.36, 0.36), "shade_floor": 0.45, "alpha_lo": 0.15, "alpha_hi": 0.55,
    "sheath_lift": 0.10, "bands": 6.0, "contrast": 0.30, "corrugate": 0.06, "bottom_width": 0.35,
    "dust_share_max": 0.35,
}
BEAUTY_TORNADO_FLIPBOOK_SHADES = ("funnel", "smoke")


def tornado_flipbook_albedo(lwc_g_m3: float = 0.5, r_e_um: float = 10.0, path_m: float = 100.0,
                            g: float = 0.85) -> float:
    """A cloud's two-stream albedo (Bohren 1987): tau = 3 LWC L / (2 rho_w r_e) (Stephens
    1978), R = (1 - g) tau / (2 + (1 - g) tau)."""
    tau = 3.0 * (lwc_g_m3 * 1.0e-3) * path_m / (2.0 * 1000.0 * r_e_um * 1.0e-6)
    return (1.0 - g) * tau / (2.0 + (1.0 - g) * tau)


def dust_whirl_top_m() -> float:
    """The dust whirl's highest reach above the ground: its highest puff centre
    (0.25 x size + top_m) plus half the largest puff."""
    d = BEAUTY_TORNADO_PUFFS["dust"]
    return d["top_m"] + 0.75 * d["size_m"][1]


def flipbook_dust_share(card_height_m: float) -> float:
    """M_TornadoFlipbook 3's DustShare under -tornado-shade=funnel: the dust whirl's top
    over the card's height, at most dust_share_max (generation 2's fixed share)."""
    top = dust_whirl_top_m() / max(float(card_height_m), 1.0)
    return min(max(top, 0.0), BEAUTY_TORNADO_FLIPBOOK_FUNNEL["dust_share_max"])


def flipbook_dust_sort_offset_m(card_height_m: float, r_core_m: float) -> float:
    """How far nearer every dust puff sorts under -tornado-shade=funnel: the card's half
    height + the whirl's reach + its top, so no puff can sort behind the card's centre."""
    return 0.5 * float(card_height_m) + float(r_core_m) * dust_whirl_extent_radii() + dust_whirl_top_m()


def beauty_funnel_radius_radii(height_share: float) -> float:
    """The beauty funnel's radius in core radii at a share of its height (before
    the ragged noise): base + (FUNNEL_TOP_RADII - base) x F^taper."""
    f = min(max(float(height_share), 0.0), 1.0)
    c = BEAUTY_TORNADO_FUNNEL
    return c["base_radii"] + (FUNNEL_TOP_RADII - c["base_radii"]) * f ** c["taper_power"]


def beauty_funnel_coverage(height_share: float) -> float:
    """The core shell's coverage (UV0.x) at a share of its height: ground_coverage at
    the ground rising (smoothstep) to 1 at contact_share."""
    c = BEAUTY_TORNADO_FUNNEL
    t = min(max(float(height_share) / c["contact_share"], 0.0), 1.0)
    return c["ground_coverage"] + (1.0 - c["ground_coverage"]) * t * t * (3.0 - 2.0 * t)


def dust_whirl_extent_radii() -> float:
    """The dust whirl's widest reach from the axis, in core radii (the outermost
    arm radius plus its jitter): the whirl is this x 2 core radii across."""
    d = BEAUTY_TORNADO_PUFFS["dust"]
    return d["radii"][1] + d["jitter_radii"]


def dust_omega_scale() -> float:
    """The dust cloud's spin as a share of the core's omega."""
    return wall_cloud_omega_scale(BEAUTY_TORNADO_DUST_SPIN_RADII)


def flipbook_top_fade_end_share(top_fade: float, height_share: float = BEAUTY_TORNADO_FLIPBOOK_HEIGHT_SHARE,
                                funnel_top_share: float = FUNNEL_TOP_SHARE) -> float:
    """Where the flipbook card's top fade reaches full opacity, as a share of the
    tornado's top height: the card's top (height_share x the funnel's top) less the fade's
    span. At or above the funnel's top (the wall cloud's base) the cap dissolves inside the
    wall cloud and the funnel below it is drawn whole."""
    return height_share * funnel_top_share * (1.0 - float(top_fade))
# -- visual push lane C -- end ------------------------------------------------------------
