"""Night: the moon's position, phase and light, the starfield, the night flag.

W3 (docs/ADVANCEMENTS_BLUEPRINT.md section 4). What a night render is
GIVEN, computed once in Python from the spec's place and a moment:

* the MOON's apparent geocentric position by Meeus, *Astronomical
  Algorithms*, 2nd ed. (1998), chapter 47 (the ELP-2000/82 truncation:
  tables 47.A and 47.B, 60 terms each, transcribed here and pinned
  against Meeus's worked example 47.a -- 1992 April 12, 0h TD: geocentric
  lambda 133.162655 deg, beta -3.229126 deg, Delta 368 409.7 km, the
  three sums -1 127 527, -3 229 126 and -16 590 875 to the unit, and the
  apparent lambda 133.167265 deg with the nutation term). Nutation by
  Meeus chapter 22 (the leading terms of table 22.A, pinned against
  example 22.a); the true obliquity and the apparent sidereal time
  (chapter 12, pinned against examples 12.a and 12.b) put the moon on
  the local sky (chapter 13, pinned against example 13.b), topocentric
  by the parallax in altitude on a spherical earth, geometric (NO
  refraction, as ``core.scenario.solar``);
* its PHASE by Meeus chapter 48: the geocentric elongation psi from the
  sun (48.2 in ecliptic form), the phase angle i (48.3) and the
  illuminated fraction k = (1 + cos i) / 2 (48.1), pinned against
  example 48.a (k 0.6786, i 69.0756 deg). The sun is Meeus chapter 25's
  low-accuracy position (0.01 deg), computed here;
* its ILLUMINANCE by Krisciunas & Schaefer 1991 (PASP 103, 1033; "eq.
  20" in the blueprint's numbering, the equation numbers are
  [unverified here]): the moon's V magnitude m(alpha) = -12.73 +
  0.026 |alpha| + 4e-9 alpha^4 at phase angle alpha, its illuminance
  above the atmosphere I* = 10^(-0.4 (m + 16.57)) foot-candles (1 fc =
  10.7639 lx), extinguished by 10^(-0.4 k X(Z)) with X(Z) = (1 - 0.96
  sin^2 Z)^-1/2 and k = 0.172 mag per air mass (their V-band Mauna Kea
  value, a STATED clear-night choice). Full moon at the zenith: 0.267 lx,
  inside the 0.05-0.3 lx Kyba, Mohar & Posch 2017 (A&G 58(1)) range.
  Monotone DECREASING in the phase angle (increasing in k), measured in
  tests/test_night.py. The sky luminance by the same paper -- the
  moonlit sky B_moon(rho, Z, Z_moon) with its scattering function
  f(rho) and the dark sky B_zen X 10^(-0.4 k (X - 1)) at B_zen = 79.0 nL
  (V = 21.587 mag/arcsec^2) -- in nanolamberts (1 nL = 1e-5 / pi cd/m^2);
* the NIGHT flag: the sun at or below -6 deg (the end of civil
  twilight), by ``core.scenario.solar`` at the same moment and place;
* the STARFIELD: the Yale Bright Star Catalogue 5th ed. (Hoffleit &
  Warren 1991) from a CACHED copy whose sha256 is checked on every load
  (assets/stars/README.md is the fetch step; a file whose digest is not
  :data:`CATALOGUE_SHA256` is refused ``look.stars`` -- a corrupt cache
  never silently becomes a procedural sky), or, when the catalogue is
  absent, a SEEDED procedural field recorded as ``procedural`` (isotropic,
  magnitudes by N(<V) proportional to 10^(0.5 V) to V 6.5, the brightest
  clamped at Sirius's -1.46; the slope is a stated choice, not a fit).

``night.sun_units`` -- the rule, stated once. The moon is handed to the
engine as a second directional light whose intensity is ``illuminance_lux``
(the atmosphere's moon, W5). A number of lux means something only where
the engine's lights ARE in lux and the camera's exposure is the manual
EV100 the lux were meant for. So the moon's lux is refused by name when
it would be applied on the BIAS path (a camera without a stated exposure
triple keeps the Phase 10 exposure bias beside the engine's unitless 8.0
sun: 0.27 lx next to 8.0 puts a moonlit night at 3 % of daylight instead
of 3e-6), or on the manual EV100 path with the sun NOT in lux (S1's
defect, ``sensing.exposure_units``: EV100 expects lux, the 8.0 sun is
not). In spec terms: a stated moon needs ``scene.sun_lux`` stated (the
render is handed the sun in lux) and every camera's exposure stated (the
manual EV100 path). ``sun_units`` on the card is ``physical`` or
``unitless`` accordingly. Stars are an emissive sky, not a light, and
are not held to the rule.

Not claimed: the moon disc is the atmosphere light's (no lunar albedo
map, no earthshine); no airglow, zodiacal light or light pollution; no
precession of the catalogue from J2000 (under 0.4 deg to 2030) and no
proper motion; the procedural field is not the real sky; the K&S sky is a
V-band model at Mauna Kea's extinction, not the engine's atmosphere;
Delta T is a constant (:data:`DELTA_T_S`, [unverified here]); the engine
half (the moon light, the starfield sphere, W5) is uncompiled here.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The night flag: the sun at or below this elevation (end of civil twilight).
NIGHT_SUN_ELEVATION_DEG = -6.0
#: TD - UT in seconds, a constant for the 2020s [unverified here]; a 5 s
#: error moves the moon 0.0008 deg (it moves 0.55 deg an hour).
DELTA_T_S = 69.0
#: Krisciunas & Schaefer 1991: the V-band extinction coefficient (mag per
#: air mass) at Mauna Kea, the stated clear-night value.
KS_EXTINCTION_V = 0.172
#: K&S: the dark sky's zenith brightness, nanolamberts (V = 21.587).
KS_DARK_SKY_NL = 79.0
#: 1 foot-candle in lux (1 lm/ft^2 = 1 / 0.09290304 lm/m^2).
LUX_PER_FOOTCANDLE = 10.763910417
#: 1 nanolambert in cd/m^2 (1 L = 1e4 / pi cd/m^2).
CD_M2_PER_NANOLAMBERT = 1e-9 * 1e4 / math.pi
#: The moon words and the star modes a spec's ``scene.night`` may state.
MOON_WORDS = ("on", "off")
STARS_MODES = ("auto", "catalogue", "procedural", "off")
NIGHT_KEYS = ("moon", "stars", "utc")
#: The card's ``look.night`` keys, in their fixed order.
CARD_KEYS = ("moon_elevation_deg", "moon_azimuth_deg", "phase", "illuminance_lux",
             "stars_mode", "sun_units")
#: The render's light units the moon's lux needs (S1's radiometry spelling).
SUN_UNITS_PHYSICAL = "physical"
SUN_UNITS_UNITLESS = "unitless"

#: The cached catalogue: the Yale BSC5 as the brettonw/YaleBrightStarCatalog
#: mirror's JSON conversion of the Harvard ASCII file (bsc5-short.json: HR,
#: RA/Dec J2000, V, K), fetched 2026-09-29 and measured here: 954 206 bytes,
#: this sha256. The primary hosts (CDS V/50, tdc-www.harvard.edu) refuse the
#: CONNECT through this container's proxy, so the digest is the mirror's.
REPO = Path(__file__).resolve().parents[2]
CATALOGUE_PATH = REPO / "assets" / "stars" / "bsc5-short.json"
CATALOGUE_SHA256 = "94b0581379ef9ea49f1ce664734a06d2fbbff2d7487f926acad3e9ef0960e0d8"
CATALOGUE_SOURCE = ("Yale Bright Star Catalogue 5th ed. (Hoffleit & Warren 1991) via "
                    "brettonw/YaleBrightStarCatalog bsc5-short.json (a JSON conversion of the "
                    "Harvard ASCII catalogue), sha256 checked on load")
#: The procedural field: count (the BSC5's order of magnitude), limiting V,
#: the brightest star allowed, and the slope of log10 N(<V).
PROCEDURAL_COUNT = 9000
STAR_LIMITING_MAG = 6.5
STAR_BRIGHTEST_MAG = -1.46
PROCEDURAL_SLOPE = 0.5

REFERENCES = (
    "Meeus, Astronomical Algorithms, 2nd ed. (1998), ch. 7, 12, 13, 22, 25, 47, 48",
    "Krisciunas, K. & Schaefer, B. E. 1991, PASP 103, 1033 (moonlight and sky brightness) "
    "[equation numbers and coefficients unverified here]",
    "Kyba, C. C. M., Mohar, A. & Posch, T. 2017, A&G 58(1) (full-moon illuminance "
    "0.05-0.3 lx) [unverified here]",
    "Hoffleit, D. & Warren, W. H. 1991, The Bright Star Catalogue, 5th rev. ed. (Yale)",
)

NOT_CLAIMED = (
    "the moon disc is the atmosphere light's: no lunar albedo map, no earthshine",
    "no airglow, zodiacal light or light pollution",
    "procedural stars when the catalogue is absent (not the real sky)",
    "no precession from J2000 and no proper motion for the catalogue stars",
    "the K&S sky is a V-band model at Mauna Kea's extinction, not the engine's atmosphere",
    "the engine half (the moon light, the starfield sphere, W5) is uncompiled here",
)


class NightError(Exception):
    """A night sky that cannot be given, refused by name (``look.moon``,
    ``look.stars`` or ``night.sun_units``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


# -- time ---------------------------------------------------------------------

def julian_day(moment: datetime) -> float:
    """JD (UT) of an aware datetime (a naive one is read as UTC)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return 2440587.5 + moment.timestamp() / 86400.0


def parse_utc(text: str) -> datetime:
    """An ISO moment (``2024-06-21T22:30:00Z``) as an aware UTC datetime;
    refuses ``look.moon`` for anything else."""
    if not isinstance(text, str):
        raise NightError("look.moon", f"scene.night.utc must be an ISO moment string, not {text!r}")
    try:
        moment = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise NightError("look.moon", f"scene.night.utc {text!r} is not an ISO moment "
                                      f"(YYYY-MM-DDTHH:MM:SSZ)") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _norm(angle: float) -> float:
    return angle % 360.0


# -- Meeus ch. 22: nutation (the leading terms of table 22.A) -------------------------

#: (D, M, M', F, Omega, psi_sin 0.0001", psi_T, eps_cos 0.0001", eps_T): the 31
#: largest terms of Meeus table 22.A (IAU 1980); the rest are under 0.0015"
#: each. Pinned against example 22.a (tests/test_night.py).
_NUTATION = (
    (0, 0, 0, 0, 1, -171996, -174.2, 92025, 8.9),
    (-2, 0, 0, 2, 2, -13187, -1.6, 5736, -3.1),
    (0, 0, 0, 2, 2, -2274, -0.2, 977, -0.5),
    (0, 0, 0, 0, 2, 2062, 0.2, -895, 0.5),
    (0, 1, 0, 0, 0, 1426, -3.4, 54, -0.1),
    (0, 0, 1, 0, 0, 712, 0.1, -7, 0.0),
    (-2, 1, 0, 2, 2, -517, 1.2, 224, -0.6),
    (0, 0, 0, 2, 1, -386, -0.4, 200, 0.0),
    (0, 0, 1, 2, 2, -301, 0.0, 129, -0.1),
    (-2, -1, 0, 2, 2, 217, -0.5, -95, 0.3),
    (-2, 0, 1, 0, 0, -158, 0.0, 0, 0.0),
    (-2, 0, 0, 2, 1, 129, 0.1, -70, 0.0),
    (0, 0, -1, 2, 2, 123, 0.0, -53, 0.0),
    (2, 0, 0, 0, 0, 63, 0.0, 0, 0.0),
    (0, 0, 1, 0, 1, 63, 0.1, -33, 0.0),
    (2, 0, -1, 2, 2, -59, 0.0, 26, 0.0),
    (0, 0, -1, 0, 1, -58, -0.1, 32, 0.0),
    (0, 0, 1, 2, 1, -51, 0.0, 27, 0.0),
    (-2, 0, 2, 0, 0, 48, 0.0, 0, 0.0),
    (0, 0, -2, 2, 1, 46, 0.0, -24, 0.0),
    (2, 0, 0, 2, 2, -38, 0.0, 16, 0.0),
    (0, 0, 2, 2, 2, -31, 0.0, 13, 0.0),
    (0, 0, 2, 0, 0, 29, 0.0, 0, 0.0),
    (-2, 0, 1, 2, 2, 29, 0.0, -12, 0.0),
    (0, 0, 0, 2, 0, 26, 0.0, 0, 0.0),
    (-2, 0, 0, 2, 0, -22, 0.0, 0, 0.0),
    (0, 0, -1, 2, 1, 21, 0.0, -10, 0.0),
    (0, 2, 0, 0, 0, 17, -0.1, 0, 0.0),
    (2, 0, -1, 0, 1, 16, 0.0, -8, 0.0),
    (-2, 2, 0, 2, 2, -16, 0.1, 7, 0.0),
    (0, 1, 0, 0, 1, -15, 0.0, 9, 0.0),
)


def nutation(jde: float) -> Tuple[float, float, float]:
    """(delta_psi, delta_eps, true obliquity), degrees, at a JDE."""
    t = (jde - 2451545.0) / 36525.0
    d = math.radians(297.85036 + 445267.111480 * t - 0.0019142 * t * t + t ** 3 / 189474.0)
    m = math.radians(357.52772 + 35999.050340 * t - 0.0001603 * t * t - t ** 3 / 300000.0)
    mp = math.radians(134.96298 + 477198.867398 * t + 0.0086972 * t * t + t ** 3 / 56250.0)
    f = math.radians(93.27191 + 483202.017538 * t - 0.0036825 * t * t + t ** 3 / 327270.0)
    om = math.radians(125.04452 - 1934.136261 * t + 0.0020708 * t * t + t ** 3 / 450000.0)
    dpsi = deps = 0.0
    for cd, cm, cmp_, cf, co, s0, s1, c0, c1 in _NUTATION:
        arg = cd * d + cm * m + cmp_ * mp + cf * f + co * om
        dpsi += (s0 + s1 * t) * math.sin(arg)
        deps += (c0 + c1 * t) * math.cos(arg)
    dpsi_deg = dpsi * 1e-4 / 3600.0
    deps_deg = deps * 1e-4 / 3600.0
    eps0 = (23.0 + 26.0 / 60.0 + 21.448 / 3600.0
            - (46.8150 * t + 0.00059 * t * t - 0.001813 * t ** 3) / 3600.0)
    return dpsi_deg, deps_deg, eps0 + deps_deg


# -- Meeus ch. 12: sidereal time ----------------------------------------------

def mean_sidereal_deg(jd_ut: float) -> float:
    """Greenwich mean sidereal time, degrees (Meeus 12.4)."""
    t = (jd_ut - 2451545.0) / 36525.0
    return _norm(280.46061837 + 360.98564736629 * (jd_ut - 2451545.0)
                 + 0.000387933 * t * t - t ** 3 / 38710000.0)


def apparent_sidereal_deg(jd_ut: float) -> float:
    """Greenwich apparent sidereal time: the mean plus delta_psi cos(eps)."""
    dpsi, _deps, eps = nutation(jd_ut + DELTA_T_S / 86400.0)
    return _norm(mean_sidereal_deg(jd_ut) + dpsi * math.cos(math.radians(eps)))


# -- Meeus ch. 13: equatorial -> horizontal ----------------------------------------

def horizontal(hour_angle_deg: float, declination_deg: float,
               latitude_deg: float) -> Tuple[float, float]:
    """(Meeus azimuth from the SOUTH, westward; altitude), degrees (13.5, 13.6)."""
    h = math.radians(hour_angle_deg)
    d = math.radians(declination_deg)
    p = math.radians(latitude_deg)
    azimuth = math.degrees(math.atan2(math.sin(h),
                                      math.cos(h) * math.sin(p) - math.tan(d) * math.cos(p)))
    altitude = math.degrees(math.asin(max(-1.0, min(1.0, math.sin(p) * math.sin(d)
                                                    + math.cos(p) * math.cos(d) * math.cos(h)))))
    return _norm(azimuth), altitude


def equatorial(lambda_deg: float, beta_deg: float, eps_deg: float) -> Tuple[float, float]:
    """(right ascension, declination), degrees, from ecliptic (13.3, 13.4)."""
    lam, bet, eps = (math.radians(v) for v in (lambda_deg, beta_deg, eps_deg))
    alpha = math.degrees(math.atan2(math.sin(lam) * math.cos(eps) - math.tan(bet) * math.sin(eps),
                                    math.cos(lam)))
    delta = math.degrees(math.asin(math.sin(bet) * math.cos(eps)
                                   + math.cos(bet) * math.sin(eps) * math.sin(lam)))
    return _norm(alpha), delta


# -- Meeus ch. 25: the sun, low accuracy -----------------------------------------

def sun_ecliptic(jde: float) -> Tuple[float, float]:
    """(apparent longitude deg, distance AU): Meeus 25.2-25.5, 25.8."""
    t = (jde - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    m = 357.52911 + 35999.05029 * t - 0.0001537 * t * t
    e = 0.016708634 - 0.000042037 * t - 0.0000001267 * t * t
    mr = math.radians(m)
    c = ((1.914602 - 0.004817 * t - 0.000014 * t * t) * math.sin(mr)
         + (0.019993 - 0.000101 * t) * math.sin(2 * mr) + 0.000289 * math.sin(3 * mr))
    true_longitude = l0 + c
    v = math.radians(m + c)
    distance = 1.000001018 * (1.0 - e * e) / (1.0 + e * math.cos(v))
    omega = math.radians(125.04 - 1934.136 * t)
    return _norm(true_longitude - 0.00569 - 0.00478 * math.sin(omega)), distance


AU_KM = 149597870.7


# -- Meeus ch. 47: the moon ----------------------------------------------------------

#: Table 47.A: (D, M, M', F, sigma_l sine coefficient, sigma_r cosine coefficient).
_MOON_LR = (
    (0, 0, 1, 0, 6288774, -20905355), (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968), (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888), (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158), (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733), (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620), (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755), (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0), (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782), (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636), (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824), (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675), (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445), (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403), (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0), (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322), (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751), (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950), (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0), (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0), (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616), (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117), (2, 2, -1, 0, -700, 2354),
    (2, 1, -2, 0, 691, 0), (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, -1423), (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571), (1, 0, -2, 0, -487, -1739),
    (2, 1, 0, -2, -399, 0), (0, 0, 2, -2, -381, -4421),
    (1, 1, 1, 0, 351, 0), (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0), (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 1165), (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0), (2, 0, -1, -2, 0, 8752),
)
#: Table 47.B: (D, M, M', F, sigma_b sine coefficient).
_MOON_B = (
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200), (2, 1, 0, -1, -3359), (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211), (2, -1, -1, -1, 2065), (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828), (0, 1, 0, 1, -1794), (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565), (1, 0, 0, 1, -1491), (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410), (0, 1, 0, -1, -1344), (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107), (4, 0, 0, -1, 1021), (4, 0, -1, 1, 833),
    (0, 0, 1, -3, 777), (4, 0, -2, 1, 671), (2, 0, 0, -3, 607),
    (2, 0, 2, -1, 596), (2, -1, 1, -1, 491), (2, 0, -2, 1, -451),
    (0, 0, 3, -1, 439), (2, 0, 2, 1, 422), (2, 0, -3, -1, 421),
    (2, 1, -1, 1, -366), (2, 1, 0, 1, -351), (4, 0, 0, 1, 331),
    (2, -1, 1, 1, 315), (2, -2, 0, -1, 302), (0, 0, 1, 3, -283),
    (2, 1, 1, -1, -229), (1, 1, 0, -1, 223), (1, 1, 0, 1, 223),
    (0, 1, -2, -1, -220), (2, 1, -1, -1, -220), (1, 0, 1, 1, -185),
    (2, -1, -2, -1, 181), (0, 1, 2, 1, -177), (4, 0, -2, -1, 176),
    (4, -1, -1, -1, 166), (1, 0, 1, -1, -164), (4, 0, 1, -1, 132),
    (1, 0, -1, -1, -119), (4, -1, 0, -1, 115), (2, -2, 0, 1, 107),
)


@dataclass(frozen=True)
class MoonGeocentric:
    """Meeus ch. 47 at one JDE: the sums, the geocentric ecliptic position,
    the distance, the parallax, and the apparent position with nutation."""

    jde: float
    sigma_l: float
    sigma_b: float
    sigma_r: float
    longitude_deg: float          # geocentric, mean equinox of date
    latitude_deg: float
    distance_km: float
    parallax_deg: float
    apparent_longitude_deg: float
    nutation_longitude_deg: float
    obliquity_deg: float          # true
    right_ascension_deg: float    # apparent
    declination_deg: float        # apparent


def moon_geocentric(jde: float) -> MoonGeocentric:
    """The moon's position by Meeus chapter 47 (see the module docstring)."""
    t = (jde - 2451545.0) / 36525.0
    lp = _norm(218.3164477 + 481267.88123421 * t - 0.0015786 * t * t
               + t ** 3 / 538841.0 - t ** 4 / 65194000.0)
    d = _norm(297.8501921 + 445267.1114034 * t - 0.0018819 * t * t
              + t ** 3 / 545868.0 - t ** 4 / 113065000.0)
    m = _norm(357.5291092 + 35999.0502909 * t - 0.0001536 * t * t + t ** 3 / 24490000.0)
    mp = _norm(134.9633964 + 477198.8675055 * t + 0.0087414 * t * t
               + t ** 3 / 69699.0 - t ** 4 / 14712000.0)
    f = _norm(93.2720950 + 483202.0175233 * t - 0.0036539 * t * t
              - t ** 3 / 3526000.0 + t ** 4 / 863310000.0)
    a1 = math.radians(_norm(119.75 + 131.849 * t))
    a2 = math.radians(_norm(53.09 + 479264.290 * t))
    a3 = math.radians(_norm(313.45 + 481266.484 * t))
    e = 1.0 - 0.002516 * t - 0.0000074 * t * t
    dr, mr, mpr, fr, lpr = (math.radians(v) for v in (d, m, mp, f, lp))
    sigma_l = sigma_r = sigma_b = 0.0
    for cd, cm, cmp_, cf, cl, cr in _MOON_LR:
        arg = cd * dr + cm * mr + cmp_ * mpr + cf * fr
        scale = e ** abs(cm)
        sigma_l += cl * scale * math.sin(arg)
        sigma_r += cr * scale * math.cos(arg)
    for cd, cm, cmp_, cf, cb in _MOON_B:
        arg = cd * dr + cm * mr + cmp_ * mpr + cf * fr
        sigma_b += cb * (e ** abs(cm)) * math.sin(arg)
    sigma_l += 3958.0 * math.sin(a1) + 1962.0 * math.sin(lpr - fr) + 318.0 * math.sin(a2)
    sigma_b += (-2235.0 * math.sin(lpr) + 382.0 * math.sin(a3) + 175.0 * math.sin(a1 - fr)
                + 175.0 * math.sin(a1 + fr) + 127.0 * math.sin(lpr - mpr)
                - 115.0 * math.sin(lpr + mpr))
    longitude = _norm(lp + sigma_l / 1e6)
    latitude = sigma_b / 1e6
    distance = 385000.56 + sigma_r / 1000.0
    parallax = math.degrees(math.asin(6378.14 / distance))
    dpsi, _deps, eps = nutation(jde)
    apparent = _norm(longitude + dpsi)
    alpha, delta = equatorial(apparent, latitude, eps)
    return MoonGeocentric(jde=jde, sigma_l=sigma_l, sigma_b=sigma_b, sigma_r=sigma_r,
                          longitude_deg=longitude, latitude_deg=latitude,
                          distance_km=distance, parallax_deg=parallax,
                          apparent_longitude_deg=apparent, nutation_longitude_deg=dpsi,
                          obliquity_deg=eps, right_ascension_deg=alpha,
                          declination_deg=delta)


# -- Meeus ch. 48: the phase ---------------------------------------------------------

def moon_phase(jde: float, moon: Optional[MoonGeocentric] = None) -> Tuple[float, float, float]:
    """(illuminated fraction k, phase angle i deg, elongation psi deg):
    cos psi = cos beta cos(lambda - lambda_sun) (48.2 in ecliptic form),
    tan i = R sin psi / (Delta - R cos psi) (48.3), k = (1 + cos i) / 2 (48.1)."""
    moon = moon_geocentric(jde) if moon is None else moon
    sun_longitude, sun_au = sun_ecliptic(jde)
    beta = math.radians(moon.latitude_deg)
    dlon = math.radians(moon.apparent_longitude_deg - sun_longitude)
    psi = math.acos(max(-1.0, min(1.0, math.cos(beta) * math.cos(dlon))))
    r = sun_au * AU_KM
    i = math.atan2(r * math.sin(psi), moon.distance_km - r * math.cos(psi))
    return (1.0 + math.cos(i)) / 2.0, math.degrees(i), math.degrees(psi)


# -- Krisciunas & Schaefer 1991 ----------------------------------------------------

def ks_air_mass(zenith_deg: float) -> float:
    """X(Z) = (1 - 0.96 sin^2 Z)^-1/2 (K&S; finite at the horizon: 5.0)."""
    s = math.sin(math.radians(min(90.0, max(0.0, float(zenith_deg)))))
    return (1.0 - 0.96 * s * s) ** -0.5


def moon_magnitude(phase_angle_deg: float) -> float:
    """The moon's V magnitude at phase angle alpha: -12.73 + 0.026|a| + 4e-9 a^4."""
    a = abs(float(phase_angle_deg))
    return -12.73 + 0.026 * a + 4e-9 * a ** 4


def moon_illuminance_top_lux(phase_angle_deg: float) -> float:
    """I* above the atmosphere: 10^(-0.4 (m + 16.57)) fc, in lux."""
    return 10.0 ** (-0.4 * (moon_magnitude(phase_angle_deg) + 16.57)) * LUX_PER_FOOTCANDLE


def moon_illuminance_lux(phase_angle_deg: float, moon_elevation_deg: float,
                         k: float = KS_EXTINCTION_V) -> float:
    """The moon's illuminance at the ground, normal to the moon, lux: I*
    extinguished by 10^(-0.4 k X(Z)); 0 at or below the horizon."""
    if moon_elevation_deg <= 0.0:
        return 0.0
    return moon_illuminance_top_lux(phase_angle_deg) * 10.0 ** (
        -0.4 * k * ks_air_mass(90.0 - moon_elevation_deg))


def ks_scattering(rho_deg: float) -> float:
    """f(rho) = 10^5.36 (1.06 + cos^2 rho) + 10^(6.15 - rho / 40), rho >= 10 deg
    (clamped there: K&S state the Mie term for rho above 10 deg)."""
    rho = max(10.0, float(rho_deg))
    return (10.0 ** 5.36 * (1.06 + math.cos(math.radians(rho)) ** 2)
            + 10.0 ** (6.15 - rho / 40.0))


def moonlit_sky_nl(phase_angle_deg: float, rho_deg: float, moon_zenith_deg: float,
                   sky_zenith_deg: float, k: float = KS_EXTINCTION_V) -> float:
    """B_moon = f(rho) I* 10^(-0.4 k X(Zm)) [1 - 10^(-0.4 k X(Z))], nL, I* in
    foot-candles; 0 with the moon below the horizon."""
    if moon_zenith_deg >= 90.0:
        return 0.0
    i_star = 10.0 ** (-0.4 * (moon_magnitude(phase_angle_deg) + 16.57))
    return (ks_scattering(rho_deg) * i_star
            * 10.0 ** (-0.4 * k * ks_air_mass(moon_zenith_deg))
            * (1.0 - 10.0 ** (-0.4 * k * ks_air_mass(sky_zenith_deg))))


def dark_sky_nl(sky_zenith_deg: float, k: float = KS_EXTINCTION_V,
                zenith_nl: float = KS_DARK_SKY_NL) -> float:
    """B_sky = B_zen X(Z) 10^(-0.4 k (X(Z) - 1)), nL."""
    x = ks_air_mass(sky_zenith_deg)
    return zenith_nl * x * 10.0 ** (-0.4 * k * (x - 1.0))


def separation_deg(az1: float, el1: float, az2: float, el2: float) -> float:
    """The angle between two sky directions (compass azimuth, elevation)."""
    a1, e1, a2, e2 = (math.radians(v) for v in (az1, el1, az2, el2))
    c = math.sin(e1) * math.sin(e2) + math.cos(e1) * math.cos(e2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def sky_luminance_cd_m2(phase_angle_deg: float, moon_azimuth_deg: float,
                        moon_elevation_deg: float, sky_azimuth_deg: float,
                        sky_elevation_deg: float, moon: bool = True,
                        k: float = KS_EXTINCTION_V) -> Dict[str, float]:
    """The K&S sky luminance at one sky direction, cd/m^2: the dark sky and
    (with ``moon``) the moonlit sky, and their sum."""
    z = 90.0 - float(sky_elevation_deg)
    dark = dark_sky_nl(z, k) * CD_M2_PER_NANOLAMBERT
    lit = 0.0
    if moon:
        rho = separation_deg(moon_azimuth_deg, moon_elevation_deg, sky_azimuth_deg,
                             sky_elevation_deg)
        lit = moonlit_sky_nl(phase_angle_deg, rho, 90.0 - float(moon_elevation_deg), z, k) \
            * CD_M2_PER_NANOLAMBERT
    return {"dark_cd_m2": dark, "moon_cd_m2": lit, "total_cd_m2": dark + lit}


# -- the night flag --------------------------------------------------------------

def is_night(sun_elevation_deg: float) -> bool:
    """The night flag: the sun at or below NIGHT_SUN_ELEVATION_DEG (-6 deg)."""
    return float(sun_elevation_deg) <= NIGHT_SUN_ELEVATION_DEG


def sun_elevation_deg(latitude_deg: float, longitude_deg: float, moment: datetime) -> float:
    """The sun's geometric elevation by ``core.scenario.solar`` (S1's chain)."""
    from ..scenario.solar import solar_position

    utc = moment.astimezone(timezone.utc)
    day = utc.timetuple().tm_yday
    hour = utc.hour + utc.minute / 60.0 + (utc.second + utc.microsecond * 1e-6) / 3600.0
    return solar_position(latitude_deg, longitude_deg, utc.year, day, hour).elevation_deg


# -- the moon on the local sky --------------------------------------------------------

@dataclass(frozen=True)
class MoonSky:
    elevation_deg: float          # topocentric (parallax in altitude), geometric
    azimuth_deg: float            # compass, clockwise from true north
    illuminated_fraction: float
    phase_angle_deg: float
    elongation_deg: float
    distance_km: float
    illuminance_lux: float        # at the ground, normal to the moon; 0 below the horizon
    right_ascension_deg: float
    declination_deg: float


def moon_at(latitude_deg: float, longitude_deg: float, moment: datetime) -> MoonSky:
    """The moon at a place (longitude east-positive) and a UTC moment."""
    jd = julian_day(moment)
    jde = jd + DELTA_T_S / 86400.0
    moon = moon_geocentric(jde)
    k, i, psi = moon_phase(jde, moon)
    theta = apparent_sidereal_deg(jd)
    hour_angle = _norm(theta + float(longitude_deg) - moon.right_ascension_deg)
    south_azimuth, altitude = horizontal(hour_angle, moon.declination_deg, latitude_deg)
    parallax = math.degrees(math.asin(math.sin(math.radians(moon.parallax_deg))
                                      * math.cos(math.radians(altitude))))
    elevation = altitude - parallax
    return MoonSky(elevation_deg=elevation, azimuth_deg=_norm(south_azimuth + 180.0),
                   illuminated_fraction=k, phase_angle_deg=i, elongation_deg=psi,
                   distance_km=moon.distance_km,
                   illuminance_lux=moon_illuminance_lux(i, elevation),
                   right_ascension_deg=moon.right_ascension_deg,
                   declination_deg=moon.declination_deg)


# -- the starfield -----------------------------------------------------------------

@dataclass(frozen=True)
class StarField:
    """The stars a night render is given: (ra_deg, dec_deg, v_mag) rows, J2000."""

    mode: str                                   # "catalogue" | "procedural" | "off"
    stars: Tuple[Tuple[float, float, float], ...]
    sha256: Optional[str]                       # of the rows as text, None when off
    source: str
    seed: Optional[int] = None
    catalogue_sha256: Optional[str] = None

    @property
    def count(self) -> int:
        return len(self.stars)

    def record(self) -> Dict[str, Any]:
        return {"mode": self.mode, "count": self.count, "sha256": self.sha256,
                "source": self.source, "seed": self.seed,
                "catalogue_sha256": self.catalogue_sha256}


def _rows_digest(rows: Sequence[Tuple[float, float, float]]) -> str:
    text = "\n".join(f"{ra:.6f} {dec:.6f} {v:.3f}" for ra, dec, v in rows)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _sexagesimal(text: str, hours: bool) -> float:
    parts = _NUMBER.findall(str(text))
    if len(parts) != 3:
        raise ValueError(f"{text!r} is not three sexagesimal fields")
    whole, minutes, seconds = (float(p) for p in parts)
    sign = -1.0 if str(text).strip().startswith("-") else 1.0
    value = abs(whole) + minutes / 60.0 + seconds / 3600.0
    return sign * value * (15.0 if hours else 1.0)


def load_catalogue(path: Optional[Path] = None,
                   expected_sha256: str = CATALOGUE_SHA256
                   ) -> Optional[Tuple[Tuple[float, float, float], ...]]:
    """The cached catalogue's (ra, dec, V) rows, or None when the file is
    absent. A file whose sha256 is not ``expected_sha256`` is refused
    ``look.stars``; so is one that does not parse (entries without a V
    magnitude -- the catalogue's few novae and non-stellar objects -- are
    skipped and counted in nothing: the digest pins the file)."""
    path = CATALOGUE_PATH if path is None else Path(path)
    if not path.is_file():
        return None
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        raise NightError("look.stars",
                         f"the cached star catalogue {path.name} has sha256 {digest[:12]}..., "
                         f"not the {expected_sha256[:12]}... the code checks; re-fetch it "
                         f"(assets/stars/README.md) rather than draw a sky from another file")
    try:
        entries = json.loads(data.decode("utf-8"))
        rows = []
        for entry in entries:
            if not isinstance(entry, Mapping) or entry.get("V") in (None, ""):
                continue
            rows.append((_sexagesimal(entry["RA"], True), _sexagesimal(entry["Dec"], False),
                         float(entry["V"])))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
        raise NightError("look.stars", f"the cached star catalogue {path.name} does not "
                                       f"parse as the BSC5 conversion ({exc})") from None
    return tuple(rows)


def procedural_field(seed: int, count: int = PROCEDURAL_COUNT,
                     limiting_mag: float = STAR_LIMITING_MAG
                     ) -> Tuple[Tuple[float, float, float], ...]:
    """The seeded stand-in: RA uniform, sin(Dec) uniform, V = V_lim +
    log10(u) / slope clamped at the brightest; one numpy generator per
    seed (sha256 of ``"<seed>:stars"``), the same rows every time."""
    import numpy as np

    digest = hashlib.sha256(f"{int(seed)}:stars".encode("ascii")).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:8], "big"))
    ra = rng.uniform(0.0, 360.0, count)
    dec = np.degrees(np.arcsin(rng.uniform(-1.0, 1.0, count)))
    u = 1.0 - rng.uniform(0.0, 1.0, count)             # (0, 1]
    mag = np.maximum(limiting_mag + np.log10(u) / PROCEDURAL_SLOPE, STAR_BRIGHTEST_MAG)
    return tuple((float(a), float(d), float(round(m, 3))) for a, d, m in zip(ra, dec, mag))


def starfield(mode: str, seed: int = 0, catalogue_path: Optional[Path] = None,
              expected_sha256: str = CATALOGUE_SHA256) -> StarField:
    """The field a ``stars`` mode gives: ``catalogue`` (refused ``look.stars``
    when absent), ``procedural`` (always the seeded field), ``auto`` (the
    catalogue when cached and verified, else procedural, RECORDED as
    procedural), ``off`` (no stars). A cached file whose digest differs is
    refused in every mode that reads it."""
    if mode not in STARS_MODES:
        raise NightError("look.stars", f"scene.night.stars must be one of "
                                       f"{list(STARS_MODES)}, not {mode!r}")
    if mode == "off":
        return StarField("off", (), None, "no stars asked for")
    rows = None
    if mode in ("catalogue", "auto"):
        rows = load_catalogue(catalogue_path, expected_sha256)
        if rows is None and mode == "catalogue":
            where = CATALOGUE_PATH if catalogue_path is None else Path(catalogue_path)
            raise NightError("look.stars", f"the star catalogue is not cached at {where}; "
                                           f"fetch it (assets/stars/README.md) or ask for "
                                           f"procedural stars")
    if rows is not None:
        return StarField("catalogue", rows, _rows_digest(rows), CATALOGUE_SOURCE,
                         catalogue_sha256=expected_sha256)
    rows = procedural_field(seed)
    return StarField("procedural", rows, _rows_digest(rows),
                     f"procedural: {PROCEDURAL_COUNT} isotropic stars, log10 N(<V) slope "
                     f"{PROCEDURAL_SLOPE} to V {STAR_LIMITING_MAG}, seed {int(seed)} "
                     f"(the catalogue is not cached)", seed=int(seed))


def stars_above_horizon(field: StarField, latitude_deg: float, longitude_deg: float,
                        moment: datetime, limiting_mag: float = STAR_LIMITING_MAG) -> int:
    """How many of the field's stars no fainter than ``limiting_mag`` stand
    above the geometric horizon at the moment (J2000 positions, no
    precession, stated)."""
    if not field.stars:
        return 0
    import numpy as np

    rows = np.asarray(field.stars, dtype=float)
    rows = rows[rows[:, 2] <= limiting_mag]
    theta = mean_sidereal_deg(julian_day(moment))
    h = np.radians((theta + float(longitude_deg) - rows[:, 0]) % 360.0)
    d = np.radians(rows[:, 1])
    p = math.radians(latitude_deg)
    sin_alt = math.sin(p) * np.sin(d) + math.cos(p) * np.cos(d) * np.cos(h)
    return int(np.count_nonzero(sin_alt > 0.0))


# -- the spec's block ---------------------------------------------------------------

def night_problems(value: Any) -> List[Tuple[str, str]]:
    """``[(constraint, message)]`` for a stated ``scene.night`` mapping: a
    mapping of ``moon`` (on | off), ``stars`` (auto | catalogue |
    procedural | off) and an optional ``utc`` ISO moment; the shape and
    the moon words refuse ``look.moon``, the star mode ``look.stars``."""
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [("look.moon", f"scene.night must be a mapping {{moon, stars, utc}}, not {value!r}")]
    out: List[Tuple[str, str]] = []
    unknown = sorted(set(value) - set(NIGHT_KEYS))
    if unknown:
        out.append(("look.moon", f"scene.night carries unknown keys {unknown}; it states "
                                 f"{list(NIGHT_KEYS)}"))
    moon = value.get("moon", "on")
    if moon not in MOON_WORDS:
        out.append(("look.moon", f"scene.night.moon must be one of {list(MOON_WORDS)}, "
                                 f"not {moon!r}"))
    stars = value.get("stars", "auto")
    if stars not in STARS_MODES:
        out.append(("look.stars", f"scene.night.stars must be one of {list(STARS_MODES)}, "
                                  f"not {stars!r}"))
    if value.get("utc") is not None:
        try:
            parse_utc(value["utc"])
        except NightError as exc:
            out.append((exc.constraint, exc.message))
    return out


def sun_units_problem(moon_on: bool, sun_units: str, exposure_path: str) -> Optional[str]:
    """Why the moon's lux cannot be applied, or None (the rule in the module
    docstring): the moon on needs the sun in lux (``physical``) and the
    manual EV100 path (``manual_ev100``)."""
    if not moon_on:
        return None
    if sun_units != SUN_UNITS_PHYSICAL and exposure_path != "manual_ev100":
        return ("the moon's lux would be applied on the bias path: no camera states an "
                "exposure triple and the sun is the engine's unitless 8.0 -- state "
                "scene.sun_lux and every camera's exposure, or turn the moon off")
    if sun_units != SUN_UNITS_PHYSICAL:
        return ("the exposure is manual EV100 but the sun is not in lux (the engine's "
                "unitless 8.0, S1's defect): the moon's lux beside it means nothing -- state "
                "scene.sun_lux")
    if exposure_path != "manual_ev100":
        return ("the sun is in lux but a camera keeps the bias exposure path: the moon's lux "
                "would be exposed by a bias calibrated for the unitless sun -- state every "
                "camera's exposure triple")
    return None


# -- the sky a spec asks for ---------------------------------------------------------

@dataclass(frozen=True)
class NightSky:
    """Everything the night look records (the card carries CARD_KEYS)."""

    moment_utc: str
    moment_source: str
    latitude_deg: float
    longitude_deg: float
    sun_elevation_deg: float
    night: bool
    moon_requested: bool
    moon_elevation_deg: float
    moon_azimuth_deg: float
    phase: float                  # illuminated fraction k (Meeus 48.1)
    phase_angle_deg: float
    moon_distance_km: float
    illuminance_lux: float        # 0 when the moon is off or below the horizon
    stars_mode: str               # as APPLIED: catalogue | procedural | off
    stars_requested: str
    star_count: int
    stars_sha256: Optional[str]
    stars_source: str
    sun_units: str

    def card_block(self) -> Dict[str, Any]:
        return {"moon_elevation_deg": round(self.moon_elevation_deg, 4),
                "moon_azimuth_deg": round(self.moon_azimuth_deg, 4),
                "phase": round(self.phase, 4),
                "illuminance_lux": float(f"{self.illuminance_lux:.6g}"),
                "stars_mode": self.stars_mode,
                "sun_units": self.sun_units}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def night_sky(latitude_deg: float, longitude_deg: float, moment: datetime,
              moon: str = "on", stars: str = "auto", seed: int = 0,
              sun_units: str = SUN_UNITS_UNITLESS, moment_source: str = "stated",
              catalogue_path: Optional[Path] = None,
              expected_sha256: str = CATALOGUE_SHA256) -> NightSky:
    """The night look at a place and a moment (pure but for the catalogue read)."""
    problems = night_problems({"moon": moon, "stars": stars})
    if problems:
        raise NightError(*problems[0])
    utc = moment.astimezone(timezone.utc) if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    sun = sun_elevation_deg(latitude_deg, longitude_deg, utc)
    sky = moon_at(latitude_deg, longitude_deg, utc)
    field = starfield(stars, seed, catalogue_path, expected_sha256)
    moon_on = moon == "on"
    return NightSky(
        moment_utc=utc.strftime("%Y-%m-%dT%H:%M:%SZ"), moment_source=moment_source,
        latitude_deg=float(latitude_deg), longitude_deg=float(longitude_deg),
        sun_elevation_deg=sun, night=is_night(sun), moon_requested=moon_on,
        moon_elevation_deg=sky.elevation_deg, moon_azimuth_deg=sky.azimuth_deg,
        phase=sky.illuminated_fraction, phase_angle_deg=sky.phase_angle_deg,
        moon_distance_km=sky.distance_km,
        illuminance_lux=sky.illuminance_lux if moon_on else 0.0,
        stars_mode=field.mode, stars_requested=stars,
        star_count=stars_above_horizon(field, latitude_deg, longitude_deg, utc),
        stars_sha256=field.sha256, stars_source=field.source, sun_units=sun_units)


def spec_moment(spec) -> Tuple[Optional[datetime], str]:
    """The moment a spec's night is computed for: ``scene.night.utc`` when
    stated, else the randomisation block's drawn moment (year, day of year,
    UTC hour) when it was sampled, else (None, why)."""
    value = spec.scene.night.value if getattr(spec.scene, "night", None) is not None else None
    if isinstance(value, Mapping) and value.get("utc") is not None:
        return parse_utc(value["utc"]), "scene.night.utc"
    block = spec.randomization
    if block.is_enabled() and block.is_sampled():
        from datetime import timedelta

        start = datetime(int(block.year.value), 1, 1, tzinfo=timezone.utc)
        moment = start + timedelta(days=int(block.day_of_year.value) - 1,
                                   hours=float(block.hour_utc.value))
        return moment, "the randomisation block's drawn moment"
    return None, ("no moment: scene.night states no utc and the randomisation block has "
                  "not drawn one")


def spec_sun_units(spec) -> str:
    """``physical`` when the spec states ``scene.sun_lux`` (the render is
    handed the sun in lux), else ``unitless`` (the engine's 8.0)."""
    q = getattr(spec.scene, "sun_lux", None)
    return SUN_UNITS_PHYSICAL if q is not None and q.value is not None else SUN_UNITS_UNITLESS


def spec_exposure_path(spec) -> str:
    """``manual_ev100`` when every camera states its exposure triple (the
    card then carries cameras[N].exposure), else ``manual_bias``."""
    cameras = list(spec.cameras)
    if cameras and all(not c.exposure.is_default(str(c.preset.value)) for c in cameras):
        return "manual_ev100"
    return "manual_bias"


def spec_night(spec, catalogue_path: Optional[Path] = None,
               expected_sha256: str = CATALOGUE_SHA256) -> Optional[NightSky]:
    """The night sky a spec states, or None when ``scene.night`` is unstated.
    Refuses ``look.moon`` without a moment and ``night.sun_units`` by the rule."""
    q = getattr(spec.scene, "night", None)
    if q is None or q.value is None:
        return None
    problems = night_problems(q.value)
    if problems:
        raise NightError(*problems[0])
    moment, source = spec_moment(spec)
    if moment is None:
        raise NightError("look.moon", f"the moon cannot be placed: {source}")
    moon = q.value.get("moon", "on")
    units = spec_sun_units(spec)
    problem = sun_units_problem(moon == "on", units, spec_exposure_path(spec))
    if problem:
        raise NightError("night.sun_units", problem)
    return night_sky(float(spec.latitude.value), float(spec.longitude.value), moment,
                     moon=moon, stars=q.value.get("stars", "auto"),
                     seed=int(spec.seed.value), sun_units=units, moment_source=source,
                     catalogue_path=catalogue_path, expected_sha256=expected_sha256)
