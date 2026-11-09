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
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from core.environment import sun as sun_model

#: The sidecar's version; the host refuses one it does not know.
HERO_LIGHTING_VERSION = 1
#: The commandlet token.
HERO_LIGHTING_PREFIX = "-hero-lighting="
#: The sidecar's file name, written beside ``beauty_look.json``.
SIDECAR_NAME = "hero_lighting.json"


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


def plan_sidecar(*, surface: str, sun_elevation_deg: float, horizontal_lux: Optional[float],
                 raining: bool, altitude_m: float = 0.0,
                 time_of_day_basis: Optional[str] = None) -> Dict[str, Any]:
    """The ``hero_lighting.json`` sidecar. Pure: same inputs, same bytes."""
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
    return {
        "hero_lighting_version": HERO_LIGHTING_VERSION,
        "ground": {
            "surface": str(surface),
            "albedo_rgb": list(albedo),
            "horizontal_lux": round(float(horizontal_lux), 1),
            "horizontal_lux_basis": lux_basis,
            "lower_hemisphere_luminance_rgb": luminance,
            "model": "Lambertian ground: L = albedo x E_horizontal / pi (cd/m2)",
        },
        "sun_elevation_deg": round(float(sun_elevation_deg), 4),
        "time_of_day_basis": time_of_day_basis,
        "uncalibrated": ["GROUND_ALBEDO_RGB", "OVERCAST_ILLUMINANCE_FRACTION"],
        "note": "VISUAL ONLY, beauty quality only (docs/visual/PROBE_LOG.md hero-lighting)",
    }


def write_sidecar(plan: Mapping[str, Any], path: Path) -> Path:
    """ASCII-only JSON (render.json echoes it; gotcha 13), written UTF-8."""
    path = Path(path)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


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
    plan = plan_sidecar(
        surface=str(getattr(getattr(spec, "surface", None), "value", "unspecified")),
        sun_elevation_deg=elevation,
        horizontal_lux=None if reference is None else float(reference),
        raining=raining, altitude_m=altitude,
        time_of_day_basis=None if tod is None else getattr(tod, "frm", None))
    return write_sidecar(plan, beauty_look.with_name(SIDECAR_NAME))


def flags_beside(beauty_look: Optional[Path]) -> List[str]:
    """``-hero-lighting=<abs path>`` when the sidecar sits beside the beauty
    look; empty otherwise (measure: no beauty look, no token)."""
    if beauty_look is None:
        return []
    sidecar = Path(beauty_look).with_name(SIDECAR_NAME)
    return [f"{HERO_LIGHTING_PREFIX}{sidecar.resolve()}"] if sidecar.is_file() else []
