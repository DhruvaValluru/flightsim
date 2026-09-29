"""The non-standard atmosphere and humidity (gap P1): a stated day, delivered.

What this provider does
-----------------------
It writes three JSBSim properties -- ``atmosphere/delta-T`` (a temperature
bias in Rankine applied at every altitude), ``atmosphere/P-sl-psf`` (an
off-standard sea-level pressure) and ``atmosphere/dew-point-R`` (the dew
point, which JSBSim turns into a vapour pressure and a moist gas constant)
-- BEFORE the trim, so the trim solver sees the hot day, and again every
step, reading each back so the record can say the value survived. A
variable the spec does not state is not written: JSBSim's own standard
day stands for it, and no record is made for it.

The model (JSBSim 1.2.4 ``FGStandardAtmosphere``, fetched and read; every
equation below is a transcription with the source function named):

* ``T(h) = T_ISA(H) + delta_T`` where ``H`` is the geopotential altitude
  of the geometric ``h`` (``GetTemperature``; the graded-delta route,
  ``SL-graded-delta-T``, is NOT used and is said so).
* Pressure by the layer formula with the BIASED base temperatures
  (``CalculatePressureBreakpoints``, ``GetPressure``): the breakpoints
  are rebuilt from ``P_sl`` and ``T_b + delta_T`` layer by layer.
* Vapour pressure by the Magnus form ``e = a exp(b t / (c + t))`` with
  ``a = 611.2 Pa, b = 17.62, c = 243.12 degC`` (Sonntag 1990 as the
  source cites it; ``CalculateVaporPressure``), the vapour mass fraction
  ``f = R_dry e / (R_water (P - e))`` (``SetVaporPressure``), capped at
  saturation and at a per-altitude table of record-high fractions
  (``ValidateVaporMassFraction``), and the moist gas constant
  ``R = (f R_water + R_dry) / (1 + f)``.
* Density ``rho = P / (R T)``; density altitude and pressure altitude by
  inverting the standard layer formulas (``CalculateDensityAltitude``,
  ``CalculatePressureAltitude``), returned as geometric altitudes.

The closed form here (:func:`closed_form`, :func:`expected_density_ratio`)
is the same set of equations, so the null test's predicted side and the
delivered side can be compared to a stated tolerance -- measured on the
installed build, not assumed (tests/test_atmosphere.py).

Two silent caps in JSBSim, measured here and refused by name instead
(docs/JSBSIM_CORRECTIONS.md): a dew point above the air temperature is
capped to it and a line is printed (``dew-point-R`` 540 at ISA sea level
reads back 518.67); a vapour mass fraction above the altitude table's
record-high value is capped to the table (a dew point of 500 R written
at 5000 ft reads back 499.63 R). The validator refuses both at the
scene's initial altitude (``atmosphere.dew_point``); along the flight
the provider writes the least of the stated dew point, the modelled
temperature at the aircraft's altitude and the cap there, and counts
the steps where it had to.

What is NOT claimed: the words are stated choices, not MIL-HDBK-310
transcriptions (``hot_day`` is +30 degC, a value inside the handbook's
1 % hot column as remembered, unverified here; ``cold_day`` is -40 degC;
``humid`` is 90 % relative humidity); the MIL-HDBK-310 named profiles
are refused (``atmosphere.profile``) until transcribed with provenance;
no temperature inversion, no lapse-rate change, no humidity profile with
height (the dew point is held constant along the flight); JSBSim's
standard day is taken as the US Standard Atmosphere 1976 on the source's
own word (the 1976 tables were not compared here); the Magnus constants
carry the source's stated +/-0.35 degC over -45..60 degC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..fdm import units as u
from ..records import AppliedVariable, NullTest
from ..scenario.blocks import (
    ATMOSPHERE_RANGES, DAY_STANDARDS, DAY_WORDS, NAMED_PROFILES,
)
from .base import AtmosphereProvider, Position, Term

# -- constants, transcribed from FGStandardAtmosphere.h / FGAtmosphere.h ------

#: JSBSim's own standard-day sea level: 518.67 R, 2116.228 psf
#: (FGAtmosphere.h ``StdDaySLtemperature``, ``StdDaySLpressure``).
T_SL_R = 518.67
P_SL_PSF = 2116.228
#: Rankine per kelvin.
R_PER_K = 1.8
#: g0 in ft/s^2 (FGAtmosphere.h ``g0 = 9.80665 / fttom``).
G0_FT_S2 = 9.80665 / u.M_PER_FT
#: Gas constants in ft.lbf/(slug.R): Rstar / M with Rstar 8.31432
#: J/(mol.K), M_air 28.9645, M_water 18.016 g/mol (FGAtmosphere.h,
#: FGStandardAtmosphere.h); the kg-to-slug factor cancels in the ratio.
R_DRY = 8.31432 / 0.0289645 / (R_PER_K * u.M_PER_FT ** 2)
R_WATER = 8.31432 / 0.018016 / (R_PER_K * u.M_PER_FT ** 2)
#: JSBSim's psf-to-pascal factor (FGJSBBase ``psftopa = 47.88``), used
#: ONLY where the source uses it: the Magnus ``a`` in psf. Measured: with
#: 47.88 the saturated vapour pressure at 518.67 R reproduces JSBSim's
#: 35.540351 psf; with the exact 47.8802589803 it is 35.5402 (5e-6 off).
JSBSIM_PSF_TO_PA = 47.88
#: Magnus (Sonntag) constants (FGStandardAtmosphere.h ``a, b, c``).
MAGNUS_A_PSF = 611.2 / JSBSIM_PSF_TO_PA
MAGNUS_B = 17.62
MAGNUS_C = 243.12
#: Earth radius for the geopotential conversion (FGStandardAtmosphere.h).
EARTH_RADIUS_FT = 6356766.0 / u.M_PER_FT
#: The 1976 temperature table by GEOPOTENTIAL altitude (ft, R)
#: (FGStandardAtmosphere.cpp ``StdAtmosTemperatureTable``).
TEMPERATURE_TABLE: Tuple[Tuple[float, float], ...] = (
    (0.0, 518.67), (36089.2388, 389.97), (65616.7979, 389.97),
    (104986.8766, 411.57), (154199.4751, 487.17), (167322.8346, 487.17),
    (232939.6325, 386.37), (278385.8268, 336.5028), (298556.4304, 336.5028),
)
#: Record-high water vapour mass fraction, ppm of dry air, by geopotential
#: altitude (FGStandardAtmosphere.cpp ``MaxVaporMassFraction``).
MAX_VAPOUR_PPM_TABLE: Tuple[Tuple[float, float], ...] = (
    (0.0, 35000.0), (3280.8399, 31000.0), (6561.6798, 28000.0),
    (13123.3596, 22000.0), (19685.0394, 8900.0), (26246.7192, 4700.0),
    (32808.3990, 1300.0), (39370.0787, 230.0), (45931.7585, 48.0),
    (52493.4383, 38.0),
)
#: JSBSim's floor for a dew point: -c degC + 1 R (``SetDewPoint``).
MIN_DEW_POINT_R = (-MAGNUS_C + 273.15) * R_PER_K + 1.0

#: The properties, in the order the card carries them.
PROPERTY_DELTA_T = "atmosphere/delta-T"
PROPERTY_P_SL = "atmosphere/P-sl-psf"
PROPERTY_DEW_POINT = "atmosphere/dew-point-R"
PROPERTIES = (PROPERTY_DELTA_T, PROPERTY_P_SL, PROPERTY_DEW_POINT)
#: Read-back tolerance per property (relative), as measured: the bias
#: and the sea-level pressure are stored as written (0); the dew point
#: round-trips through the Magnus form and the mass fraction (an exact
#: algebraic inverse, floating point only: measured 0 before the trim).
READBACK_TOLERANCE = {PROPERTY_DELTA_T: 0.0, PROPERTY_P_SL: 0.0,
                      PROPERTY_DEW_POINT: 1e-9}
#: The same, read back AFTER a step: JSBSim conserves the vapour MASS
#: FRACTION across the step and recomputes the dew point from it at the
#: step's new pressure, so the dew point moves with one step's pressure
#: change (measured: 1.5e-6 R over a 3 s c172p flight, 2.3e-7 R on a 5 s
#: A320 autopilot flight); the bias and the sea-level pressure are exact.
PER_STEP_READBACK_TOLERANCE = {PROPERTY_DELTA_T: 0.0, PROPERTY_P_SL: 0.0,
                               PROPERTY_DEW_POINT: 1e-6}
#: The telemetry columns the atmosphere returns per step (recorded, not
#: graded by Gate 5).
TELEMETRY_COLUMNS = ("density_altitude_m", "pressure_altitude_m", "rh_pct",
                     "vapour_pressure_pa", "temperature_k", "pressure_hpa")
#: The null test's floor: 0.1 % of the reference density -- a +0.3 degC
#: deviation or a 1 hPa pressure change moves density by about this
#: much, and the closed form is checked to 0.5 %.
NULL_DENSITY_FRACTION = 0.001
#: The card block's keys, in the order the host reads them.
CARD_KEYS = (PROPERTY_DELTA_T, PROPERTY_P_SL, PROPERTY_DEW_POINT,
             "applied", "dew_point_rule", "stated")
MODEL = ("JSBSim 1.2.4 FGStandardAtmosphere: temperature bias (delta-T), "
         "off-standard sea-level pressure (P-sl-psf), dew point to vapour "
         "pressure by the Magnus form and a moist gas constant "
         "(dew-point-R); density altitude by the inverted barometric formula")
REFERENCES = (
    "JSBSim v1.2.4 src/models/atmosphere/FGStandardAtmosphere.cpp: "
    "GetTemperature, CalculatePressureBreakpoints, GetPressure, "
    "CalculateVaporPressure, SetVaporPressure, ValidateVaporMassFraction, "
    "CalculateDensityAltitude, CalculatePressureAltitude (fetched, read)",
    "US Standard Atmosphere 1976 (NOAA/NASA/USAF), the temperature table "
    "and layer formulas the source cites [unverified here]",
    "Sonntag, D. (1990), the Magnus-form constants the source cites "
    "(a = 611.2 Pa, b = 17.62, c = 243.12 degC, +/-0.35 degC over "
    "-45..60 degC) [unverified here]",
    "MIL-HDBK-310 (1997) climatic extremes: the 'hot_day' word is a "
    "stated choice inside its 1 % hot column as remembered "
    "[unverified here]; its named profiles are not transcribed",
)


class AtmosphereError(ValueError):
    """A stated atmosphere the model cannot deliver, refused by name."""

    def __init__(self, constraint: str, message: str, actual=None,
                 limit=None, unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


# -- the closed form, in JSBSim's units ----------------------------------------

def geopotential_ft(geometric_ft: float) -> float:
    """``GeopotentialAltitude``: h R / (R + h)."""
    return geometric_ft * EARTH_RADIUS_FT / (EARTH_RADIUS_FT + geometric_ft)


def geometric_ft(geopotential_ft_: float) -> float:
    """``GeometricAltitude``: H R / (R - H)."""
    return geopotential_ft_ * EARTH_RADIUS_FT / (EARTH_RADIUS_FT - geopotential_ft_)


def _table(table, x: float) -> float:
    """FGTable's lookup: linear between rows, held at the ends."""
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def lapse_rates() -> Tuple[float, ...]:
    """R per ft for each layer (``CalculateLapseRates``)."""
    return tuple((t1 - t0) / (h1 - h0)
                 for (h0, t0), (h1, t1) in zip(TEMPERATURE_TABLE,
                                               TEMPERATURE_TABLE[1:]))


def std_temperature_r(altitude_ft: float) -> float:
    """``GetStdTemperature``: the table at the geopotential altitude
    (below sea level: the first layer's lapse rate)."""
    big_h = geopotential_ft(altitude_ft)
    if big_h >= 0.0:
        return _table(TEMPERATURE_TABLE, big_h)
    return TEMPERATURE_TABLE[0][1] + big_h * lapse_rates()[0]


def temperature_r(altitude_ft: float, delta_t_r: float = 0.0) -> float:
    """``GetTemperature`` on the bias route: standard plus the bias."""
    return std_temperature_r(altitude_ft) + delta_t_r


def pressure_breakpoints_psf(sl_pressure_psf: float = P_SL_PSF,
                             delta_t_r: float = 0.0) -> Tuple[float, ...]:
    """``CalculatePressureBreakpoints`` with the biased base temperatures."""
    rates = lapse_rates()
    out = [sl_pressure_psf]
    for b, ((h0, t0), (h1, _)) in enumerate(zip(TEMPERATURE_TABLE,
                                                TEMPERATURE_TABLE[1:])):
        tmb = t0 + delta_t_r
        delta_h = h1 - h0
        if rates[b] != 0.0:
            exponent = G0_FT_S2 / (R_DRY * rates[b])
            out.append(out[b] * (tmb / (tmb + rates[b] * delta_h)) ** exponent)
        else:
            out.append(out[b] * math.exp(-G0_FT_S2 * delta_h / (R_DRY * tmb)))
    return tuple(out)


def _layer(big_h: float) -> int:
    """The table row whose altitude is at or below ``big_h`` (``GetPressure``)."""
    b = 0
    for candidate in range(len(TEMPERATURE_TABLE) - 2):
        if big_h < TEMPERATURE_TABLE[candidate + 1][0]:
            break
        b = candidate + 1
    return b


def pressure_psf(altitude_ft: float, sl_pressure_psf: float = P_SL_PSF,
                 delta_t_r: float = 0.0) -> float:
    """``GetPressure``: the layer formula from the biased breakpoints."""
    big_h = geopotential_ft(altitude_ft)
    b = _layer(big_h)
    base_h, base_t = TEMPERATURE_TABLE[b]
    tmb = base_t + delta_t_r
    lmb = lapse_rates()[b]
    delta_h = big_h - base_h
    breakpoints = pressure_breakpoints_psf(sl_pressure_psf, delta_t_r)
    if lmb != 0.0:
        exponent = G0_FT_S2 / (R_DRY * lmb)
        return breakpoints[b] * (tmb / (tmb + lmb * delta_h)) ** exponent
    return breakpoints[b] * math.exp(-G0_FT_S2 * delta_h / (R_DRY * tmb))


def saturated_vapour_pressure_psf(temperature_r_: float) -> float:
    """``CalculateVaporPressure``: the Magnus form at a temperature."""
    t_c = temperature_r_ / R_PER_K - 273.15
    return MAGNUS_A_PSF * math.exp(MAGNUS_B * t_c / (MAGNUS_C + t_c))


def dew_point_r_of_vapour_pressure(vapour_pressure_psf: float) -> float:
    """``GetDewPoint``: the Magnus form inverted (the floor at zero vapour)."""
    if vapour_pressure_psf <= 0.0:
        return (-MAGNUS_C + 273.15) * R_PER_K
    x = math.log(vapour_pressure_psf / MAGNUS_A_PSF)
    return (MAGNUS_C * x / (MAGNUS_B - x) + 273.15) * R_PER_K


def vapour_mass_fraction(vapour_pressure_psf: float, pressure_psf_: float) -> float:
    """``SetVaporPressure``: f = R_dry e / (R_water (P - e))."""
    return R_DRY * vapour_pressure_psf / (R_WATER * (pressure_psf_ - vapour_pressure_psf))


def vapour_pressure_of_fraction(fraction: float, pressure_psf_: float) -> float:
    """``GetVaporPressure``: e = P f / (f + R_dry / R_water)."""
    return pressure_psf_ * fraction / (fraction + R_DRY / R_WATER)


def max_vapour_mass_fraction(altitude_ft: float,
                             pressure_psf_: Optional[float] = None) -> float:
    """``ValidateVaporMassFraction``'s per-altitude cap, as a fraction.

    JSBSim looks the table up twice with two altitudes: at the PRESSURE
    altitude of the current pressure when the dew point is written
    (``SetVaporPressure``) and at the geometric altitude every step
    (``Calculate``); the fraction is only ever reduced, so the lesser of
    the two applies. Pass the pressure to include the first lookup."""
    cap = 1e-6 * _table(MAX_VAPOUR_PPM_TABLE, geopotential_ft(altitude_ft))
    if pressure_psf_ is not None:
        cap = min(cap, 1e-6 * _table(MAX_VAPOUR_PPM_TABLE,
                                     geopotential_ft(pressure_altitude_ft(pressure_psf_))))
    return cap


def moist_gas_constant(fraction: float) -> float:
    """``Reng = (f R_water + R_dry) / (1 + f)``."""
    return (fraction * R_WATER + R_DRY) / (1.0 + fraction)


def effective_vapour_fraction(dew_point_r: Optional[float], altitude_ft: float,
                              pressure_psf_: float, temperature_r_: float) -> float:
    """The vapour mass fraction JSBSim holds after a dew-point write at
    this altitude: the Magnus vapour pressure of the dew point, capped
    below the ambient pressure, at saturation and at the table."""
    if dew_point_r is None:
        return 0.0
    e = saturated_vapour_pressure_psf(dew_point_r)
    if e >= pressure_psf_:
        e = pressure_psf_ - 1.0
    fraction = vapour_mass_fraction(e, pressure_psf_)
    e_sat = saturated_vapour_pressure_psf(temperature_r_)
    if e_sat < pressure_psf_ and vapour_pressure_of_fraction(fraction, pressure_psf_) > e_sat:
        fraction = vapour_mass_fraction(e_sat, pressure_psf_)
    cap = max_vapour_mass_fraction(altitude_ft, pressure_psf_)
    if fraction > cap or fraction < 0.0:
        fraction = cap
    return fraction


def std_density_breakpoints() -> Tuple[float, ...]:
    """``CalculateStdDensityBreakpoints``: P_b / (R_dry T_b) on the standard day."""
    return tuple(p / (R_DRY * t) for p, (_, t) in zip(pressure_breakpoints_psf(),
                                                       TEMPERATURE_TABLE))


def _inverted_layer(value: float, breakpoints, exponent_of) -> float:
    """The shared inversion of ``CalculateDensityAltitude`` and
    ``CalculatePressureAltitude``: pick the layer by the breakpoints,
    solve the layer formula for H, return the geometric altitude."""
    b = 0
    for candidate in range(len(breakpoints) - 2):
        b = candidate
        if value >= breakpoints[candidate + 1]:
            break
    else:
        b = len(breakpoints) - 2
    base_h, tmb = TEMPERATURE_TABLE[b]
    lmb = lapse_rates()[b]
    pb = breakpoints[b]
    if lmb != 0.0:
        big_h = base_h + (tmb / lmb) * ((value / pb) ** exponent_of(lmb) - 1.0)
    else:
        big_h = base_h - R_DRY * tmb / G0_FT_S2 * math.log(value / pb)
    return geometric_ft(big_h)


def density_altitude_ft(density_slugft3: float) -> float:
    """``CalculateDensityAltitude``: the standard-day altitude with this density."""
    return _inverted_layer(density_slugft3, std_density_breakpoints(),
                           lambda lmb: -1.0 / (1.0 + G0_FT_S2 / (R_DRY * lmb)))


def pressure_altitude_ft(pressure_psf_: float) -> float:
    """``CalculatePressureAltitude``: the standard-day altitude with this pressure."""
    return _inverted_layer(pressure_psf_, pressure_breakpoints_psf(),
                           lambda lmb: -R_DRY * lmb / G0_FT_S2)


# -- the closed form, SI in and out --------------------------------------------

def hpa_to_psf(hpa: float) -> float:
    return hpa * 100.0 / u.PA_PER_PSF


def celsius_to_rankine(c: float) -> float:
    return (c + 273.15) * R_PER_K


def rankine_to_celsius(r: float) -> float:
    return r / R_PER_K - 273.15


def dew_point_c_from_humidity(relative_humidity_pct: float,
                              temperature_c: float) -> Optional[float]:
    """The dew point whose Magnus vapour pressure is RH % of saturation
    at ``temperature_c`` (the inverse Magnus form). RH 0 is dry air: it
    has no dew point (None) -- the Magnus form's floor is a pole, and
    JSBSim's own floor one Rankine above it reads back a different
    value, so zero humidity writes nothing and the model's dry state
    stands."""
    if relative_humidity_pct <= 0.0:
        return None
    e = relative_humidity_pct / 100.0 * saturated_vapour_pressure_psf(
        celsius_to_rankine(temperature_c))
    return rankine_to_celsius(dew_point_r_of_vapour_pressure(e))


def closed_form(altitude_m: float, temperature_deviation_c: float = 0.0,
                sea_level_pressure_hpa: Optional[float] = None,
                dew_point_c: Optional[float] = None) -> Dict[str, float]:
    """The atmosphere JSBSim should deliver at ``altitude_m`` for the stated
    day, from the transcribed equations: temperature, pressure, density,
    the density and pressure altitudes, relative humidity and vapour
    pressure, and ``sigma`` (density over JSBSim's standard sea-level
    density). A ``None`` sea-level pressure means JSBSim's own 2116.228
    psf (the spec's 1013.25 hPa converted with the exact factor is
    2116.2166 psf, 5.4e-6 lower: the spec's own number is used only when
    it states one)."""
    h_ft = u.m_to_ft(altitude_m)
    delta_t_r = temperature_deviation_c * R_PER_K
    p_sl = P_SL_PSF if sea_level_pressure_hpa is None else hpa_to_psf(sea_level_pressure_hpa)
    t_r = temperature_r(h_ft, delta_t_r)
    p = pressure_psf(h_ft, p_sl, delta_t_r)
    dew_r = None if dew_point_c is None else celsius_to_rankine(dew_point_c)
    fraction = effective_vapour_fraction(dew_r, h_ft, p, t_r)
    rho = p / (moist_gas_constant(fraction) * t_r)
    e = vapour_pressure_of_fraction(fraction, p)
    # ``sigma`` is the ratio to the STANDARD day's sea-level density, the
    # density ratio a hot day is judged by. JSBSim's own ``atmosphere/sigma``
    # property divides by the modelled day's sea-level density instead
    # (measured: 1.0 at sea level with delta-T +30 degC), so the two are
    # not the same number and the tests compare densities, not sigmas.
    return {
        "temperature_k": u.rankine_to_kelvin(t_r),
        "pressure_pa": u.psf_to_pa(p),
        "pressure_hpa": u.psf_to_pa(p) / 100.0,
        "density_kgm3": u.slugft3_to_kgm3(rho),
        "sigma": rho / (P_SL_PSF / (R_DRY * T_SL_R)),
        "density_altitude_m": u.ft_to_m(density_altitude_ft(rho)),
        "pressure_altitude_m": u.ft_to_m(pressure_altitude_ft(p)),
        "rh_pct": 100.0 * e / saturated_vapour_pressure_psf(t_r),
        "vapour_pressure_pa": u.psf_to_pa(e),
        "vapour_mass_fraction": fraction,
    }


def expected_density_ratio(temperature_deviation_c: float = 0.0,
                           sea_level_pressure_hpa: Optional[float] = None,
                           dew_point_c: Optional[float] = None,
                           altitude_m: float = 0.0) -> float:
    """``sigma`` = rho / rho_ISA,SL for the stated day at ``altitude_m``
    -- the null test's predicted side, from the same equations."""
    return closed_form(altitude_m, temperature_deviation_c,
                       sea_level_pressure_hpa, dew_point_c)["sigma"]


# -- the refusals -----------------------------------------------------------------

def problems(temperature_deviation_c: Optional[float],
             sea_level_pressure_hpa: Optional[float],
             dew_point_c: Optional[float],
             relative_humidity_pct: Optional[float],
             altitude_m: float) -> List[AtmosphereError]:
    """Every way a stated atmosphere is outside what the model delivers,
    each by name. ``None`` is "not stated" and is never a problem. The
    dew-point checks are made at the scene's initial altitude against
    the modelled temperature there and the vapour cap there, so JSBSim's
    two silent caps are never reached at the start of a flight."""
    out: List[AtmosphereError] = []
    lo, hi = ATMOSPHERE_RANGES["temperature_deviation_c"]
    if temperature_deviation_c is not None and not lo <= temperature_deviation_c <= hi:
        out.append(AtmosphereError(
            "atmosphere.temperature_deviation",
            f"temperature deviation must lie in {lo:g}..{hi:g} degC "
            f"(colder or hotter than any surface day the model is stated for)",
            actual=temperature_deviation_c, limit=f"{lo:g}..{hi:g}", unit="degC"))
    lo, hi = ATMOSPHERE_RANGES["sea_level_pressure_hpa"]
    if sea_level_pressure_hpa is not None and not lo <= sea_level_pressure_hpa <= hi:
        out.append(AtmosphereError(
            "atmosphere.sea_level_pressure",
            f"sea-level pressure must lie in {lo:g}..{hi:g} hPa (the recorded "
            f"extremes, tropical cyclone to Siberian high)",
            actual=sea_level_pressure_hpa, limit=f"{lo:g}..{hi:g}", unit="hPa"))
    if dew_point_c is not None and relative_humidity_pct is not None:
        out.append(AtmosphereError(
            "atmosphere.humidity_conflict",
            "dew point and relative humidity are one quantity stated two "
            "ways; state one of them"))
        return out
    lo, hi = ATMOSPHERE_RANGES["relative_humidity_pct"]
    if relative_humidity_pct is not None and not lo <= relative_humidity_pct <= hi:
        out.append(AtmosphereError(
            "atmosphere.dew_point",
            f"relative humidity must lie in {lo:g}..{hi:g} %",
            actual=relative_humidity_pct, limit=f"{lo:g}..{hi:g}", unit="%"))
        return out
    lo, hi = ATMOSPHERE_RANGES["dew_point_c"]
    if dew_point_c is not None and not lo <= dew_point_c <= hi:
        out.append(AtmosphereError(
            "atmosphere.dew_point",
            f"dew point must lie in {lo:g}..{hi:g} degC",
            actual=dew_point_c, limit=f"{lo:g}..{hi:g}", unit="degC"))
        return out
    if out:
        return out
    delta = 0.0 if temperature_deviation_c is None else temperature_deviation_c
    h_ft = u.m_to_ft(altitude_m)
    t_scene_r = temperature_r(h_ft, delta * R_PER_K)
    t_scene_c = rankine_to_celsius(t_scene_r)
    if relative_humidity_pct is not None:
        dew_point_c = dew_point_c_from_humidity(relative_humidity_pct, t_scene_c)
    if dew_point_c is None:
        return out
    if celsius_to_rankine(dew_point_c) > t_scene_r:
        out.append(AtmosphereError(
            "atmosphere.dew_point",
            f"dew point exceeds the modelled air temperature at the scene "
            f"({t_scene_c:.2f} degC at {altitude_m:.0f} m); JSBSim would "
            f"silently cap it there",
            actual=dew_point_c, limit=t_scene_c, unit="degC"))
        return out
    p_scene = pressure_psf(h_ft, P_SL_PSF if sea_level_pressure_hpa is None
                           else hpa_to_psf(sea_level_pressure_hpa), delta * R_PER_K)
    cap = max_vapour_mass_fraction(h_ft, p_scene)
    e = saturated_vapour_pressure_psf(celsius_to_rankine(dew_point_c))
    if e < p_scene and vapour_mass_fraction(e, p_scene) > cap:
        cap_dew_c = rankine_to_celsius(dew_point_r_of_vapour_pressure(
            vapour_pressure_of_fraction(cap, p_scene)))
        out.append(AtmosphereError(
            "atmosphere.dew_point",
            f"dew point holds more water than the model admits at the "
            f"scene's height (at most {cap * 1e6:.0f} ppm by mass, a dew "
            f"point of {cap_dew_c:.2f} degC at {altitude_m:.0f} m); JSBSim "
            f"would silently cap it",
            actual=dew_point_c, limit=cap_dew_c, unit="degC"))
    return out


def day_problem(word: Any) -> Optional[AtmosphereError]:
    """The ``day`` word, refused by name when it is not in the vocabulary:
    a MIL-HDBK-310 named profile is recognised and refused until it is
    transcribed with provenance; any other word is unknown."""
    if word in DAY_WORDS:
        return None
    if word in NAMED_PROFILES:
        return AtmosphereError(
            "atmosphere.profile",
            f"day {word!r} names a MIL-HDBK-310 profile that has not been "
            f"transcribed with provenance; the words available are "
            f"{sorted(DAY_WORDS)}", actual=word)
    return AtmosphereError(
        "atmosphere.profile",
        f"unknown day word {word!r}; the words available are "
        f"{sorted(DAY_WORDS)}", actual=word)


# -- the provider -------------------------------------------------------------------

@dataclass(frozen=True)
class Stated:
    """One stated variable with its provenance, as the spec carried it."""

    value: float
    source: str = "user"
    frm: Optional[str] = None
    std: Optional[str] = None


def _relatch(fdm) -> None:
    """Recompute the atmosphere at the initial conditions without
    advancing time. ``run_ic`` does exactly that (measured: sim time
    stays 0.0, ``delta-T`` survives it, density updates); the wrapper
    exposes no public re-latch yet, so its executive is used through
    ``relatch_initial_conditions`` when present and directly otherwise."""
    public = getattr(fdm, "relatch_initial_conditions", None)
    if public is not None:
        public()
        return
    fdm._exec.run_ic()


class NonStandardAtmosphere(AtmosphereProvider):
    """The stated day, written before the trim and every step.

    Each argument is ``None`` (not stated: JSBSim's standard day stands
    and nothing is written for it) or a :class:`Stated` / number. The
    relative humidity is stated at the scene's initial altitude
    (``reference_altitude_m``) at the modelled temperature there, and
    resolves to the dew point that is then written. The constructor
    refuses by name what the validator refuses, so a provider that
    exists can always be delivered.
    """

    name = "non_standard_atmosphere"

    def __init__(self, temperature_deviation_c=None, sea_level_pressure_hpa=None,
                 dew_point_c=None, relative_humidity_pct=None,
                 reference_altitude_m: float = 0.0) -> None:
        self.stated: Dict[str, Optional[Stated]] = {
            "temperature_deviation_c": _stated(temperature_deviation_c),
            "sea_level_pressure_hpa": _stated(sea_level_pressure_hpa),
            "dew_point_c": _stated(dew_point_c),
            "relative_humidity_pct": _stated(relative_humidity_pct),
        }
        self.reference_altitude_m = float(reference_altitude_m)
        found = problems(*(None if s is None else s.value for s in self.stated.values()),
                         self.reference_altitude_m)
        if found:
            raise found[0]
        self.delta_t_r: Optional[float] = (
            None if self.stated["temperature_deviation_c"] is None
            else self.stated["temperature_deviation_c"].value * R_PER_K)
        self.p_sl_psf: Optional[float] = (
            None if self.stated["sea_level_pressure_hpa"] is None
            else hpa_to_psf(self.stated["sea_level_pressure_hpa"].value))
        self.dew_point_c: Optional[float] = None
        rh = self.stated["relative_humidity_pct"]
        if rh is not None:
            t_scene_c = rankine_to_celsius(temperature_r(
                u.m_to_ft(self.reference_altitude_m), self.delta_t_r or 0.0))
            self.dew_point_c = dew_point_c_from_humidity(rh.value, t_scene_c)
        elif self.stated["dew_point_c"] is not None:
            self.dew_point_c = self.stated["dew_point_c"].value
        self.dew_point_r: Optional[float] = (
            None if self.dew_point_c is None else celsius_to_rankine(self.dew_point_c))
        #: Per-step bookkeeping (the read-back record): how many steps
        #: were written, how many had the dew point limited, and the
        #: largest read-back error per property across the run.
        self.step_writes = 0
        self.limited_dew_point_steps = 0
        self.readback: Dict[str, Any] = {"steps_checked": 0, "max_abs_error": {}}
        self._last_written: Dict[str, float] = {}
        self._last_temperature_r: Optional[float] = None
        self.prepared: Optional[Dict[str, Any]] = None

    @classmethod
    def from_spec(cls, spec) -> Optional["NonStandardAtmosphere"]:
        """The provider a spec asks for, or None for the standard day
        (a default block applies nothing and records nothing)."""
        block = spec.atmosphere
        if block.is_default():
            return None
        resolved = block.resolved()
        kwargs = {}
        for field in ("temperature_deviation_c", "sea_level_pressure_hpa",
                      "dew_point_c", "relative_humidity_pct"):
            q = resolved[field]
            if q.value is None or str(q.source) == "default":
                kwargs[field] = None
            else:
                kwargs[field] = Stated(float(q.value), str(q.source), q.frm, q.std)
        return cls(reference_altitude_m=float(spec.altitude.value), **kwargs)

    # -- the writes ------------------------------------------------------

    def dew_point_write_r(self, altitude_m: float,
                          jsbsim_temperature_r: Optional[float] = None,
                          ) -> Tuple[Optional[float], Optional[str]]:
        """The dew point to write at this altitude and what limited it:
        the least of the stated dew point, the modelled air temperature
        there and the vapour cap there (JSBSim's own caps, applied here
        so the read-back stays exact and nothing is printed).

        ``SetDewPoint`` checks saturation against the temperature of the
        LAST atmosphere calculation, not this step's (measured: a dew
        point written together with a +20 degC bias, before any
        recomputation, was capped at the pre-bias temperature), so the
        temperature JSBSim currently holds, when given, is a limit too:
        it matters in a saturated descent, where the last step's
        temperature is a few 1e-4 K below this step's."""
        if self.dew_point_r is None:
            return None, None
        h_ft = u.m_to_ft(altitude_m)
        t_r = temperature_r(h_ft, self.delta_t_r or 0.0)
        p = pressure_psf(h_ft, P_SL_PSF if self.p_sl_psf is None else self.p_sl_psf,
                         self.delta_t_r or 0.0)
        cap_r = dew_point_r_of_vapour_pressure(
            vapour_pressure_of_fraction(max_vapour_mass_fraction(h_ft, p), p))
        value, limited = self.dew_point_r, None
        if t_r < value:
            value, limited = t_r, "temperature"
        if jsbsim_temperature_r is not None and jsbsim_temperature_r < value:
            value, limited = jsbsim_temperature_r, "temperature"
        if cap_r < value:
            value, limited = cap_r, "vapour_cap"
        return value, limited

    def writes_at(self, altitude_m: float,
                  jsbsim_temperature_r: Optional[float] = None) -> Dict[str, float]:
        """The property writes for this altitude: only the stated ones."""
        writes: Dict[str, float] = {}
        if self.delta_t_r is not None:
            writes[PROPERTY_DELTA_T] = self.delta_t_r
        if self.p_sl_psf is not None:
            writes[PROPERTY_P_SL] = self.p_sl_psf
        dew, _ = self.dew_point_write_r(altitude_m, jsbsim_temperature_r)
        if dew is not None:
            writes[PROPERTY_DEW_POINT] = dew
        return writes

    def properties(self, position: Position, time_s: float) -> Dict[str, float]:
        """The per-step writes (the stack writes them every step). Counts
        the steps and the dew-point limits; otherwise a pure function of
        the altitude."""
        self.step_writes += 1
        _, limited = self.dew_point_write_r(position.altitude_m, self._last_temperature_r)
        if limited is not None:
            self.limited_dew_point_steps += 1
        writes = self.writes_at(position.altitude_m, self._last_temperature_r)
        self._last_written = dict(writes)
        return writes

    def observe(self, fdm) -> None:
        """Read back what the previous step was given, BEFORE this step's
        write: the record of whether the values survived a JSBSim step.
        Called by the stack at the top of every ``apply``. Also keeps the
        temperature JSBSim holds, the one its next dew-point write is
        checked against."""
        if self.dew_point_r is not None:
            self._last_temperature_r = fdm.props.get("atmosphere/T-R")
        if not self._last_written:
            return
        errors = self.readback["max_abs_error"]
        for prop, written in self._last_written.items():
            read = fdm.props.get(prop)
            errors[prop] = max(errors.get(prop, 0.0), abs(read - written))
        self.readback["steps_checked"] += 1

    # -- before the trim ---------------------------------------------------

    def prepare(self, fdm) -> Dict[str, Any]:
        """Write the day before the trim and measure what each variable
        did: the atmosphere at the initial conditions before any write,
        after each stated variable in turn (temperature deviation, then
        sea-level pressure, then the dew point), and the final read-back
        of every property written against the closed form."""
        altitude_m = fdm.state().altitude_m
        _relatch(fdm)
        before = self._atmosphere_of(fdm)
        steps: List[Dict[str, Any]] = []
        writes = self.writes_at(altitude_m)
        previous = before
        for field, prop in (("temperature_deviation_c", PROPERTY_DELTA_T),
                            ("sea_level_pressure_hpa", PROPERTY_P_SL),
                            ("humidity", PROPERTY_DEW_POINT)):
            if prop not in writes:
                continue
            fdm.props.set(prop, writes[prop])
            _relatch(fdm)
            now = self._atmosphere_of(fdm)
            steps.append({"variable": field, "property": prop,
                          "written": writes[prop], "before": previous, "after": now})
            previous = now
        readback = {}
        for prop, written in writes.items():
            read = fdm.props.get(prop)
            tolerance = READBACK_TOLERANCE[prop]
            error = abs(read - written)
            readback[prop] = {"written": written, "read": read, "abs_error": error,
                              "tolerance_relative": tolerance,
                              "agrees": error <= tolerance * max(1.0, abs(written))}
        predicted = closed_form(
            altitude_m, 0.0 if self.delta_t_r is None else self.delta_t_r / R_PER_K,
            None if self.stated["sea_level_pressure_hpa"] is None
            else self.stated["sea_level_pressure_hpa"].value,
            self.dew_point_c)
        self._last_written = dict(writes)
        self.prepared = {"altitude_m": altitude_m, "before": before, "after": previous,
                         "steps": steps, "readback": readback, "predicted": predicted,
                         "writes": writes}
        return self.prepared

    @staticmethod
    def _atmosphere_of(fdm) -> Dict[str, float]:
        g = fdm.props.get
        return {
            "density_kgm3": u.slugft3_to_kgm3(g("atmosphere/rho-slugs_ft3")),
            "temperature_k": u.rankine_to_kelvin(g("atmosphere/T-R")),
            "pressure_hpa": u.psf_to_pa(g("atmosphere/P-psf")) / 100.0,
            "density_altitude_m": u.ft_to_m(g("atmosphere/density-altitude")),
            "pressure_altitude_m": u.ft_to_m(g("atmosphere/pressure-altitude")),
            "rh_pct": g("atmosphere/RH"),
            "vapour_pressure_pa": u.psf_to_pa(g("atmosphere/vapor-pressure-psf")),
        }

    # -- the records ---------------------------------------------------------

    def applied_variables(self) -> List[AppliedVariable]:
        """One record per stated variable, from the measurements
        ``prepare`` took and the per-step read-back. Refuses to record a
        run that was never prepared: a record without its null test
        would assert what was not measured."""
        if self.prepared is None:
            raise ValueError("NonStandardAtmosphere.prepare(fdm) was never called; "
                             "there is no read-back or null test to record")
        out: List[AppliedVariable] = []
        by_variable = {s["variable"]: s for s in self.prepared["steps"]}
        for field in ("temperature_deviation_c", "sea_level_pressure_hpa",
                      "dew_point_c", "relative_humidity_pct"):
            stated = self.stated[field]
            if stated is None:
                continue
            key = "humidity" if field in ("dew_point_c", "relative_humidity_pct") else field
            if key not in by_variable:
                # RH 0: dry air, the model's own state; nothing was written
                # and the null test honestly measures no difference.
                by_variable[key] = {"variable": key, "property": PROPERTY_DEW_POINT,
                                    "written": None, "before": self.prepared["before"],
                                    "after": self.prepared["before"], "dry": True}
            step = by_variable[key]
            prop = step["property"]
            unit = {"temperature_deviation_c": "degC", "sea_level_pressure_hpa": "hPa",
                    "dew_point_c": "degC", "relative_humidity_pct": "%"}[field]
            without = step["before"]["density_kgm3"]
            with_ = step["after"]["density_kgm3"]
            null = NullTest(
                quantity=f"air density at the initial altitude, {field} applied last",
                unit="kg/m3", with_value=with_, without_value=without,
                threshold=NULL_DENSITY_FRACTION * without,
                note=(("zero humidity is dry air, the model's own state: nothing "
                       "written, no difference to reach; ") if step.get("dry") else "")
                     + (f"measured on the FDM before the trim at "
                        f"{self.prepared['altitude_m']:.1f} m: the atmosphere before "
                        f"and after writing {prop}; threshold {NULL_DENSITY_FRACTION:.1%} "
                        f"of the reference density; closed-form sigma "
                        f"{self.prepared['predicted']['sigma']:.6f}"))
            parameters: Dict[str, Any] = {
                "property": prop,
                "written": step["written"],
                "reference_altitude_m": self.reference_altitude_m,
                "readback": (dict(self.prepared["readback"][prop])
                             if prop in self.prepared["readback"] else None),
                "per_step_readback": {
                    "steps_checked": self.readback["steps_checked"],
                    "max_abs_error": dict(self.readback["max_abs_error"]),
                    "tolerance_relative": {p: PER_STEP_READBACK_TOLERANCE[p]
                                           for p in self.readback["max_abs_error"]},
                    "agrees": all(
                        err <= PER_STEP_READBACK_TOLERANCE[p] * max(1.0, abs(self._last_written.get(p, 1.0)))
                        for p, err in self.readback["max_abs_error"].items()),
                    "basis": ("read before each step's write; the dew point moves "
                              "with one step's pressure change because JSBSim "
                              "conserves the vapour mass fraction"),
                    "steps_written": self.step_writes,
                    "dew_point_limited_steps": self.limited_dew_point_steps},
                "predicted": dict(self.prepared["predicted"]),
                "delivered": dict(self.prepared["after"]),
                "route": "bias (delta-T); the graded delta is not used",
            }
            if field == "relative_humidity_pct":
                parameters["dew_point_c"] = self.dew_point_c
            out.append(AppliedVariable(
                name=f"atmosphere.{field}", value=stated.value, unit=unit,
                source=stated.source, model_name=MODEL, parameters=parameters,
                references=REFERENCES + ((stated.std,) if stated.std else ()),
                properties_written=() if step.get("dry") else (prop,),
                telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                null_test=null,
                not_claimed=(
                    "a MIL-HDBK-310 profile: the words are stated choices",
                    "a temperature inversion, a changed lapse rate or a humidity "
                    "profile with height (the dew point is held constant along "
                    "the flight and limited to the modelled temperature and the "
                    "vapour cap where it would exceed them)",
                    "the US Standard Atmosphere 1976 tables compared here: JSBSim's "
                    "standard day is taken on the source's own word",
                    "the engine side: the card block carries the writes, and no "
                    "host applies them yet",
                )))
        return out

    # -- the card and the vocabulary -------------------------------------------

    def card_block(self) -> Dict[str, Any]:
        """The exact writes for the UE host, in a fixed key order: the
        three properties (null = not written), when to apply them, the
        dew-point rule, and the stated values with their sources."""
        writes = self.writes_at(self.reference_altitude_m)
        return {
            PROPERTY_DELTA_T: writes.get(PROPERTY_DELTA_T),
            PROPERTY_P_SL: writes.get(PROPERTY_P_SL),
            PROPERTY_DEW_POINT: writes.get(PROPERTY_DEW_POINT),
            "applied": "before the trim and every step; a null is not written",
            "dew_point_rule": ("the least of the stated dew point, the modelled "
                               "air temperature at the aircraft's altitude and "
                               "the vapour cap there"),
            "stated": {field: None if s is None else
                       {"value": s.value, "source": s.source, "from": s.frm}
                       for field, s in self.stated.items()},
        }

    def vocabulary(self) -> List[Term]:
        terms = []
        for word, values in DAY_WORDS.items():
            for field, value in (values or {"temperature_deviation_c": 0.0}).items():
                unit = "degC" if field == "temperature_deviation_c" else "%"
                terms.append(Term(word, value, unit, DAY_STANDARDS[word],
                                  valid_range=ATMOSPHERE_RANGES[field]))
        for word in NAMED_PROFILES:
            terms.append(Term(word, "refused", None,
                              "MIL-HDBK-310 named profile, not transcribed",
                              note="refused by name: atmosphere.profile"))
        return terms

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({
            "stated": {f: None if s is None else s.value for f, s in self.stated.items()},
            "dew_point_c": self.dew_point_c,
            "writes_at_reference": self.writes_at(self.reference_altitude_m),
            "reference_altitude_m": self.reference_altitude_m,
            "model": MODEL,
        })
        return out


def _stated(value) -> Optional[Stated]:
    if value is None:
        return None
    if isinstance(value, Stated):
        return value
    return Stated(float(value))
