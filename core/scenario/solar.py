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
from typing import Dict, Optional

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


# -- S1: the sun in lux -------------------------------------------------------
#
# The visual scene sets its directional light to 8.0 (FlightSimVisualScene.cpp
# L164, FlightSimRenderCommandlet.cpp L1064): a unitless number where the
# manual-exposure path expects lux (ADVANCEMENTS_BLUEPRINT section 3, "where
# the branch stands"). The function below gives the number the engine should
# be handed: the clear-sky DIRECT NORMAL illuminance of the sun, in lux, at a
# stated elevation, altitude and atmosphere -- what a directional light's
# intensity means in Unreal's physical light units.
#
# Model, stated once. Bird & Hulstrom's simplified clear-sky model (Bird, R. E.
# and Hulstrom, R. L., "A Simplified Clear Sky Model for Direct and Diffuse
# Insolation on Horizontal Surfaces", SERI/TR-642-761, 1981) gives the
# broadband direct normal irradiance as I_0 x 0.9662 x T_R T_a T_w T_o T_um:
# Rayleigh, aerosol, water-vapour, ozone and uniformly-mixed-gas transmittances
# over Kasten's air mass, each a closed form in the air mass and one column
# amount. The coefficients below are transcribed from memory of that report
# and are [unverified here] -- the report's host is unreachable through this
# container's proxy. It is a BROADBAND model with no spectrum, so the lux is
# the irradiance times a DECLARED luminous efficacy: the efficacy of the
# ASTM G173-03 direct + circumsolar reference spectrum under CIE 1924
# V(lambda), 683 x integral(S V) / integral(S) = 107.92 lm/W, measured here from
# the cached tables (assets/illuminants, assets/cie; tests/test_radiometry.py
# recomputes it and pins the constant) and used at every air mass. Perez et
# al. 1990 (Solar Energy 44(5)) give the direct efficacy as a function of sky
# clearness and brightness [unverified here]; SPCTRAL2 (Bird & Riordan 1986)
# is the named upgrade that would integrate a spectrum instead.
#
# What is NOT claimed: the diffuse sky (the engine's sky light is its own
# capture); twilight (below the horizon the direct sun is 0 lx, said so);
# the air-mass dependence of the efficacy (a constant is used; the G173
# global-tilt efficacy is 109.45 lm/W and the extraterrestrial 98.74 lm/W,
# so the constant sits inside that spread); any cloud; that the engine's
# light unit is lux until the Windows step reads back light_units
# 'physical' (S4).

#: The efficacy applied to the broadband direct irradiance (lm/W): the ASTM
#: G173-03 direct spectrum under V(lambda), measured here (see above).
DIRECT_LUMINOUS_EFFICACY_LM_PER_W = 107.92
#: Bird & Hulstrom's solar constant (W/m^2), [unverified here].
SOLAR_CONSTANT_W_M2 = 1353.0
#: The largest direct normal illuminance a sun can have: the ASTM G173-03
#: extraterrestrial spectrum under V(lambda), 133 100 lx (measured here from
#: the cached table: 1347.93 W/m^2 x 98.74 lm/W). A stated sun above it is
#: refused sensing.sun_lux; nothing above the atmosphere is brighter.
SUN_LUX_MAX = 133100.0
#: Representative clear-day column amounts and turbidity (the model's
#: inputs), a STATED choice: ozone 0.3 atm-cm, precipitable water 1.5 cm,
#: aerosol optical depths 0.1 at 500 nm and 0.15 at 380 nm.
DEFAULT_OZONE_ATM_CM = 0.3
DEFAULT_WATER_CM = 1.5
DEFAULT_AOD_500NM = 0.1
DEFAULT_AOD_380NM = 0.15
#: ISA sea-level pressure (hPa) and the barometric formula the model's
#: pressure correction takes from the altitude when no pressure is stated.
ISA_SEA_LEVEL_HPA = 1013.25

SUN_LUX_SOURCE = ("Bird & Hulstrom 1981, SERI/TR-642-761 (broadband clear-sky direct normal "
                  "irradiance) [unverified here] x the ASTM G173-03 direct luminous efficacy "
                  "under CIE 1924 V(lambda), 107.92 lm/W (measured here from the cached "
                  "tables); provenance model")


class SunLuxError(Exception):
    """A sun that cannot be lit, refused by name (``sensing.sun_lux``)."""

    constraint = "sensing.sun_lux"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"sensing.sun_lux: {message}")


@dataclass(frozen=True)
class SunIlluminance:
    illuminance_lux: float            # direct normal, 0 below the horizon
    direct_normal_w_m2: float
    elevation_deg: float
    air_mass: float
    pressure_hpa: float
    transmittances: Dict[str, float]  # rayleigh, aerosol, water, ozone, mixed_gases
    efficacy_lm_per_w: float
    earth_sun_factor: float
    source: str = SUN_LUX_SOURCE
    note: str = ""


def isa_pressure_hpa(altitude_m: float) -> float:
    """The ISA troposphere's pressure at a geometric altitude (the 1976
    standard atmosphere's first layer; clamped at the tropopause)."""
    h = max(0.0, min(float(altitude_m), 11000.0))
    return ISA_SEA_LEVEL_HPA * (1.0 - 2.25577e-5 * h) ** 5.25588


def kasten_air_mass(zenith_deg: float) -> float:
    """Kasten (1966) relative optical air mass, as Bird & Hulstrom use it."""
    z = float(zenith_deg)
    return 1.0 / (math.cos(math.radians(z)) + 0.15 * (93.885 - z) ** -1.253)


def bird_hulstrom_direct_normal(elevation_deg: float, pressure_hpa: float = ISA_SEA_LEVEL_HPA,
                                ozone_atm_cm: float = DEFAULT_OZONE_ATM_CM,
                                water_cm: float = DEFAULT_WATER_CM,
                                aod_500nm: float = DEFAULT_AOD_500NM,
                                aod_380nm: float = DEFAULT_AOD_380NM,
                                day_of_year: Optional[int] = None):
    """(direct normal irradiance W/m^2, air mass, the five transmittances,
    the earth-sun factor) for a sun at ``elevation_deg`` above the
    horizon; 0 W/m^2 at or below it. The formulas are Bird & Hulstrom
    1981's [unverified here]; see the section comment."""
    elevation = float(elevation_deg)
    if elevation <= 0.0:
        return 0.0, math.inf, {"rayleigh": 0.0, "aerosol": 0.0, "water": 0.0,
                               "ozone": 0.0, "mixed_gases": 0.0}, 1.0
    zenith = 90.0 - elevation
    m = kasten_air_mass(zenith)
    mp = m * float(pressure_hpa) / ISA_SEA_LEVEL_HPA
    t_rayleigh = math.exp(-0.0903 * mp ** 0.84 * (1.0 + mp - mp ** 1.01))
    xo = float(ozone_atm_cm) * m
    t_ozone = (1.0 - 0.1611 * xo * (1.0 + 139.48 * xo) ** -0.3035
               - 0.002715 * xo / (1.0 + 0.044 * xo + 0.0003 * xo * xo))
    t_gases = math.exp(-0.0127 * mp ** 0.26)
    xw = float(water_cm) * m
    t_water = 1.0 - 2.4959 * xw / ((1.0 + 79.034 * xw) ** 0.6828 + 6.385 * xw)
    tau = 0.2758 * float(aod_380nm) + 0.35 * float(aod_500nm)
    t_aerosol = math.exp(-(tau ** 0.873) * (1.0 + tau - tau ** 0.7088) * m ** 0.9108)
    factor = 1.0
    if day_of_year is not None:
        factor = 1.0 + 0.033 * math.cos(2.0 * math.pi * int(day_of_year) / 365.0)
    dni = (SOLAR_CONSTANT_W_M2 * factor * 0.9662
           * t_rayleigh * t_aerosol * t_water * t_ozone * t_gases)
    return dni, m, {"rayleigh": t_rayleigh, "aerosol": t_aerosol, "water": t_water,
                    "ozone": t_ozone, "mixed_gases": t_gases}, factor


def illuminance_lux(elevation_deg: float, altitude_m: float = 0.0,
                    pressure_hpa: Optional[float] = None,
                    efficacy_lm_per_w: float = DIRECT_LUMINOUS_EFFICACY_LM_PER_W,
                    day_of_year: Optional[int] = None, **atmosphere) -> SunIlluminance:
    """The sun's clear-sky DIRECT NORMAL illuminance in lux (provenance
    ``model``): Bird & Hulstrom's broadband direct normal irradiance times
    the declared efficacy. ``pressure_hpa`` defaults to the ISA pressure
    at ``altitude_m``. Refuses ``sensing.sun_lux`` for an elevation that
    is not a finite number in [-90, 90], a non-positive efficacy or
    pressure, or a result above :data:`SUN_LUX_MAX` (which no admissible
    input produces; the guard exists for a mis-stated efficacy). A sun
    at or below the horizon gives 0 lx with the reason in ``note`` --
    twilight is not modelled and is not a refusal (the flight is not
    the sun's)."""
    try:
        elevation = float(elevation_deg)
    except (TypeError, ValueError):
        raise SunLuxError(f"the sun's elevation must be a number of degrees, not {elevation_deg!r}")
    if not math.isfinite(elevation) or not -90.0 <= elevation <= 90.0:
        raise SunLuxError(f"the sun's elevation {elevation!r} deg is outside -90..90")
    if not (isinstance(efficacy_lm_per_w, (int, float)) and math.isfinite(efficacy_lm_per_w)
            and efficacy_lm_per_w > 0.0):
        raise SunLuxError(f"a luminous efficacy must be a positive number of lm/W, "
                          f"not {efficacy_lm_per_w!r}")
    pressure = isa_pressure_hpa(altitude_m) if pressure_hpa is None else float(pressure_hpa)
    if not math.isfinite(pressure) or pressure <= 0.0:
        raise SunLuxError(f"a pressure of {pressure_hpa!r} hPa cannot be corrected for")
    dni, air_mass, transmittances, factor = bird_hulstrom_direct_normal(
        elevation, pressure, day_of_year=day_of_year, **atmosphere)
    lux = dni * float(efficacy_lm_per_w)
    if lux > SUN_LUX_MAX:
        raise SunLuxError(f"{lux:.0f} lx exceeds the extraterrestrial direct normal illuminance "
                          f"{SUN_LUX_MAX:.0f} lx; no sun is brighter than the one above the "
                          f"atmosphere")
    note = ("" if elevation > 0.0 else
            "the sun is at or below the horizon: direct illuminance 0 lx; twilight is not modelled")
    return SunIlluminance(illuminance_lux=lux, direct_normal_w_m2=dni, elevation_deg=elevation,
                          air_mass=air_mass, pressure_hpa=pressure,
                          transmittances=transmittances,
                          efficacy_lm_per_w=float(efficacy_lm_per_w),
                          earth_sun_factor=factor, note=note)


def sun_lux_problem(value) -> Optional[str]:
    """Why a STATED ``scene.sun_lux`` cannot be lit, or None: the one
    sentence the validator (``sensing.sun_lux``) and the render flags
    share. A stated sun is a positive finite number of lux no brighter
    than the extraterrestrial one; None is 'unstated' and is not a
    problem."""
    if value is None:
        return None
    if isinstance(value, bool):
        return f"scene.sun_lux must be a number of lux, not {value!r}"
    try:
        lux = float(value)
    except (TypeError, ValueError):
        return f"scene.sun_lux must be a number of lux, not {value!r}"
    if not math.isfinite(lux) or lux <= 0.0:
        return f"scene.sun_lux must be a positive number of lux, not {value!r}"
    if lux > SUN_LUX_MAX:
        return (f"scene.sun_lux {lux:g} lx exceeds the extraterrestrial direct normal "
                f"illuminance {SUN_LUX_MAX:.0f} lx")
    return None
