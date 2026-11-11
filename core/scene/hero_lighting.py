"""Hero lighting: a lighting director for every shot, and the ground the
sky light sees (hero-lighting lane, visual overhaul, 2026-11-09).

VISUAL ONLY. Physics never reads anything here, and the ``measure``
quality never receives the sidecar, so every Gate 6 render stands.

Two halves
----------
1. **The director** (:data:`INTENTS`, :func:`solve`). A cinematographer
   chooses where the sun sits RELATIVE TO THE CAMERA: a three-quarter
   backlight with a rim on the airframe at golden hour, a low cross-light
   for desert relief, a soft high overcast ahead for a wet specular sheen,
   the sun behind and above the cockpit for canopy glints. This module
   realises that choice with the only levers a real flight has -- the
   scenario's **time of day**, its **date** and the **flight heading** --
   and never with a second sun or a moved light. The time is solved with
   :func:`core.environment.sun.solar_position` (the NOAA equations the web
   app's render sun uses), so the sun the renderer draws is the sun solved
   for. The result is an ISO-dated UTC clock (``2026-03-20T17:42Z``) that
   both the render sun (webapp/runs.py ``sun_look``) and the sky plan
   (core/sky/plan.py) read identically, and an integer heading the offline
   compiler takes from ``heading NNN``. The date is carried on the clock,
   never as ``weather_date`` (which would switch on ERA5 winds: physics).

2. **The sidecar** (:func:`plan_sidecar`, ``-hero-lighting=``). What the
   engine side cannot know: the ground's albedo under the shot, turned
   into the luminance the sky light's lower hemisphere should have (a
   Lambertian ground: L = albedo x E_horizontal / pi). The engine-side
   light quality (true solar disc, VSM, contact shadows, the sky light's
   cloud AO and ground, Lumen hit lighting, light shafts, the sun disc) lives in
   FlightSimHeroLighting.cpp and is recorded in render.json
   ``hero_lighting``.

Every number marked UNCALIBRATED is a starting point chosen by reasoning;
docs/visual/PROBE_LOG.md "## hero-lighting" names the probe render that
sets it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from core.environment import sun as sun_model

#: The sidecar's version; the host refuses one it does not know.
HERO_LIGHTING_VERSION = 1
#: The commandlet token.
HERO_LIGHTING_PREFIX = "-hero-lighting="
#: The sidecar's file name, written beside ``beauty_look.json``.
SIDECAR_NAME = "hero_lighting.json"

#: Round 5 (2026-11-10) shade probes: beauty-only A/B switches the host
#: (FlightSimHeroLighting.cpp, the sky-light block) reads from the command
#: line or ``FLIGHTSIM_RENDER_SWITCHES`` (the channel -sky-capture-restore=
#: uses), recorded in render.json ``hero_lighting.sky_light.probes``. Each
#: name maps to its accepted words, or to ``None`` for a number >= 0. The
#: default of every one is the planned render, so a run that states none is
#: byte-identical to before.
#:
#: Why they exist: #02 "super bright" kept its blue shade (mean sRGB 96/102/157
#: -> 95/102/159) when round 4 made the stated fill neutral. Diffed plan to
#: plan, #01 and #02 differ only in the relit sun (6 -> 72 deg), the opened
#: exposure, the preset's four knob flags, the haze and this lane's fill; the
#: engine applies the sky light's colour per frame (View.SkyLightColor), so the
#: fill was never what coloured the shade. The shade's colour on the frame is
#: Rayleigh's (R/B 0.06-0.12 in every row of the JPEG) and the airframe beside
#: the camera is neutral: the shade is the atmosphere's in-scatter between
#: camera and ground with (near) no fill under it. These switches split "the
#: fill does not reach the ground" (red / off / cloud AO) from "the
#: in-scatter outruns it" (aerial perspective) on the render machine.
DIAGNOSTIC_SWITCHES: Dict[str, Optional[Tuple[str, ...]]] = {
    "sky-fill-probe": ("as-planned", "red", "off"),
    "sky-cloud-ao": ("auto", "on", "off"),
    "aerial-perspective-scale": None,
    # 2026-11-11, #10 green under the tornado's storm deck (STORM_LOWER_HEMISPHERE_SWITCHES).
    "storm-lower-hemisphere": ("neutral", "surface"),
    # 2026-11-11, #02 super bright's blue shade (STATED_FILL_FOG_SWITCHES).
    "stated-fill-fog": ("tint", "sky"),
}
#: Lane A (2026-11-11, "the planes are being too shadowed"): ``-sky-cloud-ao``
#: defaults to ``auto`` -- the sky light's cloud ambient occlusion is OFF when
#: the commandlet's one sky capture is taken at the aircraft with the
#: volumetric clouds in it (its defaults), because that cube already holds the
#: clouds overhead: under a deck its upper hemisphere is the deck's grey
#: underside, the deck's diffuse transmission, and the cloud AO multiplied the
#: fill again by the same deck's occlusion. With round 6's deck shadow on the
#: beam (core/scene/world_beauty.py deck_shadows_beam) nothing else reached the
#: airframe: round 5's #06 and #08 rendered black. ``on`` restores the old sky
#: light for an A/B. The host decides (FlightSimHeroLighting.cpp); this is the
#: rule's twin for tests and the probe log.
SKY_CLOUD_AO_DEFAULT = "auto"


def sky_cloud_ao_applies(switch: str = SKY_CLOUD_AO_DEFAULT, capture_clouds: int = 1,
                         capture_at: str = "aircraft") -> bool:
    """Whether the host leaves the sky light's cloud AO on (the twin of the
    -sky-cloud-ao= block): ``off`` never, ``on`` always, ``auto`` only when
    the capture does NOT already hold the clouds overhead."""
    if switch not in DIAGNOSTIC_SWITCHES["sky-cloud-ao"]:
        raise HeroLightingError("render.sky_fill_probe",
                                f"render.sky_fill_probe: -sky-cloud-ao={switch} is not auto, on or off")
    if switch == "off":
        return False
    if switch == "on":
        return True
    return not (int(capture_clouds) != 0 and capture_at == "aircraft")


class HeroLightingError(ValueError):
    """A lighting intent that cannot be realised as asked, refused by name."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint


# -- the director --------------------------------------------------------------


@dataclass(frozen=True)
class LightingIntent:
    """Where the sun should be, seen from the camera."""

    name: str
    #: Sun bearing minus the camera's yaw, degrees clockwise (0 = straight
    #: down the lens, +90 = from the camera's right, 180 = behind it).
    relative_azimuth_deg: float
    #: Wanted apparent sun elevation, degrees.
    elevation_deg: float
    #: "rising" (morning) or "setting" (evening): which crossing of that
    #: elevation the day gives.
    direction: str
    #: One sentence: the cinematographer's reason.
    why: str


#: The four contact-sheet looks. All UNCALIBRATED (probe hl-director: the
#: contact sheet at --step hero, each tile read for rim, relief, sheen and
#: glint against the V0 sheet).
INTENTS: Dict[str, LightingIntent] = {
    "golden_rim_backlight": LightingIntent(
        "golden_rim_backlight", 35.0, 6.0, "setting",
        "three-quarter backlight at golden hour: the sun 35 deg off the lens axis, just "
        "outside a chase lens's half-width, so the airframe's sun-side edge rims and the "
        "haze glows without the disc flaring the frame"),
    "desert_cross_relief": LightingIntent(
        "desert_cross_relief", 90.0, 16.0, "rising",
        "low morning cross-light from camera right: every butte throws a long shadow "
        "across the frame, which is what reads relief in a desert"),
    "storm_soft_sheen": LightingIntent(
        "storm_soft_sheen", 20.0, 28.0, "rising",
        "the bright patch of the overcast ahead of the camera: soft wrap on the airframe "
        "and a specular sheen off the wet canopy and wet ground toward the lens"),
    "cockpit_canopy_glint": LightingIntent(
        "cockpit_canopy_glint", 150.0, 35.0, "rising",
        "the sun behind and above the pilot's right shoulder: the coaming and the canopy "
        "arch catch it, and the glints stay on the glass rather than in the lens"),
}


@dataclass(frozen=True)
class SolvedLighting:
    intent: str
    #: The spec's environment.time_of_day value (ISO date + UTC clock).
    time_of_day: str
    #: The flight heading, degrees true (integer: ``heading NNN``).
    heading_deg: int
    date: str
    when_utc: str
    sun_elevation_deg: float
    sun_azimuth_deg: float
    relative_azimuth_deg: float
    wanted_elevation_deg: float
    wanted_relative_azimuth_deg: float
    elevation_error_deg: float
    relative_azimuth_error_deg: float
    camera_yaw_offset_deg: float
    basis: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _wrap180(degrees: float) -> float:
    return (float(degrees) + 180.0) % 360.0 - 180.0


def _elevation_at(latitude_deg: float, longitude_deg: float, when: datetime) -> float:
    return sun_model.solar_position(latitude_deg, longitude_deg, when)[0]


def solve_time(latitude_deg: float, longitude_deg: float, day: date,
               elevation_deg: float, direction: str) -> datetime:
    """The UTC instant on ``day`` when the APPARENT sun (refraction
    included, as the renderer's sun) crosses ``elevation_deg`` in
    ``direction``. Bisection on :func:`core.environment.sun.solar_position`
    between local solar noon and noon -/+ 12 h. Refuses by name when the
    sun never reaches that elevation there that day."""
    if direction not in ("rising", "setting"):
        raise HeroLightingError("hero_lighting.intent",
                                f"direction {direction!r} is not rising or setting")
    noon = sun_model._utc_from_solar_hours(day, longitude_deg, 12.0)
    # The day's highest sun: refine the solar-noon guess on a minute grid.
    best = max((noon + timedelta(minutes=m) for m in range(-30, 31)),
               key=lambda t: _elevation_at(latitude_deg, longitude_deg, t))
    peak = _elevation_at(latitude_deg, longitude_deg, best)
    far = best + timedelta(hours=-12.0 if direction == "rising" else 12.0)
    low = _elevation_at(latitude_deg, longitude_deg, far)
    if not low <= elevation_deg <= peak:
        raise HeroLightingError(
            "hero_lighting.unreachable",
            f"the sun never stands {elevation_deg:g} deg up ({direction}) at "
            f"{latitude_deg:.3f}, {longitude_deg:.3f} on {day.isoformat()}: it spans "
            f"{low:.1f} to {peak:.1f} deg that day. Choose another date or elevation.")
    a, b = (far, best) if direction == "rising" else (best, far)
    for _ in range(50):
        mid = a + (b - a) / 2
        above = _elevation_at(latitude_deg, longitude_deg, mid) >= elevation_deg
        if (direction == "rising") == above:
            b = mid
        else:
            a = mid
    return a + (b - a) / 2


def solve(intent: str, latitude_deg: float, longitude_deg: float, day: date,
          camera_yaw_offset_deg: float = 0.0) -> SolvedLighting:
    """Realise ``intent`` at a place and date: the time from the wanted
    elevation, then the heading that puts the sun at the wanted bearing
    relative to the camera (camera yaw = heading + ``camera_yaw_offset_deg``;
    0 for the chase and cockpit presets, which look along the track).

    The clock is rounded to the minute and the heading to the degree, and
    the sun is then RE-SOLVED with :func:`core.environment.sun.resolve` on
    exactly the string the render will read, so the recorded sun is the
    rendered sun and the residuals are honest."""
    row = INTENTS.get(intent)
    if row is None:
        raise HeroLightingError("hero_lighting.intent",
                                f"lighting intent {intent!r} is not one of {sorted(INTENTS)}")
    when = solve_time(latitude_deg, longitude_deg, day, row.elevation_deg, row.direction)
    when = (when + timedelta(seconds=30)).replace(second=0, microsecond=0)
    clock = f"{when.hour:02d}:{when.minute:02d}Z"
    placed = sun_model.resolve(clock, latitude_deg, longitude_deg, when.date())
    sun_model.require_renderable(placed)
    camera_yaw = (placed.azimuth_deg - row.relative_azimuth_deg) % 360.0
    heading = int(round((camera_yaw - camera_yaw_offset_deg) % 360.0)) % 360
    relative = _wrap180(placed.azimuth_deg - (heading + camera_yaw_offset_deg))
    time_of_day = f"{when.date().isoformat()}T{clock}"
    return SolvedLighting(
        intent=row.name, time_of_day=time_of_day, heading_deg=heading,
        date=when.date().isoformat(), when_utc=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        sun_elevation_deg=round(placed.elevation_deg, 3),
        sun_azimuth_deg=round(placed.azimuth_deg, 3),
        relative_azimuth_deg=round(relative, 3),
        wanted_elevation_deg=row.elevation_deg,
        wanted_relative_azimuth_deg=row.relative_azimuth_deg,
        elevation_error_deg=round(placed.elevation_deg - row.elevation_deg, 3),
        relative_azimuth_error_deg=round(_wrap180(relative - row.relative_azimuth_deg), 3),
        camera_yaw_offset_deg=float(camera_yaw_offset_deg),
        basis=(f"hero lighting director: {row.name} -- {row.why}. Realised by the time of "
               f"day ({time_of_day}, sun {placed.elevation_deg:.1f} deg up at "
               f"{placed.azimuth_deg:.1f} deg, NOAA solar position) and the heading "
               f"({heading} deg); no second sun, no moved light"))


#: The date prefix core.sky.plan reads off a clock value.
_DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})[tT]")


def scene_day(time_of_day: Any) -> date:
    """The date a compiled spec's ``time_of_day`` already carries (the
    environment presets: ``2026-07-15T12:00``), else the sun module's own
    default date (the equinox, what an undated render already uses), so
    the director never changes the season it lights."""
    match = _DATED.match(str(time_of_day or "").strip())
    if match:
        return date.fromisoformat(match.group(1))
    return sun_model.DEFAULT_DATE


#: A compass flight phrase the offline compiler reads as the heading.
_FLIGHT_DIRECTION = re.compile(
    r",?\s*\b(?:flying|heading|headed)\s+(?:due\s+)?(?:north|south|east|west)"
    r"(?:[- ]?(?:east|west))?\b|,?\s*\bheading\s*\d{1,3}\b", re.I)


def with_heading(prompt: str, heading_deg: int) -> str:
    """``prompt`` flying ``heading_deg``: any compass/heading phrase is
    removed and ``heading NNN`` (the compiler's first-priority form) put
    before the duration clause."""
    text = _FLIGHT_DIRECTION.sub("", str(prompt)).strip()
    text = re.sub(r",\s*,", ",", text)
    phrase = f"heading {int(heading_deg) % 360:03d}"
    match = re.search(r",?\s+for\s+\d", text)
    if match:
        head = text[:match.start()].rstrip().rstrip(",")
        tail = text[match.start():].lstrip(",")
        return f"{head}, {phrase}{tail}"
    return f"{text.rstrip(',')}, {phrase}"


def apply_to_spec(spec_dict: Dict[str, Any], solved: SolvedLighting) -> Dict[str, Any]:
    """The compiled spec dict with the solved time of day (a USER value: the
    director stated it). Only ``environment.time_of_day`` changes; the
    heading travels in the prompt so the compiler and planners see it."""
    out = json.loads(json.dumps(spec_dict))
    out.setdefault("environment", {})["time_of_day"] = {
        "value": solved.time_of_day, "source": "user", "from": solved.basis}
    return out


# -- the ground the sky light sees ----------------------------------------------

#: Broadband ground albedo, linear RGB, per surface class (core.environment.
#: surface.SURFACE_CLASSES plus the alpine default). UNCALIBRATED (probe
#: hl-ground: the airframe belly's luminance over each ground vs the tiles'
#: own mean linear colour under the camera, read off a -linear pass).
GROUND_ALBEDO_RGB: Dict[str, Tuple[float, float, float]] = {
    "desert": (0.36, 0.25, 0.17),      # Colorado Plateau sandstone
    "forest": (0.05, 0.08, 0.04),      # conifer canopy
    "grassland": (0.10, 0.14, 0.06),
    "city": (0.13, 0.13, 0.13),
    "ocean": (0.04, 0.05, 0.06),
    "unspecified": (0.18, 0.17, 0.15),  # alpine rock, scree and meadow
}
#: Horizontal illuminance under heavy overcast as a fraction of clear sky.
#: UNCALIBRATED (probe hl-overcast: shot c, an incident reading of the
#: tiles under the storm deck from the -calibration quad).
OVERCAST_ILLUMINANCE_FRACTION = 0.25

#: 2026-11-11, #10 ("c172 near a tornado") green over the whole frame: the sky
#: light's lower hemisphere under a STORM deck. The commandlet runs this lane
#: AFTER the world lane (FlightSimRenderCommandlet.cpp: WorldBeauty.Build, then
#: FFlightSimHeroLighting::Apply), so the world lane's storm_deck_light black
#: lower hemisphere was always overwritten by this sidecar's ground: the
#: grassland row (0.10, 0.14, 0.06), G/B 2.3, at albedo x E x 0.25 / pi --
#: about 950 cd/m2 of green, brighter than the deck underside the capture sees
#: above. Every surface and medium that takes the sky light's SH (the volumetric
#: fog, the deck's ambient, the funnel's sides) went green, while the ground,
#: facing up, stayed its own red-brown (round 44: sky 86/99/87, funnel 22/33/23,
#: ground 8/5/5). Under a storm deck the ground keeps its luminance and loses
#: its hue: a wet ground under a storm returns little colour of its own (lane D).
#: ``-storm-lower-hemisphere=surface`` (command line or FLIGHTSIM_RENDER_SWITCHES)
#: puts the surface's colour back, for the A/B. Beauty only (the sidecar is).
STORM_LOWER_HEMISPHERE_SWITCHES: Tuple[str, ...] = ("neutral", "surface")
STORM_LOWER_HEMISPHERE_DEFAULT = "neutral"
#: Rec. 709 luminance weights (linear RGB): the grey that keeps the ground's luminance.
REC709_LUMA: Tuple[float, float, float] = (0.2126, 0.7152, 0.0722)

#: 2026-11-11, #02 super bright's blue cast, still there after the neutral fill
#: (round 4), with the sky light and the aerial perspective excluded by the
#: round-5 probes: the remaining in-scatter is the HEIGHT FOG's, whose colour is
#: the SkyAtmosphere's ambient (FlightSimSky.cpp: SkyAtmosphereAmbientContribution
#: ColorScale white, FogInscatteringColor black), the clear sky at the relit
#: 72 deg sun (R/B 0.25 on the model), x1.6 by the sun knob, under an exposure
#: opened 1.7 stops over the physical meter. Round 44 measures an additive blue
#: veil on every luma band (sRGB B - R: +67 in the shade, +70 and +49 in the
#: midtones, -7 in the highlights; #01: +20, +8, -17, -46). Under a STATED fill
#: the fog's ambient takes the colour the fill takes (stated_fill_tint's
#: ``color_linear_rgb``): the haze is the fill's light, not more blue sky.
#: ``-stated-fill-fog=sky`` keeps the sky's hue, for the A/B. Clear world,
#: stated fill and beauty only.
STATED_FILL_FOG_SWITCHES: Tuple[str, ...] = ("tint", "sky")
STATED_FILL_FOG_DEFAULT = "tint"


def neutral_ground_luminance(rgb: Sequence[float]) -> List[float]:
    """A grey of the same Rec. 709 luminance as ``rgb`` (cd/m2, rounded as the sidecar's)."""
    y = sum(w * float(c) for w, c in zip(REC709_LUMA, rgb))
    return [round(y, 3)] * 3

# -- the stated fill's colour (round 3, 2026-11-10) -------------------------------

#: The share of the clear sky's blue the sky light loses when a lighting block
#: STATES the fill (a preset's or the user's ``sky_fill``), in log space:
#: tint_c = (Y / s_c) ** share, s the model's clear-sky irradiance colour at the
#: sun (core.xplane.atmosphere.sky_irradiance), Y its luminance. 0 keeps the
#: captured sky's colour, 1 makes the fill grey.
#:
#: Why: round 1's #02 ("super bright" over #01's golden-hour Yosemite) rendered a
#: heavy indigo cast, its shadows at sRGB 14/26/107 against #01's 41/30/51. The
#: preset moves the physical sky's sun from 6 to 72 deg, where the model's sky
#: irradiance is 0.245/0.497/1.0 (R/B 0.25; at 6 deg 0.45), and multiplies that
#: capture by its fill x1.35 and the no-Lumen fallback's x1.6 (2.16 in all) with
#: no GI bounce to warm it: every shadowed wall is lit by pure blue sky. On the
#: measure path the presets were chosen under the X-Plane ambient colour, which
#: is compensated for the engine's sky (webapp.runs xplane_lighting_flags); round
#: 2b sends it white in beauty and the physical sky never sends it, so a stated
#: fill multiplied the raw blue. This restores the fill a preset asked for as a
#: fill, not as more blue sky. The fill's luminance is kept (``intensity_scale``),
#: so only its colour moves; the lower hemisphere (the ground) warms by the same
#: tint. UNCALIBRATED: probe hl-fill, #02 against #01, the cliff shadows' R/B.
#:
#: Round 4 (2026-11-10): 0.75 -> 1.0, and the ground no longer takes the tint.
#: Round 2's #02 (6816852c, the round-3 tint in) still rendered blue/violet:
#: mean sRGB 96/102/157, its luma bands (scene-linear after the filmic curve)
#: R/B 0.18 in the shade, 0.4 in the midtones and 0.85 only in the sunlit
#: highlights, flat from the top row to the bottom (so not the aerial
#: perspective, which grows with distance). The highlights are the sun; all the
#: rest is the fill, and on D3D11 SM5 (no Lumen) the fill is all a surface the
#: 72 deg sun grazes or misses gets. 0.75 left that fill blue BY DESIGN (R/B 0.71
#: on the model; round 3's test pinned it below 1, "still a sky fill"), and the
#: fill is 1.35 x 1.66 x 1.6 = 3.6 x the captured noon sky. A fill a preset
#: STATES is the photographer's fill (lighting.py: "how bright the shadows
#: are"): neutral daylight. Share 1 makes it grey on the model, luminance kept.
#: The host's light colour multiplies BOTH hemispheres of the capture, so at
#: share 1 (tint 1.0/0.50/0.25) the hero ground (lower hemisphere) would turn
#: orange-red; :func:`plan_sidecar` now divides the ground's luminance by the
#: tint and its luminance factor, so the ground bounce keeps its albedo colour.
STATED_FILL_NEUTRAL_SHARE = 1.0
#: Rec. 709 luminance weights (linear RGB).
_LUMA_709 = (0.2126, 0.7152, 0.0722)


def _sky_fill_colour(sun_elevation_deg: float, altitude_m: float) -> Tuple[float, float, float]:
    """The model's clear-sky irradiance colour at this sun (linear RGB over the
    sun's top-of-atmosphere spectrum, peak 1); cached by the rounded inputs."""
    return _sky_fill_colour_cached(round(float(sun_elevation_deg), 1),
                                   round(max(float(altitude_m), 0.0), -1))


@lru_cache(maxsize=64)
def _sky_fill_colour_cached(elevation: float, altitude: float) -> Tuple[float, float, float]:
    import numpy as np

    from core.xplane.atmosphere import MODEL_SUN_ELEVATION_FLOOR_DEG, Atmosphere, sky_irradiance

    atm = Atmosphere()
    s = sky_irradiance(atm, altitude, max(elevation, MODEL_SUN_ELEVATION_FLOOR_DEG), 0.0)
    s = np.asarray(s, dtype=float) / np.asarray(atm.solar_irradiance, dtype=float)
    peak = float(np.max(s))
    return tuple(float(v) / peak for v in s) if peak > 0.0 else (1.0, 1.0, 1.0)


def stated_fill_tint(sun_elevation_deg: float, altitude_m: float = 0.0,
                     share: float = STATED_FILL_NEUTRAL_SHARE) -> Dict[str, Any]:
    """The sky light's colour and intensity factor for a STATED fill: the
    model sky's colour moved ``share`` of the way to grey in log space, the
    colour normalised to peak 1 (the host's 8-bit light colour) and
    ``intensity_scale`` restoring the fill's luminance:
    Y(sky x colour) x intensity_scale == Y(sky)."""
    sky = _sky_fill_colour(sun_elevation_deg, altitude_m)
    y = sum(w * c for w, c in zip(_LUMA_709, sky))
    raw = [(y / max(c, 1e-6)) ** float(share) for c in sky]
    peak = max(raw)
    # Round 4: the colour the host's light actually holds (SetLightColor keeps
    # 8-bit sRGB), so the luminance factor and the ground's compensation are
    # computed on what is drawn, not on a value the light cannot store.
    colour = [srgb8_stored(c / peak) for c in raw]
    y_tinted = sum(w * c * t for w, c, t in zip(_LUMA_709, sky, colour))
    return {
        "color_linear_rgb": [round(c, 6) for c in colour],
        "intensity_scale": round(y / y_tinted, 6),
        "model_sky_rgb": [round(c, 6) for c in sky],
        "neutral_share": float(share),
        "basis": ("a stated fill (the lighting block's sky_fill): the model's clear-sky "
                  "irradiance colour (core.xplane.atmosphere.sky_irradiance) moved "
                  f"{float(share):g} of the way to grey in log space, its luminance kept "
                  "(round 3; neutral since round 4, UNCALIBRATED)"),
    }


def srgb8_stored(linear: float) -> float:
    """``linear`` (0..1) as a light colour channel holds it: UE 5.7's
    FLinearColor::ToFColor(true) (sRGB encode, floor of x 255.999) read back
    by FLinearColor(FColor) (the sRGB decode)."""
    v = min(max(float(linear), 0.0), 1.0)
    enc = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1.0 / 2.4) - 0.055
    code = min(int(math.floor(enc * 255.999)), 255)
    e = code / 255.0
    return e / 12.92 if e <= 0.04045 else ((e + 0.055) / 1.055) ** 2.4


def plan_sidecar(*, surface: str, sun_elevation_deg: float, horizontal_lux: Optional[float],
                 raining: bool, altitude_m: float = 0.0,
                 time_of_day_basis: Optional[str] = None,
                 stated_fill: bool = False, storm_deck: bool = False) -> Dict[str, Any]:
    """The ``hero_lighting.json`` sidecar. Pure: same inputs, same bytes.
    ``stated_fill``: the lighting block states the sky fill (a preset or the
    user); a clear sky's light then takes :func:`stated_fill_tint` (round 3).
    Under rain or a deck the sky is grey already and nothing is added.
    ``storm_deck``: the world is the storm preset (a drawn storm deck); the
    ground's lower hemisphere is then its luminance as a grey
    (:data:`STORM_LOWER_HEMISPHERE_SWITCHES`), the surface's colour kept
    beside it for the host's ``-storm-lower-hemisphere=surface``."""
    from core.scene.beauty_look import clear_sky_horizontal_lux

    albedo = GROUND_ALBEDO_RGB.get(str(surface), GROUND_ALBEDO_RGB["unspecified"])
    if horizontal_lux is None:
        horizontal_lux = clear_sky_horizontal_lux(float(sun_elevation_deg), float(altitude_m))
        lux_basis = "modelled clear-sky global horizontal (core.scene.beauty_look)"
    else:
        lux_basis = "the beauty look's meter reference (beauty_look.json)"
    if raining:
        horizontal_lux *= OVERCAST_ILLUMINANCE_FRACTION
        lux_basis += f" x {OVERCAST_ILLUMINANCE_FRACTION:g} under rain (UNCALIBRATED)"
    luminance = [round(a * float(horizontal_lux) / math.pi, 3) for a in albedo]
    extra: Dict[str, Any] = {}
    ground_extra: Dict[str, Any] = {}
    if stated_fill and not raining and float(sun_elevation_deg) > 0.0:
        fill = stated_fill_tint(float(sun_elevation_deg), float(altitude_m))
        extra["sky_light"] = fill
        # Round 4: the light's colour and its luminance factor multiply the
        # whole capture, the ground's lower hemisphere included. Divided out
        # here, so the ground bounce stays albedo x E / pi (no orange ground
        # under a neutral fill); the host reads this field as before.
        scale = float(fill["intensity_scale"])
        ground_extra = {
            "lower_hemisphere_luminance_rgb_drawn": luminance,
            "lower_hemisphere_fill_compensation": (
                "divided by the stated fill's colour and intensity_scale (sky_light), which "
                "multiply the lower hemisphere too: the drawn ground is albedo x E / pi"),
        }
        luminance = [round(v / (c * scale), 3)
                     for v, c in zip(luminance, fill["color_linear_rgb"])]
    if storm_deck:
        ground_extra["lower_hemisphere_luminance_rgb_surface"] = luminance
        ground_extra["lower_hemisphere_storm_deck"] = (
            "neutral: the surface's luminance as a grey under a storm deck (#10 green, "
            "2026-11-11); -storm-lower-hemisphere=surface draws "
            "lower_hemisphere_luminance_rgb_surface")
        luminance = neutral_ground_luminance(luminance)
    return {
        "hero_lighting_version": HERO_LIGHTING_VERSION,
        "ground": {
            "surface": str(surface),
            "albedo_rgb": list(albedo),
            "horizontal_lux": round(float(horizontal_lux), 1),
            "horizontal_lux_basis": lux_basis,
            "lower_hemisphere_luminance_rgb": luminance,
            "model": "Lambertian ground: L = albedo x E_horizontal / pi (cd/m2)",
            **ground_extra,
        },
        **extra,
        "sun_elevation_deg": round(float(sun_elevation_deg), 4),
        "time_of_day_basis": time_of_day_basis,
        "uncalibrated": ["GROUND_ALBEDO_RGB", "OVERCAST_ILLUMINANCE_FRACTION"]
                        + (["STATED_FILL_NEUTRAL_SHARE"] if extra else []),
        "note": "VISUAL ONLY, beauty quality only (docs/visual/PROBE_LOG.md hero-lighting)",
    }


def write_sidecar(plan: Mapping[str, Any], path: Path) -> Path:
    """ASCII-only JSON (render.json echoes it; gotcha 13), written UTF-8."""
    path = Path(path)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def storm_deck_look(look: Mapping[str, Any]) -> bool:
    """Whether the beauty look (beauty_look.json) is the storm world: its world
    preset is ``storm`` (the world lane's storm deck), or no card named a world
    and the grade is ``storm`` from a storm event (a tornado, a thunderstorm)."""
    # Round 55: a tornado card's beauty_look.json says world_preset "clear"
    # with grade "storm" from the weather event, while the world lane draws
    # the storm deck from the same storm word -- so a storm event wins over
    # the preset, or the green ground fill stays under the deck (#10).
    if str(look.get("world_preset") or "") == "storm":
        return True
    return look.get("grade") == "storm" and str(look.get("grade_basis", "")).startswith("weather event")


def write_sidecar_beside(spec: Any, beauty_look: Optional[Path]) -> Optional[Path]:
    """The web app's hook: write ``hero_lighting.json`` beside the run's
    ``beauty_look.json`` (beauty only: None in, None out, so a measure
    render's command is untouched)."""
    if beauty_look is None:
        return None
    beauty_look = Path(beauty_look)
    look = json.loads(beauty_look.read_text(encoding="utf-8"))
    elevation = float(look.get("sun_elevation_deg", 0.0))
    reference = (look.get("exposure") or {}).get("meter_horizontal_lux_reference")
    rate = getattr(getattr(spec, "precipitation_rate_mmh", None), "value", None)
    try:
        raining = float(rate) > 0.0
    except (TypeError, ValueError):
        raining = False
    raining = raining or look.get("grade") == "storm"
    # The beauty look's world preset (the world lane's selector): an overcast
    # deck without rain shadows the ground as well (core/scene/beauty_look.py
    # DECK_PRESETS meters the same fraction).
    from core.scene.beauty_look import DECK_PRESETS

    raining = raining or look.get("world_preset") in DECK_PRESETS
    altitude = getattr(getattr(spec, "terrain_elevation", None), "value", 0.0)
    try:
        altitude = float(altitude or 0.0)
    except (TypeError, ValueError):
        altitude = 0.0
    tod = getattr(spec, "time_of_day", None)
    # Round 3: a fill the lighting block states (a preset's or the user's
    # sky_fill) is lit as a fill, not as more blue sky (stated_fill_tint).
    stated_fill = False
    block = getattr(spec, "lighting", None)
    if block is not None:
        from core.scene import lighting as lighting_block

        stated_fill = lighting_block.effective_values(
            lighting_block.stated_values(block)).get("sky_fill") is not None
    plan = plan_sidecar(
        surface=str(getattr(getattr(spec, "surface", None), "value", "unspecified")),
        sun_elevation_deg=elevation,
        horizontal_lux=None if reference is None else float(reference),
        raining=raining, altitude_m=altitude,
        time_of_day_basis=None if tod is None else getattr(tod, "frm", None),
        stated_fill=stated_fill, storm_deck=storm_deck_look(look))
    return write_sidecar(plan, beauty_look.with_name(SIDECAR_NAME))


def with_stated_fill_scale(look: Optional[Mapping[str, Any]],
                           beauty_look: Optional[Path]) -> Optional[Mapping[str, Any]]:
    """``look`` with its ``sky_light_scale`` multiplied by the hero sidecar's
    stated-fill ``intensity_scale`` (round 3: the host sets only the fill's
    colour, :func:`stated_fill_tint`; its luminance factor rides the lighting
    block's own -sky-light-scale=). The same ``look`` object when there is no
    sidecar (measure), no ``sky_light`` block or no stated scale, so every
    other command is unchanged."""
    if beauty_look is None or not look or look.get("sky_light_scale") is None:
        return look
    sidecar = Path(beauty_look).with_name(SIDECAR_NAME)
    if not sidecar.is_file():
        return look
    fill = json.loads(sidecar.read_text(encoding="utf-8")).get("sky_light")
    if not fill:
        return look
    return {**look, "sky_light_scale": round(float(look["sky_light_scale"])
                                             * float(fill["intensity_scale"]), 6)}


def flags_beside(beauty_look: Optional[Path]) -> List[str]:
    """``-hero-lighting=<abs path>`` when the sidecar sits beside the beauty
    look; empty otherwise (measure: no beauty look, no token)."""
    if beauty_look is None:
        return []
    sidecar = Path(beauty_look).with_name(SIDECAR_NAME)
    return [f"{HERO_LIGHTING_PREFIX}{sidecar.resolve()}"] if sidecar.is_file() else []


def parse_diagnostic_switches(text: str) -> Dict[str, Any]:
    """The round-5 shade probes stated in ``text`` (a command line and/or the
    FLIGHTSIM_RENDER_SWITCHES value), the way the host parses them: each of
    :data:`DIAGNOSTIC_SWITCHES` by its first ``-name=value`` token, a word
    checked against its accepted words, a number checked finite and >= 0.
    Unstated switches are left out (the host renders as planned).
    HeroLightingError names a value the host would refuse by name
    (``render.sky_fill_probe``)."""
    out: Dict[str, Any] = {}
    for name, words in DIAGNOSTIC_SWITCHES.items():
        match = re.search(rf"(?:^|\s)-?{re.escape(name)}=(\S*)", text or "")
        if match is None:
            continue
        value = match.group(1)
        if words is not None:
            if value not in words:
                raise HeroLightingError(
                    "render.sky_fill_probe",
                    f"render.sky_fill_probe: -{name}={value} is not one of {', '.join(words)}")
            out[name] = value
            continue
        try:
            number = float(value)
        except ValueError:
            number = math.nan
        if not math.isfinite(number) or number < 0.0:
            raise HeroLightingError("render.sky_fill_probe",
                                    f"render.sky_fill_probe: -{name}={value} is not a number >= 0")
        out[name] = number
    return out
