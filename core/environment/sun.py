"""Sun position from place, date and time of day (visual-fidelity plan V1).

Replaces the hand-picked render looks (``TIME_OF_DAY`` in
experiments/showcase_matrix.py: "noon" is elevation 50 deg, azimuth 180
everywhere on Earth, every day of the year) with the geometry the scene
actually has. The render commandlet already takes ``-sun-elev`` and
``-sun-azim``; this module only decides the numbers, so the UE side is
unchanged.

Algorithm, honestly
-------------------
The NOAA Solar Calculator equations (Meeus, *Astronomical Algorithms*,
as published by NOAA ESRL/GML): geometric mean longitude and anomaly,
equation of centre, apparent longitude, obliquity, declination, equation
of time, then hour angle -> zenith/azimuth, plus NOAA's piecewise
atmospheric-refraction correction. Stated accuracy is about 0.01 deg in
the years 1800-2100, far inside what a rendered shadow can show. The
tests pin it against pvlib's NREL SPA implementation (Reda & Andreas
2004) at reference instants.

Time of day, honestly
---------------------
A clock time with no zone ("14:30", "5 pm") is **local apparent solar
time** -- 12:00 is the sun at its highest, whatever the civil clock says
there. Civil time zones need a time-zone boundary database this project
does not carry, and guessing one from longitude is wrong by hours in
places (Spain, western China). ``14:30Z`` / ``14:30 UTC`` is exact UTC.
Named times are sun geometry, not clock readings, so they mean the same
light everywhere: "dawn" is the sun 8 deg up and rising (the elevation
the probe-calibrated dawn look was measured at), "golden hour" 8 deg up
and setting. Every resolution says which rule it used, and the webapp
records that sentence with the run.

Night is not rendered: the scene has no moon, stars or night exposure
yet, so a sun below :data:`RENDER_FLOOR_DEG` is refused by name
(``sun.below_render_floor``) rather than rendered as something it is not.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

#: Date used when the spec states none: the March equinox, whose
#: declination (~0 deg) is the mid-year value. Recorded as a default.
DEFAULT_DATE = date(2026, 3, 20)

#: Lowest sun the renderer is asked to show. Below it the scene would
#: need twilight/night treatment (moon, stars, night exposure) it does
#: not have.
RENDER_FLOOR_DEG = 2.0

#: Named times defined by sun ELEVATION, with the direction of travel.
#: 8 deg is where the probe-calibrated "dawn" look was measured.
ELEVATION_EVENTS = {
    "sunrise": (3.0, "rising"),
    "dawn": (8.0, "rising"),
    "golden hour": (8.0, "setting"),
    "sunset": (3.0, "setting"),
}

#: Named times defined by local apparent solar time, in hours.
SOLAR_CLOCK_EVENTS = {
    "morning": 9.0,
    "noon": 12.0,
    "afternoon": 15.0,
}

#: Words that ask for a sun below the horizon. They resolve (so the
#: request is recorded, never silently turned into noon) and then refuse
#: at render time.
NIGHT_WORDS = ("dusk", "twilight", "night", "midnight")

#: Synonyms the parsers accept, mapped onto the canonical names above.
ALIASES = {
    "midday": "noon",
    "early morning": "dawn",
    "first light": "dawn",
    "evening": "golden hour",
    "late afternoon": "golden hour",
    "nighttime": "night",
}

NAMED_TIMES = tuple(sorted(
    set(ELEVATION_EVENTS) | set(SOLAR_CLOCK_EVENTS) | set(NIGHT_WORDS)))

_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(z| utc)?$")


class SunError(ValueError):
    """The requested sun cannot be placed (or shown) as asked."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint


@dataclass(frozen=True)
class SunPosition:
    #: Apparent elevation above the horizon, degrees (refraction applied).
    elevation_deg: float
    #: Azimuth the sun is SEEN at, degrees clockwise from true north.
    azimuth_deg: float
    #: The UTC instant the position was computed for.
    when_utc: datetime
    #: One sentence: which rule turned the request into this instant.
    basis: str


# -- the NOAA equations ---------------------------------------------------

def _julian_day(when_utc: datetime) -> float:
    when_utc = when_utc.astimezone(timezone.utc)
    epoch = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    return 2451545.0 + (when_utc - epoch).total_seconds() / 86400.0


def _declination_and_eot(when_utc: datetime) -> Tuple[float, float]:
    """(declination in degrees, equation of time in minutes)."""
    t = (_julian_day(when_utc) - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (
        0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    declination = math.degrees(math.asin(math.sin(eps) * math.sin(apparent)))
    y = math.tan(eps / 2.0) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * e * e * math.sin(2 * mr))
    return declination, eot


def _refraction_deg(elevation_deg: float) -> float:
    """NOAA's piecewise atmospheric refraction, degrees (added to the
    geometric elevation)."""
    if elevation_deg > 85.0:
        return 0.0
    te = math.tan(math.radians(elevation_deg))
    if elevation_deg > 5.0:
        arcsec = 58.1 / te - 0.07 / te ** 3 + 0.000086 / te ** 5
    elif elevation_deg > -0.575:
        h = elevation_deg
        arcsec = 1735.0 + h * (-518.2 + h * (103.4 + h * (-12.79 + h * 0.711)))
    else:
        arcsec = -20.772 / te
    return arcsec / 3600.0


def solar_position(latitude_deg: float, longitude_deg: float,
                   when_utc: datetime) -> Tuple[float, float]:
    """(apparent elevation, azimuth clockwise from north) in degrees."""
    if when_utc.tzinfo is None:
        raise ValueError("when_utc must be timezone-aware")
    declination, eot = _declination_and_eot(when_utc)
    utc = when_utc.astimezone(timezone.utc)
    minutes = utc.hour * 60.0 + utc.minute + utc.second / 60.0 \
        + utc.microsecond / 6e7
    true_solar = (minutes + eot + 4.0 * longitude_deg) % 1440.0
    hour_angle = math.radians(true_solar / 4.0 - 180.0)
    lat = math.radians(latitude_deg)
    dec = math.radians(declination)
    cos_zenith = (math.sin(lat) * math.sin(dec)
                  + math.cos(lat) * math.cos(dec) * math.cos(hour_angle))
    zenith = math.acos(max(-1.0, min(1.0, cos_zenith)))
    elevation = 90.0 - math.degrees(zenith)
    azimuth = (math.degrees(math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat)
        - math.tan(dec) * math.cos(lat))) + 180.0) % 360.0
    return elevation + _refraction_deg(elevation), azimuth


# -- requests -> instants --------------------------------------------------

def canonical_time_of_day(text: str) -> str:
    """Normalise a time-of-day value; raises ValueError if unrecognised.

    Accepts the named times (and their aliases) and clock times
    ``HH:MM`` (local apparent solar time) or ``HH:MMZ`` / ``HH:MM UTC``.
    """
    value = " ".join(str(text).strip().lower().split())
    value = ALIASES.get(value, value)
    if value in NAMED_TIMES:
        return value
    match = _CLOCK.match(value)
    if match:
        hour, minute, zone = match.groups()
        return f"{int(hour):02d}:{minute}" + ("Z" if zone else "")
    raise ValueError(
        f"time of day {text!r} is not one of {list(NAMED_TIMES)} or a "
        f"clock time HH:MM (local solar) / HH:MMZ (UTC)")


def _utc_from_solar_hours(day: date, longitude_deg: float,
                          solar_hours: float) -> datetime:
    """The UTC instant at which local apparent solar time is solar_hours.

    Iterated twice: the equation of time moves by seconds over a day."""
    guess = datetime(day.year, day.month, day.day, 12,
                     tzinfo=timezone.utc)
    for _ in range(3):
        _, eot = _declination_and_eot(guess)
        minutes = solar_hours * 60.0 - eot - 4.0 * longitude_deg
        guess = datetime(day.year, day.month, day.day,
                         tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return guess


def _solar_hours_at_elevation(day: date, latitude_deg: float,
                              longitude_deg: float, elevation_deg: float,
                              direction: str) -> Optional[float]:
    """Local solar hours when the (geometric) sun crosses elevation_deg,
    or None when it never does that day (polar night/day, winter sun
    that never climbs that high)."""
    noon = _utc_from_solar_hours(day, longitude_deg, 12.0)
    declination, _ = _declination_and_eot(noon)
    lat = math.radians(latitude_deg)
    dec = math.radians(declination)
    denominator = math.cos(lat) * math.cos(dec)
    if abs(denominator) < 1e-9:
        return None
    cos_h = (math.sin(math.radians(elevation_deg))
             - math.sin(lat) * math.sin(dec)) / denominator
    if not -1.0 <= cos_h <= 1.0:
        return None
    hour_angle_hours = math.degrees(math.acos(cos_h)) / 15.0
    return 12.0 - hour_angle_hours if direction == "rising" \
        else 12.0 + hour_angle_hours


def resolve(time_of_day: str, latitude_deg: float, longitude_deg: float,
            day: Optional[date] = None) -> SunPosition:
    """Place the sun for a spec's time of day. Raises SunError when the
    requested event does not happen at that place on that day."""
    value = canonical_time_of_day(time_of_day)
    dated = day is not None
    day = day or DEFAULT_DATE
    date_note = (f"on {day.isoformat()}" if dated else
                 f"on {day.isoformat()} (no date stated: the equinox)")
    where = f"at {latitude_deg:.3f}, {longitude_deg:.3f}"

    if value in NIGHT_WORDS:
        when = _utc_from_solar_hours(
            day, longitude_deg, 0.0 if value == "midnight" else 21.0)
        basis = (f"'{value}' {where} {date_note}: taken as solar "
                 f"{'00:00' if value == 'midnight' else '21:00'}")
    elif value in ELEVATION_EVENTS:
        target, direction = ELEVATION_EVENTS[value]
        hours = _solar_hours_at_elevation(day, latitude_deg, longitude_deg,
                                          target, direction)
        if hours is None:
            raise SunError(
                "sun.event_absent",
                f"'{value}' means the sun {target:g} deg up and "
                f"{direction}, which never happens {where} {date_note}. "
                f"State a clock time or another date.")
        when = _utc_from_solar_hours(day, longitude_deg, hours)
        basis = (f"'{value}' = sun {target:g} deg up and {direction} "
                 f"{where} {date_note}")
    elif value in SOLAR_CLOCK_EVENTS:
        hours = SOLAR_CLOCK_EVENTS[value]
        when = _utc_from_solar_hours(day, longitude_deg, hours)
        basis = (f"'{value}' = local solar {int(hours):02d}:00 {where} "
                 f"{date_note}")
    else:
        hour, minute = int(value[:2]), int(value[3:5])
        if value.endswith("Z"):
            when = datetime(day.year, day.month, day.day, hour, minute,
                            tzinfo=timezone.utc)
            basis = f"{value[:5]} UTC {where} {date_note}"
        else:
            when = _utc_from_solar_hours(day, longitude_deg,
                                         hour + minute / 60.0)
            basis = (f"{value} local apparent solar time (not civil "
                     f"clock time) {where} {date_note}")

    elevation, azimuth = solar_position(latitude_deg, longitude_deg, when)
    return SunPosition(elevation_deg=elevation, azimuth_deg=azimuth,
                       when_utc=when, basis=basis)


def require_renderable(sun: SunPosition) -> None:
    """Refuse a sun the scene cannot show (see module docstring)."""
    if sun.elevation_deg < RENDER_FLOOR_DEG:
        raise SunError(
            "sun.below_render_floor",
            f"the sun is {sun.elevation_deg:.1f} deg "
            f"{'below' if sun.elevation_deg < 0 else 'above'} the horizon "
            f"({sun.basis}); the renderer has no twilight/night scene "
            f"(moon, stars, night exposure), so it refuses rather than "
            f"showing daylight. Floor: {RENDER_FLOOR_DEG:g} deg.")
