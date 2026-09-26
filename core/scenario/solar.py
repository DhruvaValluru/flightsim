"""Solar position from date, time and place -- the cited algorithm.

The sun's elevation and azimuth for a given latitude, longitude, year,
day of year and UTC hour, by the low-accuracy solar coordinates of
Meeus, *Astronomical Algorithms*, 2nd ed. (1998), chapter 25, in the
form the NOAA ESRL Global Monitoring Laboratory publishes as its
"General Solar Position Calculations" (the NOAA Solar Calculator). The
stated accuracy of the method is about 0.01 degree in the sun's
longitude for years 1950-2050; the sun's position on the sky is good to
better than a tenth of a degree, which is far inside what a rendered
frame resolves.

What is and is not modelled, stated once:

* geometric elevation -- NO atmospheric refraction correction (about
  0.5 degree at the horizon, negligible at the elevations the sampler
  accepts; the record says "geometric");
* azimuth clockwise from true north (compass convention), 0-360;
* UTC time in; the equation of time and the longitude turn it into
  true solar time inside;
* no nutation beyond Meeus's apparent-longitude term, no parallax.

Nothing here draws a random number. The sampler chooses a moment; this
module says where the sun is at that moment, the same way every time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

SOURCE = ("Meeus, Astronomical Algorithms, 2nd ed. (1998), ch. 25 "
          "(low-accuracy solar coordinates); NOAA ESRL GML General Solar "
          "Position Calculations. Geometric elevation, no refraction.")


@dataclass(frozen=True)
class SolarPosition:
    elevation_deg: float        # geometric, above the horizontal
    azimuth_deg: float          # clockwise from true north, [0, 360)
    declination_deg: float
    equation_of_time_min: float
    hour_angle_deg: float       # negative before solar noon
    julian_day: float


def julian_day(year: int, day_of_year: int, hour_utc: float) -> float:
    """Julian Day for a calendar year, day of year (1-based) and UTC hour.

    J2000.0 = JD 2451545.0 = 2000-01-01 12:00 UTC; days are counted from
    there with the calendar, so leap years fall where they fall."""
    if not (1 <= day_of_year <= 366):
        raise ValueError(f"day_of_year {day_of_year} is not in 1..366")
    days_in_year = 366 if _is_leap(year) else 365
    if day_of_year > days_in_year:
        raise ValueError(f"{year} has {days_in_year} days; day "
                         f"{day_of_year} does not exist")
    civil = date(year, 1, 1) + timedelta(days=day_of_year - 1)
    days_since_j2000_noon = (civil - date(2000, 1, 1)).days - 0.5
    return 2451545.0 + days_since_j2000_noon + hour_utc / 24.0


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def solar_position(latitude_deg: float, longitude_deg: float, year: int,
                   day_of_year: int, hour_utc: float) -> SolarPosition:
    """Where the sun is. Longitude east-positive, as everywhere in the
    spec."""
    jd = julian_day(year, day_of_year, hour_utc)
    t = (jd - 2451545.0) / 36525.0                       # Julian centuries
    # Geometric mean longitude and anomaly of the sun (Meeus 25.2, 25.3).
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)  # eccentricity
    mr = math.radians(m)
    # Equation of centre (25.4) -> true longitude.
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    # Apparent longitude (nutation + aberration, 25.8) and the
    # corresponding obliquity (22.2 + 25.8 correction).
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = true_long - 0.00569 - 0.00478 * math.sin(omega)
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - 0.001813 * t))) / 60.0) / 60.0
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(math.radians(apparent)))
    # Equation of time, minutes (Meeus 28.3 as NOAA writes it).
    y = math.tan(eps / 2.0) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr)
        + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    # True solar time (minutes) and hour angle (degrees, negative before
    # local solar noon).
    tst = (hour_utc * 60.0 + eot + 4.0 * longitude_deg) % 1440.0
    hour_angle = tst / 4.0 - 180.0
    if hour_angle < -180.0:
        hour_angle += 360.0
    lat = math.radians(latitude_deg)
    ha = math.radians(hour_angle)
    cos_zenith = (math.sin(lat) * math.sin(decl)
                  + math.cos(lat) * math.cos(decl) * math.cos(ha))
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    zenith = math.acos(cos_zenith)
    elevation = 90.0 - math.degrees(zenith)
    sin_zenith = math.sin(zenith)
    if sin_zenith < 1e-12 or abs(math.cos(lat)) < 1e-12:
        # Sun at the zenith/nadir or observer at a pole: azimuth is
        # undefined; report the solar-noon convention (south for the
        # northern hemisphere, north for the southern) rather than NaN.
        azimuth = 180.0 if latitude_deg >= 0.0 else 0.0
    else:
        cos_az = ((math.sin(lat) * cos_zenith - math.sin(decl))
                  / (math.cos(lat) * sin_zenith))
        cos_az = max(-1.0, min(1.0, cos_az))
        az = math.degrees(math.acos(cos_az))
        azimuth = (az + 180.0) % 360.0 if hour_angle > 0.0 else (540.0 - az) % 360.0
    return SolarPosition(elevation_deg=elevation, azimuth_deg=azimuth,
                         declination_deg=math.degrees(decl),
                         equation_of_time_min=eot,
                         hour_angle_deg=hour_angle, julian_day=jd)
