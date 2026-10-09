"""Solar, lunar and stellar positions for a place and an instant.

Low-precision series, chosen so the sky is right to well under a rendered
pixel's worth of what matters and nothing needs an ephemeris download:

* Sun: the NOAA solar calculator's formulation of Meeus ch. 25 (about
  0.01 deg in position, well inside the 0.27 deg solar radius).
* Moon: Meeus ch. 47 truncated to its largest terms (about 0.1-0.3 deg in
  position; the full series is 60+ terms), with topocentric parallax --
  the moon sits up to ~1 deg lower than its geocentric position, which
  is bigger than the moon.
* Stars: catalogue J2000 positions precessed to date (Meeus ch. 21, IAU
  1976 angles). Proper motion, nutation and aberration (all < 30 arcsec
  over this century for naked-eye stars) are ignored.

Horizontal coordinates: azimuth is a compass bearing (0 = north, 90 =
east), elevation above the astronomical horizon, with Bennett's standard
refraction added above -1 deg. tests/test_sky.py pins these against
published values and against astropy-computed references.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Tuple

import numpy as np

#: Mean Earth-Moon distance and the Moon's radius, km (Meeus; IAU).
MOON_MEAN_DISTANCE_KM = 385000.56
MOON_RADIUS_KM = 1737.4
EARTH_EQUATORIAL_RADIUS_KM = 6378.14
AU_KM = 149597870.7
SUN_RADIUS_KM = 695700.0


def julian_day(when: datetime) -> float:
    """Julian day (UT) of an aware or naive-UTC datetime."""
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc).replace(tzinfo=None)
    year, month = when.year, when.month
    day = (when.day + (when.hour + (when.minute + (when.second
           + when.microsecond / 1e6) / 60.0) / 60.0) / 24.0)
    if month <= 2:
        year -= 1
        month += 12
    a = year // 100
    b = 2 - a + a // 4
    return (math.floor(365.25 * (year + 4716))
            + math.floor(30.6001 * (month + 1)) + day + b - 1524.5)


def _centuries(jd: float) -> float:
    return (jd - 2451545.0) / 36525.0


def _obliquity_deg(t: float) -> float:
    """Mean obliquity plus the dominant nutation term (Meeus 22.2/25.8)."""
    seconds = 21.448 - t * (46.8150 + t * (0.00059 - t * 0.001813))
    omega = 125.04 - 1934.136 * t
    return 23.0 + (26.0 + seconds / 60.0) / 60.0 \
        + 0.00256 * math.cos(math.radians(omega))


def gmst_deg(jd: float) -> float:
    """Greenwich mean sidereal time, degrees (Meeus 12.4)."""
    t = _centuries(jd)
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * t * t - t ** 3 / 38710000.0) % 360.0


def refraction_deg(elevation_deg):
    """Bennett's refraction for a TRUE elevation, degrees (standard
    atmosphere); zero below -1 deg where the formula is meaningless."""
    h = np.asarray(elevation_deg, dtype=float)
    r = 1.02 / np.tan(np.radians(h + 10.3 / (h + 5.11))) / 60.0
    return np.where(h > -1.0, r, 0.0)


def equatorial_to_horizontal(ra_deg, dec_deg, jd: float, lat_deg: float,
                             lon_deg: float, refract: bool = True):
    """(azimuth, elevation) in degrees for arrays of RA/Dec of date."""
    ra = np.radians(np.asarray(ra_deg, dtype=float))
    dec = np.radians(np.asarray(dec_deg, dtype=float))
    lat = math.radians(lat_deg)
    hour = np.radians(gmst_deg(jd) + lon_deg) - ra
    sin_el = (np.sin(lat) * np.sin(dec)
              + np.cos(lat) * np.cos(dec) * np.cos(hour))
    el = np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))
    az = np.degrees(np.arctan2(
        np.sin(hour),
        np.cos(hour) * np.sin(lat) - np.tan(dec) * np.cos(lat))) + 180.0
    if refract:
        el = el + refraction_deg(el)
    return np.mod(az, 360.0), el


def _ecliptic_to_equatorial(lon_deg: float, lat_deg: float,
                            eps_deg: float) -> Tuple[float, float]:
    lam, beta, eps = (math.radians(lon_deg), math.radians(lat_deg),
                      math.radians(eps_deg))
    ra = math.atan2(math.sin(lam) * math.cos(eps)
                    - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps)
                    + math.cos(beta) * math.sin(eps) * math.sin(lam))
    return math.degrees(ra) % 360.0, math.degrees(dec)


# -- sun -------------------------------------------------------------------


def sun_ecliptic(jd: float) -> Tuple[float, float]:
    """(apparent ecliptic longitude deg, distance km) -- NOAA / Meeus 25."""
    t = _centuries(jd)
    l0 = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360.0
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m) * (0.019993 - 0.000101 * t)
         + math.sin(3 * m) * 0.000289)
    true_lon = l0 + c
    true_anomaly = m + math.radians(c)
    radius_au = 1.000001018 * (1 - e * e) / (1 + e * math.cos(true_anomaly))
    omega = math.radians(125.04 - 1934.136 * t)
    apparent = true_lon - 0.00569 - 0.00478 * math.sin(omega)
    return apparent % 360.0, radius_au * AU_KM


@dataclass(frozen=True)
class Body:
    """A body's horizontal position for one observer and instant."""

    azimuth_deg: float
    elevation_deg: float
    distance_km: float
    angular_radius_deg: float


def sun_position(when: datetime, lat_deg: float, lon_deg: float) -> Body:
    jd = julian_day(when)
    lam, dist = sun_ecliptic(jd)
    ra, dec = _ecliptic_to_equatorial(lam, 0.0,
                                      _obliquity_deg(_centuries(jd)))
    az, el = equatorial_to_horizontal(ra, dec, jd, lat_deg, lon_deg)
    return Body(float(az), float(el), dist,
                math.degrees(math.asin(SUN_RADIUS_KM / dist)))


# -- moon ------------------------------------------------------------------

# Meeus Table 47.A/B, largest terms: (D, M, M', F, sigma_l 1e-6 deg,
# sigma_r 1e-3 km). Terms in M carry the eccentricity factor E^|M|.
_MOON_LR = (
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
)
_MOON_B = (
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
)


def moon_ecliptic(jd: float) -> Tuple[float, float, float]:
    """(geocentric ecliptic longitude deg, latitude deg, distance km)."""
    t = _centuries(jd)
    lp = 218.3164477 + 481267.88123421 * t
    d = math.radians(297.8501921 + 445267.1114034 * t)
    m = math.radians(357.5291092 + 35999.0502909 * t)
    mp = math.radians(134.9633964 + 477198.8675055 * t)
    f = math.radians(93.2720950 + 483202.0175233 * t)
    e = 1.0 - 0.002516 * t - 0.0000074 * t * t
    sum_l = sum_r = sum_b = 0.0
    for cd, cm, cmp_, cf, sl, sr in _MOON_LR:
        arg = cd * d + cm * m + cmp_ * mp + cf * f
        scale = e ** abs(cm)
        sum_l += sl * scale * math.sin(arg)
        sum_r += sr * scale * math.cos(arg)
    for cd, cm, cmp_, cf, sb in _MOON_B:
        arg = cd * d + cm * m + cmp_ * mp + cf * f
        sum_b += sb * (e ** abs(cm)) * math.sin(arg)
    # The additive A1-A3 / L' corrections (Meeus 47, venus/jupiter/flattening).
    a1 = math.radians(119.75 + 131.849 * t)
    a2 = math.radians(53.09 + 479264.290 * t)
    a3 = math.radians(313.45 + 481266.484 * t)
    lp_r = math.radians(lp)
    sum_l += 3958 * math.sin(a1) + 1962 * math.sin(lp_r - f) \
        + 318 * math.sin(a2)
    sum_b += (-2235 * math.sin(lp_r) + 382 * math.sin(a3)
              + 175 * math.sin(a1 - f) + 175 * math.sin(a1 + f)
              + 127 * math.sin(lp_r - mp) - 115 * math.sin(lp_r + mp))
    omega = math.radians(125.04452 - 1934.136261 * t)
    nutation_lon = -17.20 / 3600.0 * math.sin(omega)
    lon = (lp + sum_l / 1e6 + nutation_lon) % 360.0
    return lon, sum_b / 1e6, MOON_MEAN_DISTANCE_KM + sum_r / 1000.0


@dataclass(frozen=True)
class Moon(Body):
    #: Sun-Moon-Earth angle, degrees: 0 full, 180 new.
    phase_angle_deg: float
    illuminated_fraction: float
    waxing: bool


def moon_position(when: datetime, lat_deg: float, lon_deg: float) -> Moon:
    jd = julian_day(when)
    t = _centuries(jd)
    lam, beta, dist = moon_ecliptic(jd)
    ra, dec = _ecliptic_to_equatorial(lam, beta, _obliquity_deg(t))
    az, el_geo = equatorial_to_horizontal(ra, dec, jd, lat_deg, lon_deg,
                                          refract=False)
    # Topocentric parallax in elevation (spherical-Earth approximation; the
    # azimuth shift is second order at these precisions).
    parallax = math.asin(EARTH_EQUATORIAL_RADIUS_KM / dist)
    el = float(el_geo) - math.degrees(
        parallax * math.cos(math.radians(float(el_geo))))
    el += float(refraction_deg(el))

    sun_lon, sun_dist = sun_ecliptic(jd)
    cos_elong = (math.cos(math.radians(beta))
                 * math.cos(math.radians(lam - sun_lon)))
    elong = math.acos(max(-1.0, min(1.0, cos_elong)))
    phase = math.atan2(sun_dist * math.sin(elong),
                       dist - sun_dist * math.cos(elong))
    fraction = (1.0 + math.cos(phase)) / 2.0
    waxing = (lam - sun_lon) % 360.0 < 180.0
    return Moon(float(az), el, dist,
                math.degrees(math.asin(MOON_RADIUS_KM / dist)),
                math.degrees(phase), fraction, waxing)


def moon_relative_brightness(phase_angle_deg: float) -> float:
    """Moon illuminance relative to full, from the phase-angle magnitude
    law (Allen: m = -12.73 + 0.026|i| + 4e-9 i^4). Half moon is ~0.1 of
    full, not 0.5 -- the opposition surge."""
    i = abs(phase_angle_deg)
    delta_mag = 0.026 * i + 4e-9 * i ** 4
    return 10.0 ** (-0.4 * delta_mag)


# -- stars -----------------------------------------------------------------


def precess_j2000(ra_deg, dec_deg, jd: float):
    """Catalogue J2000 RA/Dec -> mean of date (Meeus 21.2-21.4)."""
    t = _centuries(jd)
    zeta = math.radians((2306.2181 * t + 0.30188 * t * t
                         + 0.017998 * t ** 3) / 3600.0)
    z = math.radians((2306.2181 * t + 1.09468 * t * t
                      + 0.018203 * t ** 3) / 3600.0)
    theta = math.radians((2004.3109 * t - 0.42665 * t * t
                          - 0.041833 * t ** 3) / 3600.0)
    ra0 = np.radians(np.asarray(ra_deg, dtype=float))
    dec0 = np.radians(np.asarray(dec_deg, dtype=float))
    a = np.cos(dec0) * np.sin(ra0 + zeta)
    b = (math.cos(theta) * np.cos(dec0) * np.cos(ra0 + zeta)
         - math.sin(theta) * np.sin(dec0))
    c = (math.sin(theta) * np.cos(dec0) * np.cos(ra0 + zeta)
         + math.cos(theta) * np.sin(dec0))
    ra = np.degrees(np.arctan2(a, b) + z) % 360.0
    dec = np.degrees(np.arcsin(np.clip(c, -1.0, 1.0)))
    return ra, dec


def star_illuminance_lux(vmag):
    """Illuminance at normal incidence from a star of visual magnitude V,
    outside the atmosphere: E = 10^(-0.4 (V + 13.99)) lux (V = 0 gives
    2.54e-6 lux)."""
    return 10.0 ** (-0.4 * (np.asarray(vmag, dtype=float) + 13.99))


def bv_to_rgb(bv) -> np.ndarray:
    """Approximate linear RGB (max channel 1) for a B-V colour index.

    B-V -> temperature (Ballesteros 2012), then a blackbody sampled at
    three wavelengths and normalised. A presentation approximation: the
    eye barely sees star colour at night, and it is labeled as such.
    """
    bv = np.clip(np.nan_to_num(np.asarray(bv, dtype=float), nan=0.6),
                 -0.4, 2.0)
    temp = 4600.0 * (1.0 / (0.92 * bv + 1.7) + 1.0 / (0.92 * bv + 0.62))
    wavelengths = np.array([610e-9, 550e-9, 465e-9])
    h, c, k = 6.626e-34, 2.998e8, 1.381e-23
    lam = wavelengths[None, :]
    radiance = 1.0 / (lam ** 5 * (np.exp(h * c / (lam * k * temp[:, None]))
                                  - 1.0))
    return radiance / radiance.max(axis=1, keepdims=True)
