"""The IR proxy: a stated band radiance per pixel from the class image and
the depth (S3; ADVANCEMENTS_BLUEPRINT section 3, "The chosen way" and
"Models and parameters"). It is a PROXY -- ``proxy: true`` in every block,
record and frame declaration it writes -- and never a thermal simulation.

The model, per palette class c and pixel at range R::

    L_band = tau(R) [eps_c int_band B_lambda(T_c) dlambda + (1 - eps_c) L_down]
             + (1 - tau(R)) B_band(T_air)

* ``B_lambda`` is Planck's law with the SI 2019 exact constants (h, c,
  k_B); ``int_band`` is the band integral on a log-wavelength grid. The
  same integral over 0.1-1000 um times pi is measured against
  Stefan-Boltzmann (sigma formed from the same constants) within
  :data:`PLANCK_INTEGRAL_TOL` (1 %; measured ~1e-6 at 200-1500 K).
* Bands: LWIR 8-12 um and MWIR 3-5 um (:data:`BANDS_UM`), nothing else.
* ``T_c`` per class, each with its source: the airframe's skin at the
  adiabatic-wall recovery temperature ``T_skin = T_inf (1 + r (gamma - 1)
  / 2 M^2)`` with r = 0.89 (the turbulent-boundary-layer recovery factor,
  r = Pr^(1/3) with Pr 0.71 for air [unverified here]) and gamma 1.4, at
  the frame's recorded Mach and air temperature; the terrain classes at
  the near-surface air temperature (the recorded air temperature carried
  down to the scene's terrain elevation by P1's standard lapse,
  core/environment/atmosphere.py), snow capped at 273.15 K; the engine has
  NO temperature (no sub-object temperatures: the class image carries no
  engine pixels); the sky is not a surface (its pixels are L_down).
* ``eps_c`` is the Planck-weighted band emissivity 1 - R/100 of the ASTER
  spectral library row the thermal table cites for the class, read from
  ``assets/emissivity/`` (sha256 sidecar checked on every load; a row
  absent, altered or not in the rows' provenance refuses
  ``sensing.ir_table`` by name -- nothing is invented in its place).
* ``tau(R)`` comes ONLY from a provenanced transmittance table
  (``assets/thermal/<name>.csv`` + ``.sha256`` + ``.provenance.json``),
  linearly interpolated in range; absent, altered, without a provenance,
  or not starting at tau(0) = 1, it refuses ``sensing.ir_transmittance``
  by name. Never Koschmieder in the LWIR, never a constant in code. The
  one table shipped is SYNTHETIC (its provenance says so and every record
  carries ``transmittance.synthetic``); a real MODTRAN / libRadtran table
  for a stated atmosphere and path is the networked step (the README).
  A pixel farther than the table reaches is written unmodelled (NaN) and
  counted, never extrapolated.
* ``L_down``, the stated sky model: a broadband clear-sky effective
  emissivity applied grey across the band at the near-surface air
  temperature -- Brutsaert (1975), eps = 1.24 (e/T)^(1/7) with e in hPa,
  when the recorded vapour pressure is positive; Swinbank (1963), L =
  5.31e-13 T^6 W m^-2, when the air is dry (JSBSim's standard day
  carries no vapour) [both unverified here]. The 8-12 um window's sky is
  colder than a broadband emissivity says; stated, not corrected.
* ``T_air`` on the path: the recorded air temperature at the aircraft
  (an isothermal path, stated).

The frame's proxy image: the ID image's objects mapped to the table's
classes (the airframe to its skin; terrain pixels by the per-pixel land
cover code when one is supplied, else by the nearest engine vertex-colour
palette word when a base-colour pass is declared, else the table's
stated default), the depth turned into range with the frame's own
intrinsics (the depth is planar, view-axis metres), then the equation
above per pixel. Written as ``frame_NNNN_ir.f32`` (float32 LE, row-major,
W m^-2 sr^-1, NaN where unmodelled) beside a ``frame_NNNN_ir.json``
declaration carrying ``proxy: true``, the band and the sha256 of every
table used; the verifier's ``ir_proxy_declared`` grades that declaration
against the manifest's per-camera ``sensing.ir`` block.

What is NOT claimed: no heat balance (no solar loading, conduction,
convection or thermal inertia -- the surfaces sit at the air temperature
and the skin at its recovery temperature), no plume and no engine, no
sub-object temperatures (one temperature per class), no validation
against any IR image, the transmittance table is user-provided (and the
shipped one synthetic), the sky model is broadband, the emissivity rows
are laboratory samples standing in for classes, no sensor (no spectral
response, noise, NETD or MTF), and nothing here is EO/IR sensor fidelity
(docs/VALIDITY.md section 2.5).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
THERMAL_DIR = REPO / "assets" / "thermal"
EMISSIVITY_DIR = REPO / "assets" / "emissivity"
EMISSIVITY_PROVENANCE = "aster_rows.provenance.json"
DEFAULT_THERMAL_TABLE = "proxy_v1"
#: The step that puts a REAL transmittance table where the synthetic one
#: sits (docs in assets/thermal/README.md): a networked, licensed run.
TRANSMITTANCE_STEP = ("a MODTRAN 6 or libRadtran (uvspec) run for the stated atmosphere and "
                      "path, written as assets/thermal/<name>.csv with its sha256 sidecar and a "
                      "provenance whose synthetic is false (assets/thermal/README.md)")
EMISSIVITY_STEP = ("the ASTER / ECOSTRESS spectral library row cached under assets/emissivity/ "
                   "with its sha256 sidecar and an entry in aster_rows.provenance.json "
                   "(assets/emissivity/README.md)")

REFUSAL_TABLE = "sensing.ir_table"
REFUSAL_TRANSMITTANCE = "sensing.ir_transmittance"
REFUSAL_STATE = "sensing.ir_state"

#: The two bands the proxy integrates, micrometres (blueprint section 3).
BANDS_UM: Dict[str, Tuple[float, float]] = {"LWIR": (8.0, 12.0), "MWIR": (3.0, 5.0)}

#: SI 2019 exact defining constants.
PLANCK_H = 6.62607015e-34        # J s
LIGHT_C = 299792458.0            # m / s
BOLTZMANN_K = 1.380649e-23       # J / K
#: First and second radiation constants for spectral RADIANCE: B_lambda =
#: C1 / lambda^5 / (exp(C2 / (lambda T)) - 1), W m^-2 sr^-1 m^-1.
C1 = 2.0 * PLANCK_H * LIGHT_C ** 2
C2 = PLANCK_H * LIGHT_C / BOLTZMANN_K
#: Stefan-Boltzmann formed from the same constants: 2 pi^5 k^4 / (15 h^3 c^2).
STEFAN_BOLTZMANN = 2.0 * math.pi ** 5 * BOLTZMANN_K ** 4 / (15.0 * PLANCK_H ** 3 * LIGHT_C ** 2)
#: The Planck band integral over SB_RANGE_UM times pi against sigma T^4.
PLANCK_INTEGRAL_TOL = 0.01
SB_RANGE_UM = (0.1, 1000.0)

#: The adiabatic-wall recovery factor of a turbulent boundary layer, r =
#: Pr^(1/3) with Pr = 0.71 for air (e.g. Schlichting, Boundary-Layer
#: Theory; laminar r = Pr^(1/2) = 0.84) [unverified here], and the ratio
#: of specific heats of air.
RECOVERY_FACTOR = 0.89
GAMMA_AIR = 1.4
#: Water ice melts at 273.15 K: a snow surface cannot be warmer.
MELTING_POINT_K = 273.15
#: Brutsaert (1975) clear-sky effective emissivity 1.24 (e/T)^(1/7), e in
#: hPa, T in K; Swinbank (1963) clear-sky downwelling 5.31e-13 T^6 W m^-2.
BRUTSAERT_COEFFICIENT = 1.24
BRUTSAERT_EXPONENT = 1.0 / 7.0
SWINBANK_COEFFICIENT = 5.31e-13
SKY_MODELS = ("brutsaert_1975", "swinbank_1963")

TEMPERATURE_MODELS = ("recovery", "near_surface_air", "near_surface_air_below_melting", "none")

#: Class image codes that are not a table class.
SKY = -2
UNMODELLED = -1

REFERENCES = (
    "Planck's law with the SI 2019 exact h, c, k_B; Stefan-Boltzmann formed from them",
    "adiabatic-wall recovery temperature T_inf (1 + r (gamma - 1) / 2 M^2), r = Pr^(1/3) = 0.89 "
    "(turbulent; Schlichting, Boundary-Layer Theory) [unverified here]",
    "Baldridge et al. 2009, The ASTER spectral library version 2.0, Remote Sens. Environ. 113 "
    "(cached rows, sha256 recorded)",
    "Brutsaert 1975, On a derivable formula for long-wave radiation from clear skies, Water "
    "Resour. Res. 11(5) [unverified here]",
    "Swinbank 1963, Long-wave radiation from clear skies, Q. J. R. Meteorol. Soc. 89 [unverified here]",
    "docs/ADVANCEMENTS_BLUEPRINT.md section 3 (the IR proxy)",
)

NOT_CLAIMED = (
    "a proxy, not a thermal simulation: no heat balance (no solar loading, conduction, convection "
    "or thermal inertia); surfaces sit at the near-surface air temperature, the skin at its "
    "recovery temperature",
    "no plume and no engine: no sub-object temperatures, one temperature per class",
    "no validation against any infrared image",
    "the transmittance table is user-provided; the shipped one is synthetic and not an atmosphere",
    "the sky is a broadband clear-sky emissivity applied grey across the band (the 8-12 um window's "
    "sky is colder than that)",
    "the emissivities are laboratory rows standing in for classes (a bare aluminium skin; no paint)",
    "no sensor: no spectral response, noise, NETD or MTF; no EO/IR sensor fidelity (VALIDITY 2.5)",
)


class ThermalError(Exception):
    """A proxy quantity that cannot be formed, refused by name:
    ``sensing.ir_table`` (the thermal table, a band, an emissivity row),
    ``sensing.ir_transmittance`` (the provenanced transmittance table) or
    ``sensing.ir_state`` (the frame's recorded air temperature or Mach)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


# -- Planck ---------------------------------------------------------------------

def planck_spectral_radiance(wavelength_m, temperature_k):
    """B_lambda(T), W m^-2 sr^-1 m^-1 (arrays broadcast)."""
    import numpy as np

    lam = np.asarray(wavelength_m, dtype=np.float64)
    t = np.asarray(temperature_k, dtype=np.float64)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        return C1 / lam ** 5 / np.expm1(C2 / (lam * t))


def band_integral(temperature_k, band_um: Sequence[float], samples: Optional[int] = None):
    """int_band B_lambda(T) dlambda, W m^-2 sr^-1, on a log-wavelength grid
    (trapezoid in ln lambda of B lambda); ``temperature_k`` a number or an
    array (the result has its shape)."""
    import numpy as np

    lo, hi = float(band_um[0]), float(band_um[1])
    if not 0.0 < lo < hi:
        raise ThermalError("sensing.ir_table", f"a band {lo:g}-{hi:g} um is not a positive interval")
    n = samples or max(2001, int(math.ceil(1000.0 * math.log10(hi / lo))) + 1)
    x = np.linspace(math.log(lo * 1e-6), math.log(hi * 1e-6), n)
    lam = np.exp(x)
    t = np.asarray(temperature_k, dtype=np.float64)
    flat = np.atleast_1d(t).reshape(-1)
    values = planck_spectral_radiance(lam[None, :], flat[:, None]) * lam[None, :]
    values = np.where(np.isfinite(values), values, 0.0)
    out = np.trapezoid(values, x, axis=1)
    return float(out[0]) if t.ndim == 0 else out.reshape(t.shape)


def stefan_boltzmann_check(temperatures_k: Sequence[float]) -> List[Dict[str, float]]:
    """pi x the band integral over 0.1-1000 um against sigma T^4, per
    temperature: {temperature_k, integral_w_m2, sigma_t4_w_m2, relative_error}."""
    out = []
    for t in temperatures_k:
        integral = math.pi * band_integral(float(t), SB_RANGE_UM)
        exact = STEFAN_BOLTZMANN * float(t) ** 4
        out.append({"temperature_k": float(t), "integral_w_m2": integral, "sigma_t4_w_m2": exact,
                    "relative_error": abs(integral - exact) / exact})
    return out


# -- temperatures -----------------------------------------------------------------

def _positive(value, what: str) -> float:
    if isinstance(value, bool):
        raise ThermalError("sensing.ir_state", f"{what} must be a number, not {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ThermalError("sensing.ir_state", f"{what} must be a number, not {value!r}")
    if not math.isfinite(number) or number <= 0.0:
        raise ThermalError("sensing.ir_state", f"{what} must be a positive finite number, not {value!r}")
    return number


def skin_temperature(air_temperature_k, mach, recovery_factor: float = RECOVERY_FACTOR,
                     gamma: float = GAMMA_AIR) -> float:
    """The adiabatic-wall recovery temperature T_inf (1 + r (gamma - 1) / 2 M^2)."""
    t = _positive(air_temperature_k, "the air temperature")
    try:
        m = float(mach)
    except (TypeError, ValueError):
        raise ThermalError("sensing.ir_state", f"the Mach number must be a number, not {mach!r}")
    if isinstance(mach, bool) or not math.isfinite(m) or m < 0.0:
        raise ThermalError("sensing.ir_state", f"the Mach number must be finite and not negative, not {mach!r}")
    return t * (1.0 + float(recovery_factor) * (float(gamma) - 1.0) / 2.0 * m * m)


def near_surface_air_temperature(air_temperature_k, altitude_m, ground_elevation_m) -> float:
    """The recorded air temperature carried from the aircraft's altitude to
    the terrain elevation by the standard lapse (P1's JSBSim transcription;
    the day's delta-T is the same at both heights, so it cancels)."""
    from ..environment.atmosphere import std_temperature_r

    t = _positive(air_temperature_k, "the air temperature")
    feet = 1.0 / 0.3048
    difference_r = std_temperature_r(float(ground_elevation_m) * feet) - std_temperature_r(float(altitude_m) * feet)
    return t + difference_r * 5.0 / 9.0


def class_temperature(model: str, *, skin_k: float, ground_air_k: float) -> Optional[float]:
    """T_c by the class's stated model; None for ``none`` (no temperature)."""
    if model == "recovery":
        return float(skin_k)
    if model == "near_surface_air":
        return float(ground_air_k)
    if model == "near_surface_air_below_melting":
        return min(float(ground_air_k), MELTING_POINT_K)
    if model == "none":
        return None
    raise ThermalError("sensing.ir_table", f"unknown temperature model {model!r} (one of {TEMPERATURE_MODELS})")


TEMPERATURE_SOURCES = {
    "recovery": "derived: the adiabatic-wall recovery temperature at the frame's recorded Mach and "
                "air temperature (r 0.89, gamma 1.4)",
    "near_surface_air": "model: the recorded air temperature carried to the terrain elevation by the "
                        "standard lapse (P1); no heat balance",
    "near_surface_air_below_melting": "model: the near-surface air temperature, capped at 273.15 K "
                                      "(a snow surface cannot be warmer than melting)",
    "none": "no temperature: the class has no pixels in the class image (no sub-object temperatures)",
}


# -- the sky -----------------------------------------------------------------------

def sky_downwelling(band_um: Sequence[float], air_temperature_k, vapour_pressure_pa) -> Dict[str, Any]:
    """L_down over the band, W m^-2 sr^-1: eps_sky B_band(T_air), eps_sky by
    Brutsaert (1975) when the vapour pressure is positive, by Swinbank
    (1963) when the air is dry. Both are broadband clear-sky models,
    applied grey across the band (stated)."""
    t = _positive(air_temperature_k, "the near-surface air temperature")
    try:
        e_pa = float(vapour_pressure_pa or 0.0)
    except (TypeError, ValueError):
        raise ThermalError("sensing.ir_state", f"the vapour pressure must be a number, not {vapour_pressure_pa!r}")
    if not math.isfinite(e_pa) or e_pa < 0.0:
        raise ThermalError("sensing.ir_state", f"the vapour pressure must be finite and not negative, not {e_pa!r}")
    e_hpa = e_pa / 100.0
    if e_hpa > 0.0:
        model = "brutsaert_1975"
        eps = BRUTSAERT_COEFFICIENT * (e_hpa / t) ** BRUTSAERT_EXPONENT
        formula = "eps_sky = 1.24 (e / T)^(1/7), e in hPa (Brutsaert 1975)"
    else:
        model = "swinbank_1963"
        eps = SWINBANK_COEFFICIENT * t ** 6 / (STEFAN_BOLTZMANN * t ** 4)
        formula = "L = 5.31e-13 T^6 W m^-2, eps_sky = L / (sigma T^4) (Swinbank 1963; dry air)"
    if not 0.0 < eps <= 1.0:
        raise ThermalError("sensing.ir_state",
                           f"the {model} sky emissivity {eps:.4f} at {t:.2f} K and {e_hpa:.2f} hPa is "
                           f"outside (0, 1]: the model is outside its range")
    return {"model": model, "formula": formula, "effective_emissivity": eps,
            "air_temperature_k": t, "vapour_pressure_hpa": e_hpa,
            "radiance_w_m2_sr": eps * band_integral(t, band_um),
            "basis": "a broadband clear-sky effective emissivity applied grey across the band at the "
                     "near-surface air temperature; the band's sky is colder than this (stated, not "
                     "corrected)"}


# -- the cached tables ------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_checked(path: Path, what: str, constraint: str, step: str) -> bytes:
    """The bytes of a cached table whose ``.sha256`` sidecar matches, or
    ``constraint`` by name: absent, no sidecar, or a digest not the sidecar's."""
    path = Path(path)
    sidecar = path.with_name(path.name + ".sha256")
    if not path.is_file():
        if constraint == "sensing.ir_transmittance":
            raise ThermalError("sensing.ir_transmittance",
                               f"the {what} {path.name} is absent from {path.parent}; nothing is "
                               f"invented in its place -- the step is {step}")
        raise ThermalError("sensing.ir_table",
                           f"the {what} {path.name} is absent from {path.parent}; nothing is "
                           f"invented in its place -- the step is {step}")
    words = sidecar.read_text(encoding="utf-8").split() if sidecar.is_file() else []
    data = path.read_bytes()
    digest = _sha256(data)
    if not words or words[0] != digest:
        said = words[0][:16] if words else "nothing (no sidecar)"
        message = (f"the {what} {path.name} digests {digest[:16]}.. but its sidecar "
                   f"{sidecar.name} says {said}; the cached file is not the one recorded")
        if constraint == "sensing.ir_transmittance":
            raise ThermalError("sensing.ir_transmittance", message)
        raise ThermalError("sensing.ir_table", message)
    return data


@dataclass(frozen=True)
class EmissivityRow:
    file: str
    path: str
    sha256: str
    name: str
    sample: str
    wavelength_um: Tuple[float, ...]
    reflectance_pct: Tuple[float, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {"file": self.file, "sha256": self.sha256, "name": self.name, "sample": self.sample,
                "range_um": [self.wavelength_um[0], self.wavelength_um[-1]],
                "rows": len(self.wavelength_um)}


def _emissivity_provenance(directory: Path) -> Dict[str, Dict[str, Any]]:
    path = directory / EMISSIVITY_PROVENANCE
    if not path.is_file():
        raise ThermalError("sensing.ir_table",
                           f"the emissivity rows carry no provenance ({EMISSIVITY_PROVENANCE} is absent "
                           f"from {directory}); the step is {EMISSIVITY_STEP}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return {str(r["file"]): r for r in document["rows"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ThermalError("sensing.ir_table", f"{EMISSIVITY_PROVENANCE} is unreadable: {exc}") from exc


def load_emissivity_row(file_name: str, directory: Optional[Path] = None) -> EmissivityRow:
    """One ASTER row (directional hemispherical reflectance, percent, over
    wavelength in micrometres) from the cache, sidecar and provenance
    checked; ``sensing.ir_table`` by name otherwise."""
    directory = Path(directory or EMISSIVITY_DIR)
    path = directory / str(file_name)
    data = _read_checked(path, "emissivity row", "sensing.ir_table", EMISSIVITY_STEP)
    provenance = _emissivity_provenance(directory)
    entry = provenance.get(str(file_name))
    if entry is None or entry.get("sha256") != _sha256(data):
        raise ThermalError("sensing.ir_table",
                           f"the emissivity row {file_name} is not the one its provenance records "
                           f"({EMISSIVITY_PROVENANCE}); a row without a recorded source is not used")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise ThermalError("sensing.ir_table", f"the emissivity row {file_name} is not ASCII text")
    header: Dict[str, str] = {}
    pairs: Dict[float, float] = {}
    for line in text.replace("\r", "\n").split("\n"):
        parts = line.split()
        if len(parts) >= 2:
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                x = y = None
            if x is not None:
                pairs.setdefault(x, y)
                continue
        if ":" in line:
            key, value = line.split(":", 1)
            header.setdefault(key.strip().lower(), value.strip())
    x_units = header.get("x units", "").lower()
    y_units = header.get("y units", "").lower()
    if "micrometer" not in x_units or "reflect" not in y_units or "percent" not in y_units:
        raise ThermalError("sensing.ir_table",
                           f"the emissivity row {file_name} is not reflectance in percent over "
                           f"micrometres (X units {x_units!r}, Y units {y_units!r})")
    if len(pairs) < 2:
        raise ThermalError("sensing.ir_table", f"the emissivity row {file_name} holds no data")
    wavelengths = tuple(sorted(pairs))
    return EmissivityRow(file=str(file_name), path=str(path), sha256=_sha256(data),
                         name=header.get("name", ""), sample=header.get("sample no.", ""),
                         wavelength_um=wavelengths,
                         reflectance_pct=tuple(pairs[w] for w in wavelengths))


def band_emissivity(row: EmissivityRow, band_um: Sequence[float], temperature_k: float) -> float:
    """The Planck-weighted band emissivity int eps B / int B over the band,
    eps(lambda) = 1 - R(lambda)/100 (Kirchhoff, an opaque sample), so that
    eps_c int B(T_c) is int eps(lambda) B(lambda, T_c) exactly."""
    import numpy as np

    lo, hi = float(band_um[0]), float(band_um[1])
    if row.wavelength_um[0] > lo or row.wavelength_um[-1] < hi:
        raise ThermalError("sensing.ir_table",
                           f"the emissivity row {row.file} covers {row.wavelength_um[0]:g}-"
                           f"{row.wavelength_um[-1]:g} um, not the band {lo:g}-{hi:g} um")
    grid = np.linspace(lo, hi, 2001)
    reflectance = np.interp(grid, np.asarray(row.wavelength_um), np.asarray(row.reflectance_pct))
    weight = planck_spectral_radiance(grid * 1e-6, float(temperature_k))
    eps = float(np.trapezoid((1.0 - reflectance / 100.0) * weight, grid) / np.trapezoid(weight, grid))
    if not 0.0 <= eps <= 1.0:
        raise ThermalError("sensing.ir_table",
                           f"the emissivity row {row.file} gives a band emissivity {eps:.4f} outside [0, 1]")
    return eps


@dataclass(frozen=True)
class TransmittanceTable:
    name: str
    path: str
    sha256: str
    range_m: Tuple[float, ...]
    tau: Dict[str, Tuple[float, ...]]
    synthetic: bool
    source: str
    provenance: Dict[str, Any]
    provenance_sha256: str

    def at(self, band: str, range_m):
        """tau at each range by linear interpolation in the table; NaN for a
        range that is negative, not finite, or beyond the last row (never
        extrapolated)."""
        import numpy as np

        if band not in self.tau:
            raise ThermalError("sensing.ir_transmittance",
                               f"the transmittance table {self.name} carries no {band} column "
                               f"(columns: {', '.join(self.tau)})")
        r = np.asarray(range_m, dtype=np.float64)
        out = np.interp(r, np.asarray(self.range_m), np.asarray(self.tau[band]))
        bad = ~np.isfinite(r) | (r < 0.0) | (r > self.range_m[-1])
        out = np.where(bad, np.nan, out)
        return float(out) if out.ndim == 0 else out

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "file": Path(self.path).name, "sha256": self.sha256,
                "synthetic": self.synthetic, "source": self.source,
                "provenance_sha256": self.provenance_sha256,
                "range_m": [self.range_m[0], self.range_m[-1]], "rows": len(self.range_m),
                "bands": list(self.tau)}


def load_transmittance(name: str, directory: Optional[Path] = None) -> TransmittanceTable:
    """The provenanced tau(R) table ``<name>.csv`` (``range_m`` then one
    column per band) with its sha256 sidecar and ``<name>.provenance.json``
    (a source, a ``synthetic`` flag, the bands' bounds); anything missing,
    altered or malformed refuses ``sensing.ir_transmittance`` by name."""
    directory = Path(directory or THERMAL_DIR)
    path = directory / f"{name}.csv"
    data = _read_checked(path, "transmittance table", "sensing.ir_transmittance", TRANSMITTANCE_STEP)
    provenance_path = directory / f"{name}.provenance.json"
    if not provenance_path.is_file():
        raise ThermalError("sensing.ir_transmittance",
                           f"the transmittance table {path.name} has no provenance "
                           f"({provenance_path.name}); a table without a stated source is not used")
    try:
        provenance_bytes = provenance_path.read_bytes()
        provenance = json.loads(provenance_bytes.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ThermalError("sensing.ir_transmittance", f"{provenance_path.name} is unreadable: {exc}") from exc
    if not isinstance(provenance, dict) or not isinstance(provenance.get("synthetic"), bool) \
            or not str(provenance.get("source", "")).strip():
        raise ThermalError("sensing.ir_transmittance",
                           f"{provenance_path.name} must state a source and whether the table is "
                           f"synthetic (true or false)")
    if provenance.get("sha256") != _sha256(data):
        raise ThermalError("sensing.ir_transmittance",
                           f"{provenance_path.name} records a digest that is not {path.name}'s")
    lines = [line for line in data.decode("ascii", errors="replace").splitlines() if line.strip()]
    columns = [c.strip() for c in lines[0].split(",")] if lines else []
    if len(columns) < 2 or columns[0] != "range_m" or any(c not in BANDS_UM for c in columns[1:]):
        raise ThermalError("sensing.ir_transmittance",
                           f"{path.name}'s header must be range_m then bands among {sorted(BANDS_UM)}, "
                           f"not {columns}")
    stated = provenance.get("bands_um") or {}
    for band in columns[1:]:
        if [float(v) for v in (stated.get(band) or [])] != list(BANDS_UM[band]):
            raise ThermalError("sensing.ir_transmittance",
                               f"{provenance_path.name} does not state the {band} band as "
                               f"{BANDS_UM[band][0]:g}-{BANDS_UM[band][1]:g} um")
    rows: List[Tuple[float, ...]] = []
    for number, line in enumerate(lines[1:], start=2):
        try:
            values = tuple(float(v) for v in line.split(","))
        except ValueError:
            raise ThermalError("sensing.ir_transmittance", f"{path.name} line {number} is not numeric")
        if len(values) != len(columns) or not all(math.isfinite(v) for v in values):
            raise ThermalError("sensing.ir_transmittance",
                               f"{path.name} line {number} has {len(values)} finite values, not {len(columns)}")
        rows.append(values)
    ranges = tuple(r[0] for r in rows)
    if len(rows) < 2 or ranges[0] != 0.0 or any(b <= a for a, b in zip(ranges, ranges[1:])):
        raise ThermalError("sensing.ir_transmittance",
                           f"{path.name}'s ranges must start at 0 m and increase strictly")
    tau = {band: tuple(r[i + 1] for r in rows) for i, band in enumerate(columns[1:])}
    for band, values in tau.items():
        if any(not 0.0 <= v <= 1.0 for v in values) or values[0] != 1.0:
            raise ThermalError("sensing.ir_transmittance",
                               f"{path.name}'s {band} column must lie in [0, 1] with tau(0 m) = 1")
    return TransmittanceTable(name=name, path=str(path), sha256=_sha256(data), range_m=ranges, tau=tau,
                              synthetic=bool(provenance["synthetic"]), source=str(provenance["source"]),
                              provenance=provenance, provenance_sha256=_sha256(provenance_bytes))


@dataclass(frozen=True)
class ThermalTable:
    name: str
    path: str
    sha256: str
    source: str
    bands: Tuple[str, ...]
    transmittance: str
    classes: Dict[str, Dict[str, Any]]
    objects: Dict[str, str]
    surface_objects: Tuple[str, ...]
    terrain_default: str
    palette: Dict[str, Tuple[float, float, float]]
    landcover: Dict[int, Optional[str]]
    rows: Dict[str, EmissivityRow]
    not_claimed: Tuple[str, ...]

    @property
    def words(self) -> Tuple[str, ...]:
        return tuple(self.classes)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "file": Path(self.path).name, "sha256": self.sha256,
                "source": self.source, "bands": list(self.bands), "transmittance": self.transmittance,
                "terrain_default": self.terrain_default, "proxy": True}


def available_thermal_tables(directory: Optional[Path] = None) -> List[str]:
    return sorted(p.stem for p in Path(directory or THERMAL_DIR).glob("*.json")
                  if not p.name.endswith(".provenance.json"))


def load_thermal_table(name: str = DEFAULT_THERMAL_TABLE, directory: Optional[Path] = None,
                       emissivity_dir: Optional[Path] = None) -> ThermalTable:
    """The thermal table ``assets/thermal/<name>.json``: ``proxy: true``, a
    source, the bands, the transmittance table's name, the classes (each a
    temperature model and an ASTER row or none, with its source), the
    object and land-cover mappings and the engine palette. Every ASTER row
    it names is loaded (sidecar and provenance checked); any problem
    refuses ``sensing.ir_table`` by name."""
    directory = Path(directory or THERMAL_DIR)
    path = directory / f"{name}.json"
    if not path.is_file():
        raise ThermalError("sensing.ir_table",
                           f"no thermal table {name!r} in {directory} (available: "
                           f"{', '.join(available_thermal_tables(directory)) or 'none'})")
    raw = path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ThermalError("sensing.ir_table", f"thermal table {name!r} is unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("name") != name:
        raise ThermalError("sensing.ir_table", f"thermal table {path.name} does not name itself {name!r}")
    if data.get("proxy") is not True:
        raise ThermalError("sensing.ir_table",
                           f"thermal table {name!r} does not declare proxy: true; the IR image is a "
                           f"proxy and must say so")
    if not str(data.get("source", "")).strip():
        raise ThermalError("sensing.ir_table", f"thermal table {name!r} cites no source")
    bands = tuple(str(b) for b in (data.get("bands") or ()))
    if not bands or any(b not in BANDS_UM for b in bands):
        raise ThermalError("sensing.ir_table",
                           f"thermal table {name!r} bands {list(bands)} are not among {sorted(BANDS_UM)}")
    classes = data.get("classes")
    if not isinstance(classes, dict) or not classes:
        raise ThermalError("sensing.ir_table", f"thermal table {name!r} declares no classes")
    rows: Dict[str, EmissivityRow] = {}
    clean: Dict[str, Dict[str, Any]] = {}
    for word, entry in classes.items():
        if not isinstance(entry, dict) or entry.get("temperature_model") not in TEMPERATURE_MODELS:
            raise ThermalError("sensing.ir_table",
                               f"class {word!r} of {name!r} names no temperature model among "
                               f"{TEMPERATURE_MODELS}")
        if not str(entry.get("source", "")).strip():
            raise ThermalError("sensing.ir_table", f"class {word!r} of {name!r} cites no source")
        row = entry.get("emissivity_row")
        if row is not None:
            rows[str(row)] = rows.get(str(row)) or load_emissivity_row(str(row), emissivity_dir)
        clean[str(word)] = {"temperature_model": entry["temperature_model"],
                            "emissivity_row": None if row is None else str(row),
                            "source": str(entry["source"])}
    objects = {str(k): str(v) for k, v in (data.get("objects") or {}).items()}
    surface = tuple(str(s) for s in (data.get("surface_objects") or ()))
    default = str(data.get("terrain_default", ""))
    palette = {str(k): tuple(float(x) for x in v) for k, v in (data.get("palette_linear_rgb") or {}).items()}
    landcover = {int(k): (None if v is None else str(v)) for k, v in (data.get("landcover") or {}).items()}
    for where, word in ([("objects", w) for w in objects.values()] + [("terrain_default", default)]
                        + [("palette", w) for w in palette]
                        + [("landcover", w) for w in landcover.values() if w is not None]):
        if word not in clean:
            raise ThermalError("sensing.ir_table",
                               f"thermal table {name!r} maps {where} to {word!r}, which is not one of its classes")
    if any(len(rgb) != 3 for rgb in palette.values()):
        raise ThermalError("sensing.ir_table", f"thermal table {name!r} palette colours are not RGB triples")
    transmittance = str(data.get("transmittance", "")).strip()
    if not transmittance:
        raise ThermalError("sensing.ir_table", f"thermal table {name!r} names no transmittance table")
    return ThermalTable(name=name, path=str(path), sha256=_sha256(raw), source=str(data["source"]),
                        bands=bands, transmittance=transmittance, classes=clean, objects=objects,
                        surface_objects=surface, terrain_default=default, palette=palette,
                        landcover=landcover, rows=rows,
                        not_claimed=tuple(str(s) for s in (data.get("not_claimed") or ())))


def ir_request_problem(value) -> Optional[ThermalError]:
    """``cameras[i].ir`` = {band, thermal_table}: the shape, the band among
    :data:`BANDS_UM` and carried by the table, the table and its
    transmittance table loading. None when it stands."""
    if not isinstance(value, Mapping) or set(value) != {"band", "thermal_table"}:
        return ThermalError("sensing.ir_table",
                            f"an IR request is a mapping of exactly band and thermal_table, not {value!r}")
    band = value.get("band")
    if band not in BANDS_UM:
        return ThermalError("sensing.ir_table",
                            f"the IR band {band!r} is not one of {sorted(BANDS_UM)} "
                            f"(LWIR 8-12 um, MWIR 3-5 um)")
    try:
        table = load_thermal_table(str(value.get("thermal_table")))
        if band not in table.bands:
            return ThermalError("sensing.ir_table",
                                f"the thermal table {table.name!r} carries no {band} band "
                                f"(it carries {', '.join(table.bands)})")
        load_transmittance(table.transmittance).at(band, 0.0)
    except ThermalError as exc:
        return exc
    return None


def tables_sha256(table: ThermalTable, transmittance: TransmittanceTable) -> Dict[str, str]:
    """The digests the manifest and every frame declaration carry, by role."""
    out = {"thermal_table": table.sha256, "transmittance": transmittance.sha256}
    for file_name, row in sorted(table.rows.items()):
        out[f"emissivity:{file_name}"] = row.sha256
    return out


# -- the proxy image ---------------------------------------------------------------------

def range_from_depth(depth_m, fx_px: float, fy_px: float, cx_px: float, cy_px: float):
    """Planar (view-axis) depth to range along each pixel's ray through
    its centre: z sqrt(1 + ((u - cx)/fx)^2 + ((v - cy)/fy)^2)."""
    import numpy as np

    depth = np.asarray(depth_m, dtype=np.float64)
    h, w = depth.shape
    x = (np.arange(w) + 0.5 - float(cx_px)) / float(fx_px)
    y = (np.arange(h) + 0.5 - float(cy_px)) / float(fy_px)
    return depth * np.sqrt(1.0 + x[None, :] ** 2 + y[:, None] ** 2)


def palette_words(basecolor_rgb, table: ThermalTable):
    """(h, w) indices into ``table.words`` by the nearest engine palette
    colour (linear RGB, squared distance) of a base-colour image."""
    import numpy as np

    if not table.palette:
        raise ThermalError("sensing.ir_table", f"thermal table {table.name!r} carries no palette")
    image = np.asarray(basecolor_rgb, dtype=np.float64)[..., :3]
    names = list(table.palette)
    colours = np.asarray([table.palette[n] for n in names], dtype=np.float64)
    distance = ((image[..., None, :] - colours[None, None, :, :]) ** 2).sum(axis=-1)
    nearest = distance.argmin(axis=-1)
    lookup = np.asarray([table.words.index(n) for n in names])
    return lookup[nearest]


def class_image(mask, depth_m, objects: Sequence[Mapping[str, Any]], table: ThermalTable,
                landcover_codes=None, basecolor_rgb=None) -> Tuple[Any, Dict[str, Any]]:
    """(h, w) int16 indices into ``table.words`` (SKY, UNMODELLED below 0)
    from the ID image and the depth: sky where no object and no depth;
    each object's class through the table's ``objects``; a surface object
    (terrain) by the land cover code per pixel, else the nearest palette
    word of a base-colour image, else the table's default. Returns the
    image and the basis of the surface words."""
    import numpy as np

    ids = np.asarray(mask)
    depth = np.asarray(depth_m, dtype=np.float64)
    out = np.full(ids.shape, UNMODELLED, dtype=np.int16)
    out[(ids == 0) & ~np.isfinite(depth)] = SKY
    words = table.words
    if landcover_codes is not None:
        codes = np.asarray(landcover_codes)
        surface = np.full(ids.shape, UNMODELLED, dtype=np.int16)
        for code, word in table.landcover.items():
            if word is not None:
                surface[codes == code] = words.index(word)
        basis = "the per-pixel land cover code (ESA WorldCover legend) through the table's landcover map"
    elif basecolor_rgb is not None:
        surface = palette_words(basecolor_rgb, table).astype(np.int16)
        basis = "the nearest engine vertex-colour palette word of the base-colour pass"
    else:
        surface = np.full(ids.shape, words.index(table.terrain_default), dtype=np.int16)
        basis = (f"no land cover image and no base-colour pass: every surface pixel is the table's "
                 f"default {table.terrain_default!r}")
    for entry in objects:
        int_id = int(entry.get("int_id", -1))
        cls = str(entry.get("class", entry.get("class_name", "")))
        where = ids == int_id
        if int_id <= 0 or not where.any():
            continue
        if cls in table.surface_objects:
            out[where] = surface[where]
        elif cls in table.objects:
            out[where] = words.index(table.objects[cls])
    return out, {"surface": basis}


def proxy_radiance(index_image, range_m, table: ThermalTable, transmittance: TransmittanceTable,
                   band: str, temperatures_k: Mapping[str, Optional[float]],
                   emissivity: Mapping[str, Optional[float]], air_temperature_k: float,
                   l_down: float, tau_one: bool = False, eps_one: bool = False):
    """The band radiance image (W m^-2 sr^-1) and its pixel summary:
    L = tau(R) [eps_c B_band(T_c) + (1 - eps_c) L_down] + (1 - tau(R)) B_band(T_air)
    per class pixel, L_down on sky, NaN where unmodelled (no class, a
    class without a temperature or a row, or a range beyond the table).
    ``tau_one`` / ``eps_one`` are the two null tests' switches."""
    import numpy as np

    classes = np.asarray(index_image)
    ranges = np.asarray(range_m, dtype=np.float64)
    out = np.full(classes.shape, np.nan, dtype=np.float64)
    b_air = band_integral(float(air_temperature_k), BANDS_UM[band])
    tau = np.ones(classes.shape) if tau_one else transmittance.at(band, ranges)
    counts: Dict[str, int] = {}
    unmodelled_classes: Dict[str, int] = {}
    for k, word in enumerate(table.words):
        where = classes == k
        n = int(where.sum())
        if not n:
            continue
        counts[word] = n
        t_c = temperatures_k.get(word)
        eps = 1.0 if eps_one else emissivity.get(word)
        if t_c is None or eps is None:
            unmodelled_classes[word] = n
            continue
        b = band_integral(float(t_c), BANDS_UM[band])
        t = tau[where]
        out[where] = t * (eps * b + (1.0 - eps) * l_down) + (1.0 - t) * b_air
    sky = classes == SKY
    out[sky] = l_down
    surfaces = classes >= 0
    beyond = int((surfaces & ~np.isfinite(tau)).sum())
    return out, {"class_pixels": counts, "sky_px": int(sky.sum()),
                 "unlabelled_px": int((classes == UNMODELLED).sum()),
                 "unmodelled_class_px": unmodelled_classes, "beyond_table_px": beyond,
                 "b_band_air_w_m2_sr": b_air}


# -- per frame, per camera ---------------------------------------------------------------

def frame_ir_state(frame: Mapping[str, Any], ground_elevation_m: float) -> Dict[str, Any]:
    """The recorded quantities a frame's proxy is evaluated at: air
    temperature, Mach, vapour pressure and altitude from ``frame.state``,
    the skin temperature, the near-surface air temperature and the range
    from the camera to the aircraft's CG."""
    state = frame.get("state") or {}
    missing = [k for k in ("temperature_k", "mach", "altitude_m") if k not in state]
    if missing:
        raise ThermalError("sensing.ir_state",
                           f"frame {frame.get('index')} of {frame.get('camera_id')} records no "
                           f"{', '.join(missing)}; the proxy is evaluated at the recorded state")
    air = _positive(state["temperature_k"], "the recorded air temperature")
    skin = skin_temperature(air, state["mach"])
    ground_air = near_surface_air_temperature(air, state["altitude_m"], ground_elevation_m)
    aircraft = frame.get("aircraft") or {}
    try:
        cg_range = math.sqrt((float(frame["position_north_m"]) - float(aircraft["north_m"])) ** 2
                             + (float(frame["position_east_m"]) - float(aircraft["east_m"])) ** 2
                             + (float(frame["position_alt_m"]) - float(aircraft["alt_m"])) ** 2)
    except (KeyError, TypeError, ValueError):
        cg_range = None
    return {"air_temperature_k": air, "mach": float(state["mach"]), "t_skin_k": skin,
            "altitude_m": float(state["altitude_m"]),
            "vapour_pressure_pa": float(state.get("vapour_pressure_pa") or 0.0),
            "ground_air_temperature_k": ground_air, "cg_range_m": cg_range}


def class_values(table: ThermalTable, band: str, skin_k: float, ground_air_k: float
                 ) -> Tuple[Dict[str, Optional[float]], Dict[str, Optional[float]]]:
    """({word: T_c or None}, {word: band emissivity at T_c, or None})."""
    temperatures: Dict[str, Optional[float]] = {}
    emissivity: Dict[str, Optional[float]] = {}
    for word, entry in table.classes.items():
        t_c = class_temperature(entry["temperature_model"], skin_k=skin_k, ground_air_k=ground_air_k)
        temperatures[word] = t_c
        row = entry["emissivity_row"]
        emissivity[word] = (None if row is None or t_c is None
                            else band_emissivity(table.rows[row], BANDS_UM[band], t_c))
    return temperatures, emissivity


def frame_ir_keys(state: Mapping[str, Any], transmittance: TransmittanceTable, band: str) -> Dict[str, Any]:
    """The per-frame ``ir`` keys of the capture manifest."""
    tau = None
    if state.get("cg_range_m") is not None:
        value = transmittance.at(band, state["cg_range_m"])
        tau = None if not math.isfinite(value) else value
    return {"proxy": True, "band": band, "t_skin_k": state["t_skin_k"], "mach": state["mach"],
            "air_temperature_k": state["air_temperature_k"],
            "ground_air_temperature_k": state["ground_air_temperature_k"],
            "cg_range_m": state["cg_range_m"], "tau_cg": tau, "file": None,
            "basis": "no IR frame until a render's ID image and depth exist (the post-pass writes "
                     "frame_NNNN_ir.f32 and its declaration)"}


def attach_frame_ir(block: Mapping[str, Any], frames: Sequence[Dict[str, Any]],
                    ground_elevation_m: float = 0.0) -> None:
    """Set each of the camera's frame records' ``ir`` keys (T_skin at the
    frame's Mach, tau at its CG range, ``file`` null until a render)."""
    transmittance = load_transmittance(str(block["transmittance"]["name"]))
    for frame in frames:
        frame["ir"] = frame_ir_keys(frame_ir_state(frame, ground_elevation_m), transmittance,
                                    str(block["band"]))


def camera_ir_block(camera, frames: Sequence[Mapping[str, Any]], ground_elevation_m: float = 0.0
                    ) -> Optional[Dict[str, Any]]:
    """The per-camera ``sensing.ir`` block, or None when the camera asked
    for no IR proxy (absent-canonical). Evaluated at the camera's first
    frame (the reference frame): T_skin at its Mach, tau at its CG range,
    the class temperatures and emissivities, the sky. Refuses by name
    (``sensing.ir_table``, ``sensing.ir_transmittance``, ``sensing.ir_state``)."""
    q = getattr(camera, "ir", None)
    request = getattr(q, "value", None)
    if request is None:
        return None
    problem = ir_request_problem(request)
    if problem is not None:
        raise problem
    band = str(request["band"])
    table = load_thermal_table(str(request["thermal_table"]))
    transmittance = load_transmittance(table.transmittance)
    if not frames:
        raise ThermalError("sensing.ir_state",
                           f"camera {getattr(camera.camera_id, 'value', '?')} captures no frame; the "
                           f"proxy has no recorded state to be evaluated at")
    reference = frames[0]
    state = frame_ir_state(reference, ground_elevation_m)
    temperatures, emissivity = class_values(table, band, state["t_skin_k"], state["ground_air_temperature_k"])
    sky = sky_downwelling(BANDS_UM[band], state["ground_air_temperature_k"], state["vapour_pressure_pa"])
    keys = frame_ir_keys(state, transmittance, band)
    check = stefan_boltzmann_check([state["t_skin_k"]])[0]
    return {
        "proxy": True,
        "requested_by": "camera",
        "request": dict(request),
        "band": band,
        "band_um": list(BANDS_UM[band]),
        "unit": "W m^-2 sr^-1",
        "model": "L = tau(R) [eps_c int_band B(T_c) + (1 - eps_c) L_down] + (1 - tau(R)) B_band(T_air)",
        "thermal_table": table.to_dict(),
        "transmittance": transmittance.to_dict(),
        "emissivity_rows": {f: r.to_dict() for f, r in sorted(table.rows.items())},
        "tables_sha256": tables_sha256(table, transmittance),
        "recovery_factor": RECOVERY_FACTOR,
        "gamma": GAMMA_AIR,
        "ground_elevation_m": float(ground_elevation_m),
        "reference_frame": {"index": reference.get("index"), "t_s": reference.get("t_s"),
                            **{k: keys[k] for k in ("t_skin_k", "mach", "air_temperature_k",
                                                    "ground_air_temperature_k", "cg_range_m", "tau_cg")},
                            "vapour_pressure_pa": state["vapour_pressure_pa"]},
        "class_temperatures_k": {w: {"value": temperatures[w],
                                     "source": TEMPERATURE_SOURCES[table.classes[w]["temperature_model"]],
                                     "class_source": table.classes[w]["source"]} for w in table.words},
        "class_emissivity": {w: {"value": emissivity[w], "row": table.classes[w]["emissivity_row"]}
                             for w in table.words},
        "sky": sky,
        "planck_check": {"range_um": list(SB_RANGE_UM), "tolerance": PLANCK_INTEGRAL_TOL, **check},
        "solar_loading": {"applied": False,
                          "basis": "no heat balance: no normal pass exists here (S4) and no class "
                                   "states a solar term; the surfaces sit at the air temperature"},
        "frames": "per frame: frames[].ir {t_skin_k, cg_range_m, tau_cg, file}; the image "
                  "frame_NNNN_ir.f32 with frame_NNNN_ir.json once a render's ID image and depth exist",
        "references": list(REFERENCES),
        "not_claimed": list(NOT_CLAIMED) + list(table.not_claimed),
    }


# -- the records -------------------------------------------------------------------------

def _synthetic_strip(block: Mapping[str, Any], table: ThermalTable, transmittance: TransmittanceTable):
    """A synthetic bundle for the null tests: one row of pixels of every
    class with a temperature and a row, each at the table's own range
    rows, evaluated at the block's reference state. Returns (image,
    ranges, temperatures, emissivity, air, l_down)."""
    import numpy as np

    band = str(block["band"])
    ref = block["reference_frame"]
    temperatures, emissivity = class_values(table, band, float(ref["t_skin_k"]),
                                            float(ref["ground_air_temperature_k"]))
    usable = [k for k, w in enumerate(table.words)
              if temperatures[w] is not None and emissivity[w] is not None]
    ranges_row = np.asarray(transmittance.range_m, dtype=np.float64)
    image = np.repeat(np.asarray(usable, dtype=np.int16)[:, None], len(ranges_row), axis=1)
    ranges = np.repeat(ranges_row[None, :], len(usable), axis=0)
    return (image, ranges, temperatures, emissivity, float(ref["air_temperature_k"]),
            float(block["sky"]["radiance_w_m2_sr"]))


def ir_records(block: Mapping[str, Any]) -> List[Any]:
    """The two AppliedVariables the IR block returns (record 2), each null
    test MEASURED here on a synthetic bundle (every modelled class at every
    range row of the table):

    * ``sensing.ir`` -- value T_skin (K) at the reference frame's Mach;
      readback T_skin recomputed from the frame's recorded Mach and air
      temperature (tolerance 0); null test eps = 1 on a unit-transmittance
      path gives the Planck map of the class temperatures (``bounded``, 0).
    * ``sensing.ir_transmittance`` -- value tau at the CG range; readback
      tau re-interpolated from the cached table (tolerance 0); null test
      tau = 1 against tau(R): the radiance difference at the table's last
      range (with) against at 0 m (without, exactly 0), ``reached`` at half
      its analytic value; the difference by range is recorded and must
      grow with range (``grows_with_range``)."""
    import numpy as np
    from ..records import AppliedVariable, Model, NullTest, Readback

    band = str(block["band"])
    table = load_thermal_table(str(block["thermal_table"]["name"]))
    transmittance = load_transmittance(str(block["transmittance"]["name"]))
    ref = block["reference_frame"]
    image, ranges, temperatures, emissivity, air, l_down = _synthetic_strip(block, table, transmittance)
    planck, _ = proxy_radiance(image, ranges, table, transmittance, band, temperatures, emissivity,
                               air, l_down, tau_one=True, eps_one=True)
    expected = np.empty_like(planck)
    for k, word in enumerate(table.words):
        where = image == k
        if where.any():
            expected[where] = band_integral(float(temperatures[word]), BANDS_UM[band])
    planck_error = float(np.nanmax(np.abs(planck - expected)))
    with_tau, _ = proxy_radiance(image, ranges, table, transmittance, band, temperatures, emissivity,
                                 air, l_down)
    without_tau, _ = proxy_radiance(image, ranges, table, transmittance, band, temperatures, emissivity,
                                    air, l_down, tau_one=True)
    difference = np.abs(with_tau - without_tau).max(axis=0)          # per range row
    by_range = [{"range_m": float(r), "max_abs_difference_w_m2_sr": float(d)}
                for r, d in zip(transmittance.range_m, difference)]
    grows = bool(all(b >= a for a, b in zip(difference, difference[1:])))
    b_air = band_integral(air, BANDS_UM[band])
    predicted = max(float(abs(without_tau[i, -1] - b_air)) * (1.0 - transmittance.tau[band][-1])
                    for i in range(image.shape[0]))
    skin_again = skin_temperature(float(ref["air_temperature_k"]), float(ref["mach"]))
    tau_again = (None if ref.get("cg_range_m") is None
                 else transmittance.at(band, float(ref["cg_range_m"])))
    tau_value = ref.get("tau_cg")
    common = {"band": band, "band_um": list(BANDS_UM[band]), "proxy": True,
              "tables_sha256": dict(block["tables_sha256"]),
              "transmittance_synthetic": bool(block["transmittance"]["synthetic"])}
    ir = AppliedVariable(
        name="sensing.ir", value=float(ref["t_skin_k"]), unit="K", source="derived",
        model=str(block["model"]),
        parameters=dict(common, t_skin_k=float(ref["t_skin_k"]), mach=float(ref["mach"]),
                        air_temperature_k=float(ref["air_temperature_k"]),
                        recovery_factor=RECOVERY_FACTOR, gamma=GAMMA_AIR,
                        class_temperatures_k={w: v["value"] for w, v in block["class_temperatures_k"].items()},
                        class_emissivity={w: v["value"] for w, v in block["class_emissivity"].items()},
                        sky_model=block["sky"]["model"], l_down_w_m2_sr=block["sky"]["radiance_w_m2_sr"],
                        planck_check=dict(block["planck_check"])),
        references=tuple(block["references"]),
        frame_keys=("ir.t_skin_k", "ir.tau_cg", "ir.file"),
        null_test=NullTest(
            quantity="max |proxy with eps = 1 and tau = 1 - B_band(T_c)|", unit="W m^-2 sr^-1",
            with_value=planck_error, without_value=0.0, threshold=0.0, kind="bounded",
            note="eps = 1 on a unit-transmittance path returns the Planck map of the class "
                 "temperatures; measured on the synthetic bundle (every modelled class at every "
                 "range row of the table)"),
        not_claimed=tuple(block["not_claimed"]),
        frm=f"the reference frame's recorded Mach {float(ref['mach']):.4f} and air temperature "
            f"{float(ref['air_temperature_k']):.2f} K",
        std="adiabatic-wall recovery, r = Pr^(1/3) = 0.89 [unverified here]; ASTER library rows (cached)",
        readback=Readback(property="t_skin_k", value=float(skin_again), written=float(ref["t_skin_k"]),
                          tolerance=0.0, tolerance_kind="absolute",
                          basis="T_skin recomputed from the frame's recorded Mach and air temperature "
                                "equals the block's"),
        model_block=Model(name="IR band radiance proxy", standard="Planck (SI 2019 constants)",
                          version=str(block["thermal_table"]["name"]),
                          parameters={"recovery_factor": RECOVERY_FACTOR, "gamma": GAMMA_AIR,
                                      "band_um": list(BANDS_UM[band])},
                          references=tuple(block["references"])),
    )
    records = [ir]
    if tau_value is not None and tau_again is not None:
        records.append(AppliedVariable(
            name="sensing.ir_transmittance", value=float(tau_value), unit="1", source="derived",
            model=f"tau(R) interpolated linearly in the provenanced table {transmittance.name} "
                  f"({'SYNTHETIC' if transmittance.synthetic else 'stated source'})",
            parameters=dict(common, cg_range_m=float(ref["cg_range_m"]),
                            transmittance=dict(block["transmittance"]),
                            null_by_range=by_range, grows_with_range=grows,
                            predicted_far_difference_w_m2_sr=predicted),
            references=(str(transmittance.source),),
            frame_keys=("ir.cg_range_m", "ir.tau_cg"),
            null_test=NullTest(
                quantity="max |L with tau(R) - L with tau = 1| at the table's last range, against at 0 m",
                unit="W m^-2 sr^-1", with_value=float(difference[-1]), without_value=float(difference[0]),
                threshold=0.5 * predicted, kind="reached",
                note=f"the difference grows with range ({'measured monotone' if grows else 'NOT monotone'} "
                     f"over the {len(by_range)} range rows); threshold half the analytic "
                     f"(1 - tau) |L_surface - B_band(T_air)| at the last row"),
            not_claimed=(("the table is SYNTHETIC: not an atmosphere, it exercises the plumbing only"
                          if transmittance.synthetic else "the table is the user's; it is not checked "
                                                          "against any measurement here"),
                         "never Koschmieder in the LWIR; never extrapolated beyond the last row",
                         "an isothermal path at the recorded air temperature"),
            frm=f"the CG range {float(ref['cg_range_m']):.2f} m at the reference frame",
            std=str(transmittance.source),
            readback=Readback(property="tau_cg", value=float(tau_again), written=float(tau_value),
                              tolerance=0.0, tolerance_kind="absolute",
                              basis="tau re-interpolated from the cached table at the CG range equals "
                                    "the block's"),
        ))
    return records


# -- after a render: the frames ------------------------------------------------------------

def _read_basecolor(path: Path, width: int, height: int):
    import numpy as np

    raw = np.fromfile(path, dtype="<f4")
    if raw.size != width * height * 3:
        return None
    return raw.reshape(height, width, 3)


def _write_preview(run_dir: Path, camera: str, stem: str, radiance) -> Dict[str, Any]:
    """The human-inspection preview (the Windows clause: one real render's
    IR preview looked at once): ``ir_preview/<camera>/<stem>_ir.png``, 8-bit
    grey stretched linearly between the frame's own finite minimum and
    maximum, unmodelled pixels black. A display, not data."""
    import numpy as np
    from PIL import Image

    finite = np.isfinite(radiance)
    lo = float(radiance[finite].min()) if finite.any() else 0.0
    hi = float(radiance[finite].max()) if finite.any() else 0.0
    span = hi - lo if hi > lo else 1.0
    grey = np.where(finite, np.clip((np.nan_to_num(radiance) - lo) / span, 0.0, 1.0) * 255.0, 0.0)
    path = run_dir / "ir_preview" / camera / f"{stem}_ir.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.round(grey).astype(np.uint8)).save(path)
    return {"file": str(path.relative_to(run_dir).as_posix()), "stretch_w_m2_sr": [lo, hi],
            "note": "display only: a linear grey stretch of this frame's own range, NaN black"}


def render_ir_frames(run_dir, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """After a render: for every camera whose manifest block carries
    ``sensing.ir`` and every frame whose render bundle declares an ID image
    and a depth, write ``frame_NNNN_ir.f32`` (float32 LE, W m^-2 sr^-1, NaN
    unmodelled) and ``frame_NNNN_ir.json`` (the declaration: proxy true,
    the band, every table's sha256 as loaded now, the pixel summary) and
    set the frame record's ``ir.file``. A frame without a bundle keeps
    ``file: null``. Returns {cameras, written, without_bundle}."""
    import numpy as np
    from .labels import _bundle_records, _read_id_png, read_depth_f32, read_depth_png

    run_dir = Path(run_dir)
    summary: Dict[str, Any] = {"cameras": 0, "written": 0, "without_bundle": 0}
    objects = manifest.get("objects") or []
    for block in manifest.get("cameras", []) or []:
        ir = (block.get("sensing") or {}).get("ir") if isinstance(block, dict) else None
        if not isinstance(ir, dict):
            continue
        summary["cameras"] += 1
        camera = str(block["camera_id"])
        band = str(ir["band"])
        table = load_thermal_table(str(ir["thermal_table"]["name"]))
        transmittance = load_transmittance(table.transmittance)
        digests = tables_sha256(table, transmittance)
        folder = run_dir / "frames" / camera
        bundles = _bundle_records(folder)
        ground = float(ir.get("ground_elevation_m") or 0.0)
        for frame in manifest.get("frames", []):
            if str(frame.get("camera_id")) != camera:
                continue
            record = bundles.get(Path(str(frame["file"])).name)
            labels = (record or {}).get("labels") or {}
            if not labels.get("mask") or not (labels.get("depth_f32") or labels.get("depth")):
                summary["without_bundle"] += 1
                continue
            width, height = int(frame["width_px"]), int(frame["height_px"])
            mask = _read_id_png(folder / str(labels["mask"]))
            if labels.get("depth_f32"):
                depth = read_depth_f32(folder / str(labels["depth_f32"]), width, height)
            else:
                depth = read_depth_png(folder / str(labels["depth"]),
                                       float(labels.get("depth_scale_m", 0.1)),
                                       float(labels.get("depth_saturation_m", 6553.5)))
            basecolor = None
            if str(labels.get("basecolor", "")).endswith(".f32"):
                basecolor = _read_basecolor(folder / str(labels["basecolor"]), width, height)
            images, basis = class_image(mask, depth, objects, table, basecolor_rgb=basecolor)
            ranges = range_from_depth(depth, frame["fx_px"], frame["fy_px"],
                                      *frame["principal_point_px"])
            state = frame_ir_state(frame, ground)
            temperatures, emissivity = class_values(table, band, state["t_skin_k"],
                                                    state["ground_air_temperature_k"])
            sky = sky_downwelling(BANDS_UM[band], state["ground_air_temperature_k"],
                                  state["vapour_pressure_pa"])
            radiance, pixels = proxy_radiance(images, ranges, table, transmittance, band, temperatures,
                                              emissivity, state["air_temperature_k"],
                                              sky["radiance_w_m2_sr"])
            stem = Path(str(frame["file"])).stem
            f32 = folder / f"{stem}_ir.f32"
            data = radiance.astype("<f4").tobytes()
            f32.write_bytes(data)
            declaration = {
                "proxy": True, "band": band, "band_um": list(BANDS_UM[band]), "unit": "W m^-2 sr^-1",
                "file": f32.name, "sha256": _sha256(data), "width_px": width, "height_px": height,
                "dtype": "float32 little-endian, row-major; NaN where unmodelled",
                "frame": Path(str(frame["file"])).name, "t_s": frame.get("t_s"),
                "tables_sha256": digests, "sky": sky, "t_skin_k": state["t_skin_k"],
                "surface_basis": basis["surface"], "pixels": pixels,
                "sources": {"mask": str(labels["mask"]),
                            "depth": str(labels.get("depth_f32") or labels.get("depth"))},
                "not_claimed": list(NOT_CLAIMED),
            }
            declaration["preview"] = _write_preview(run_dir, camera, stem, radiance)
            (folder / f"{stem}_ir.json").write_text(json.dumps(declaration, indent=1), encoding="utf-8")
            if isinstance(frame.get("ir"), dict):
                frame["ir"]["file"] = f32.name
                frame["ir"]["basis"] = "written from the render's ID image and depth"
            summary["written"] += 1
    return summary
