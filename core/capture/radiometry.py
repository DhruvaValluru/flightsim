"""The calibration chain: what one unit of the linear frame is worth, in
candela per square metre, and the band proxy over it (S1; gap S1;
ADVANCEMENTS_BLUEPRINT section 3, "Corrections applied").

The engine renders through a manual exposure at EV100 (core/capture/
exposure.py; the same formula in FlightSimVisualScene.cpp). Under ISO
2720 (H = q t L / N^2, q = 0.65) and ISO 12232:2019 (S_sat = 78 / H_sat),
the scene luminance that saturates the sensor at ISO 100 is L_max =
2^EV100 x 78 / (q x 100) = 1.2 x 2^EV100 cd/m^2 (Lagarde & de Rousiers
2014, section 5.1). Unreal's manual exposure divides by one more factor,
the lens attenuation ``r.EyeAdaptation.LensAttenuation`` (default 0.78;
the skeptic's recomputation of Epic's own worked example needs it), so
the value the linear frame carries is

    v = L_v / (1.2 x A x 2^(EV100 - EC))

with EC the camera's exposure compensation in stops (+1 EC halves the
luminance a unit stands for, so the picture doubles). The chain's
constant, ``luminance_cd_m2_per_unit`` = 1.2 x A x 2^(EV100 - EC), is
what every frame records; it is PREDICTED here (A is the console
variable's documented default, or its read-back from render.json when
a render exists) and becomes MEASURED only when the engine's grey-card
calibration frame (S4, a Windows step) writes ``calibration.json``
beside the bundle and the ratio measured / predicted is within the
tolerance the verifier states. Nothing in this container has measured
it, and the status says so.

The band proxy. The frame is three photometric channels, not a spectrum.
A band radiance in W m^-2 sr^-1 is formed as L_e,band = L_v,ch / (683 x
K_band) where K_band = integral(S V w_band) / integral(S w_band) is the
luminous efficiency of the STATED illuminant spectrum S (ASTM G173-03
direct + circumsolar) within the band's declared window w_band under CIE
1924 V(lambda). Both tables are read from the cached files
``assets/cie/vlambda_1nm.csv`` and ``assets/illuminants/astm_g173_direct.csv``
(sha256 sidecars checked on every load; scripts/fetch_sensing_tables.py
is the step that puts them there) and from NOWHERE ELSE: a build without
them refuses ``sensing.radiometry`` (a table absent or its digest wrong)
and ``sensing.band`` (a band file absent, malformed or naming a band the
table cannot integrate). No number of either table is written in code.

The scene's sun. ``scene.sun_lux`` is the directional light's intensity
in lux; when unstated, :func:`scene_sun_lux` evaluates
core/scenario/solar.py's clear-sky model at the look's sun elevation
(provenance ``model``) so the render can be handed ``-sun-lux=``. The
visual scene today sets the sun to 8.0 (a unitless number): under the
daylight triple (EV100 14.97) an 18 % grey surface would read
0.18 x 8 / pi / (1.2 x 0.78 x 2^14.97) = 1.5e-5 of full scale -- black.
:func:`exposure_units_check` refuses ``sensing.exposure_units`` by name
with those numbers when a render.json says the sun's light unit is not
physical while the card took the manual-EV100 path; the refusal is
recorded in the frame's radiometry block, never thrown at the flight.

What is NOT claimed: no spectral rendering and no BRDF spectra (the
band model is a linear proxy over three sRGB / Rec.709 channels); the
constant 1.2 x A x 2^EV100 is predicted until the grey card measures it
and carries no traceable chain to a reference luminance (a stated gap:
a future clause ties it to an ISO 12232 saturation exposure with u_D);
the working colour space is the engine's (read back, not chosen here);
the illuminant is the stated reference spectrum, not the scene's.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .exposure import ev100 as _ev100

REPO = Path(__file__).resolve().parents[2]
VLAMBDA_FILE = REPO / "assets" / "cie" / "vlambda_1nm.csv"
ILLUMINANT_DIR = REPO / "assets" / "illuminants"
BAND_DIR = REPO / "assets" / "sensor_bands"
DEFAULT_ILLUMINANT = "astm_g173_direct"
FETCH_STEP = "scripts/fetch_sensing_tables.py"

REFUSAL_RADIOMETRY = "sensing.radiometry"
REFUSAL_BAND = "sensing.band"
REFUSAL_EXPOSURE_UNITS = "sensing.exposure_units"

#: ISO 12232 / Lagarde 2014 section 5.1: L_max = 2^EV100 x 78 / (q x 100)
#: with q = 0.65 (ISO 2720) = 1.2 x 2^EV100 cd/m^2 at ISO 100.
CALIBRATION_CONSTANT = 1.2
#: Unreal's manual-exposure lens attenuation, the documented default of
#: r.EyeAdaptation.LensAttenuation [unverified here: the engine
#: documentation is unreachable through this container's proxy]; replaced
#: by the read-back in render.json render_settings.console when present.
LENS_ATTENUATION_DEFAULT = 0.78
LENS_ATTENUATION_CVAR = "r.EyeAdaptation.LensAttenuation"
#: The maximum spectral luminous efficacy (lm/W), the definition of the
#: candela (CGPM 2018).
LUMINOUS_EFFICACY_MAX_LM_PER_W = 683.0
#: The working colour space the frame's channels are in: the engine's,
#: read back from render.json (``render_settings.working_colour_space``)
#: when a render exists; the documented default otherwise.
WORKING_COLOUR_SPACE_DEFAULT = "sRGB / Rec.709 primaries, linear"
#: An 18 % grey card and its Lambertian luminance under an illuminance E:
#: L = rho E / pi.
GREY_CARD_REFLECTANCE = 0.18
#: The visual scene's unitless sun today (FlightSimVisualScene.cpp L164).
ENGINE_SUN_TODAY = 8.0
#: What the engine's sun must read back as for the chain to mean lux
#: (S4 records ``look_applied.sun.light_units``).
PHYSICAL_LIGHT_UNITS = "physical"

CALIBRATION_PREDICTED = "predicted"
CALIBRATION_MEASURED = "measured"
CALIBRATION_REFUSED = "refused"

REFERENCES = (
    "ISO 2720:1974 (exposure meters; H = q t L / N^2, q = 0.65) [unverified here]",
    "ISO 12232:2019 (S_sat = 78 / H_sat) [unverified here]",
    "Lagarde & de Rousiers, Moving Frostbite to PBR, 2014, section 5.1 (L_max = 1.2 x 2^EV100)",
    "Unreal Engine r.EyeAdaptation.LensAttenuation, default 0.78 [unverified here]",
    "CIE 018:2019 (V(lambda), the 1924 photopic observer) via the cached table",
    "ASTM G173-03 reference spectra via the cached table",
    "docs/ADVANCEMENTS_BLUEPRINT.md section 3, corrections applied",
)


class RadiometryError(Exception):
    """A radiometric quantity that cannot be formed, refused by name:
    ``sensing.radiometry`` (the chain, a table absent or corrupt),
    ``sensing.band`` (the band file or a band) or
    ``sensing.exposure_units`` (the engine's sun is not in lux)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


# -- the calibration chain ----------------------------------------------------

def _finite(value, what: str, constraint: str = "sensing.radiometry") -> float:
    if isinstance(value, bool):
        raise RadiometryError(constraint, f"{what} must be a number, not {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RadiometryError(constraint, f"{what} must be a number, not {value!r}")
    if not math.isfinite(number):
        raise RadiometryError(constraint, f"{what} must be finite, not {value!r}")
    return number


def check_lens_attenuation(value) -> float:
    """A in (0, 1]: the fraction of the scene's light the lens passes."""
    a = _finite(value, "the lens attenuation")
    if not 0.0 < a <= 1.0:
        raise RadiometryError("sensing.radiometry",
                              f"the lens attenuation {a!r} is outside (0, 1]; Unreal's "
                              f"{LENS_ATTENUATION_CVAR} is a fraction of the light passed")
    return a


def luminance_per_unit(ev100_value, exposure_compensation_ev=0.0,
                       lens_attenuation=LENS_ATTENUATION_DEFAULT) -> float:
    """cd/m^2 per unit of the linear frame: 1.2 x A x 2^(EV100 - EC).
    +1 EC halves it (the picture doubles)."""
    ev = _finite(ev100_value, "EV100")
    ec = _finite(exposure_compensation_ev, "the exposure compensation")
    a = check_lens_attenuation(lens_attenuation)
    return CALIBRATION_CONSTANT * a * math.pow(2.0, ev - ec)


def luminance_from_frame(linear, ev100_value, exposure_compensation_ev=0.0,
                         lens_attenuation=LENS_ATTENUATION_DEFAULT):
    """The linear frame (any shape of floats) as photometric luminance
    per channel, cd/m^2: value x :func:`luminance_per_unit`."""
    import numpy as np

    scale = luminance_per_unit(ev100_value, exposure_compensation_ev, lens_attenuation)
    return np.asarray(linear, dtype=np.float64) * scale


def grey_card_luminance(illuminance_lux, reflectance: float = GREY_CARD_REFLECTANCE) -> float:
    """A Lambertian card's luminance under an illuminance: rho E / pi."""
    e = _finite(illuminance_lux, "the illuminance")
    return float(reflectance) * e / math.pi


def grey_card_prediction(sun_lux, ev100_value, exposure_compensation_ev=0.0,
                         lens_attenuation=LENS_ATTENUATION_DEFAULT,
                         reflectance: float = GREY_CARD_REFLECTANCE) -> float:
    """The linear value an 18 % card lit by the sun alone should read:
    (rho E / pi) / luminance_per_unit -- the prediction the grey-card
    calibration frame (S4) is measured against."""
    return grey_card_luminance(sun_lux, reflectance) / luminance_per_unit(
        ev100_value, exposure_compensation_ev, lens_attenuation)


def exposure_units_check(look_applied: Optional[Mapping[str, Any]], ev100_value,
                         exposure_mode: Optional[str] = None) -> Dict[str, Any]:
    """Whether the engine's sun and the manual EV100 path mean the same
    unit. Returns the numbers as a dict when they do (``light_units``
    physical); refuses ``sensing.exposure_units`` when a render.json's
    ``look_applied.sun`` carries no physical light unit while the card
    took the manual-EV100 path (or none is known): the 8.0 sun under
    EV100 14.97 puts an 18 % card at 1.5e-5 of full scale. The refusal
    is by name and carries the numbers; the caller records it in the
    frame's radiometry block rather than refusing the flight."""
    sun = (look_applied or {}).get("sun") if isinstance(look_applied, Mapping) else None
    units = sun.get("light_units") if isinstance(sun, Mapping) else None
    intensity = sun.get("intensity") if isinstance(sun, Mapping) else None
    if intensity is None:
        intensity = ENGINE_SUN_TODAY
    ev = _finite(ev100_value, "EV100")
    per_unit = luminance_per_unit(ev, 0.0, LENS_ATTENUATION_DEFAULT)
    card = grey_card_luminance(float(intensity)) / per_unit
    numbers = {"sun_intensity": float(intensity), "light_units": units, "ev100": ev,
               "luminance_cd_m2_per_unit": per_unit, "grey_card_value": card,
               "exposure_mode": exposure_mode}
    if units == PHYSICAL_LIGHT_UNITS:
        return numbers
    raise RadiometryError("sensing.exposure_units",
        f"the engine's sun is {float(intensity):g} in light units {units!r}, not lux, while the "
        f"exposure is manual EV100 {ev:.2f} ({per_unit:.0f} cd/m^2 per unit): an 18 % grey card "
        f"would read {card:.2e} of full scale, black; the sun must be set in lux "
        f"(-sun-lux=, S4) before this chain means anything")


# -- the cached tables --------------------------------------------------------

def _read_checked(path: Path, what: str) -> str:
    """The text of a cached table whose ``.sha256`` sidecar matches, or
    ``sensing.radiometry`` by name: absent, unreadable, no sidecar, or
    a digest that is not the sidecar's."""
    path = Path(path)
    sidecar = path.with_name(path.name + ".sha256")
    if not path.is_file():
        raise RadiometryError("sensing.radiometry",
                              f"the {what} table {path.name} is absent from {path.parent}; "
                              f"nothing is invented in its place -- run {FETCH_STEP} to cache it")
    if not sidecar.is_file():
        raise RadiometryError("sensing.radiometry",
                              f"the {what} table {path.name} has no sha256 sidecar "
                              f"{sidecar.name}; run {FETCH_STEP}")
    data = path.read_bytes()
    recorded = sidecar.read_text(encoding="utf-8").split()[0] if sidecar.read_text(encoding="utf-8").split() else ""
    digest = hashlib.sha256(data).hexdigest()
    if digest != recorded:
        raise RadiometryError("sensing.radiometry",
                              f"the {what} table {path.name} digests {digest[:16]}.. but its "
                              f"sidecar says {recorded[:16]}..; the cached table is not the one "
                              f"fetched (run {FETCH_STEP} --force to refetch, and say why)")
    return data.decode("utf-8")


@dataclass(frozen=True)
class SpectralTable:
    name: str
    path: str
    sha256: str
    wavelength_nm: Tuple[float, ...]
    values: Tuple[float, ...]
    unit: str

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "file": self.path, "sha256": self.sha256,
                "rows": len(self.wavelength_nm),
                "range_nm": [self.wavelength_nm[0], self.wavelength_nm[-1]], "unit": self.unit}


def load_vlambda(path: Optional[Path] = None) -> SpectralTable:
    """CIE 1924 V(lambda) at 1 nm from the cached file (sidecar checked)."""
    path = Path(path or VLAMBDA_FILE)
    text = _read_checked(path, "CIE V(lambda)")
    rows = _csv_rows(text, 2, path, "CIE V(lambda)")
    wl = tuple(r[0] for r in rows)
    if len(wl) < 2 or any(b - a != 1.0 for a, b in zip(wl, wl[1:])):
        raise RadiometryError("sensing.radiometry", f"{path.name} is not a 1 nm table")
    return SpectralTable("CIE 1924 V(lambda)", str(path), _sha256_file(path), wl,
                         tuple(r[1] for r in rows), "1")


def load_illuminant(name: str = DEFAULT_ILLUMINANT, illuminant_dir: Optional[Path] = None) -> SpectralTable:
    """An illuminant spectrum (W m^-2 nm^-1) from the cached file: the
    ASTM G173-03 direct + circumsolar column."""
    directory = Path(illuminant_dir or ILLUMINANT_DIR)
    path = directory / f"{name}.csv"
    text = _read_checked(path, f"illuminant {name}")
    rows = _csv_rows(text, 4, path, f"illuminant {name}")
    return SpectralTable(name, str(path), _sha256_file(path),
                         tuple(r[0] for r in rows), tuple(r[3] for r in rows), "W m^-2 nm^-1")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _csv_rows(text: str, columns: int, path: Path, what: str) -> List[Tuple[float, ...]]:
    rows: List[Tuple[float, ...]] = []
    for number, line in enumerate(text.splitlines()):
        if number == 0 or not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < columns:
            raise RadiometryError("sensing.radiometry",
                                  f"{path.name} line {number + 1} has {len(parts)} columns, "
                                  f"not {columns} ({what})")
        try:
            rows.append(tuple(float(p) for p in parts[:columns]))
        except ValueError:
            raise RadiometryError("sensing.radiometry",
                                  f"{path.name} line {number + 1} is not numeric ({what})")
    if not rows:
        raise RadiometryError("sensing.radiometry", f"{path.name} holds no rows ({what})")
    return rows


def luminous_efficacy(illuminant: SpectralTable, vlambda: SpectralTable) -> float:
    """683 x integral(S V) / integral(S) over the illuminant's whole
    range (lm/W); V is 0 outside its table. The number core/scenario/
    solar.py declares for the direct sun is this, measured."""
    import numpy as np

    wl = np.asarray(illuminant.wavelength_nm)
    s = np.asarray(illuminant.values)
    v = np.interp(wl, np.asarray(vlambda.wavelength_nm), np.asarray(vlambda.values),
                  left=0.0, right=0.0)
    return float(LUMINOUS_EFFICACY_MAX_LM_PER_W * np.trapezoid(s * v, wl) / np.trapezoid(s, wl))


# -- the band proxy -------------------------------------------------------------

@dataclass(frozen=True)
class BandTable:
    name: str
    proxy: bool
    basis: str
    source: str
    channels: Tuple[str, ...]
    illuminant: str
    bands: Dict[str, Dict[str, Any]]          # name -> {channel, window_nm}
    weights: Tuple[Tuple[float, ...], ...]     # 3 x 3 channel mixing (rows: out, cols: in)
    not_claimed: Tuple[str, ...]
    sha256: str
    path: str

    @property
    def is_identity(self) -> bool:
        return all(self.weights[i][j] == (1.0 if i == j else 0.0) for i in range(3) for j in range(3))

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "proxy": self.proxy, "basis": self.basis, "source": self.source,
                "channels": list(self.channels), "illuminant": self.illuminant,
                "bands": {k: dict(v) for k, v in self.bands.items()},
                "weights": [list(r) for r in self.weights],
                "not_claimed": list(self.not_claimed), "sha256": self.sha256, "file": self.path}


def available_bands(band_dir: Optional[Path] = None) -> List[str]:
    directory = Path(band_dir or BAND_DIR)
    return sorted(p.stem for p in directory.glob("*.json"))


def load_bands(name: str = "rgb_proxy", band_dir: Optional[Path] = None) -> BandTable:
    """A band file by name, or ``sensing.band`` by name: absent, not
    declared ``proxy: true``, not three channels, a band without a
    window inside 360..830 nm or naming an unknown channel, weights not
    a 3 x 3 matrix of finite numbers, or no source."""
    directory = Path(band_dir or BAND_DIR)
    path = directory / f"{name}.json"
    if not path.is_file():
        raise RadiometryError("sensing.band",
                              f"no band file {name!r} in {directory} (available: "
                              f"{', '.join(available_bands(directory)) or 'none'})")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RadiometryError("sensing.band", f"band file {name!r} unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("name") != name:
        raise RadiometryError("sensing.band", f"band file {path.name} does not name itself {name!r}")
    if data.get("proxy") is not True:
        raise RadiometryError("sensing.band",
                              f"band file {name!r} does not declare proxy: true; a band model "
                              f"over three rendered channels is a proxy and must say so")
    if not str(data.get("source", "")).strip():
        raise RadiometryError("sensing.band", f"band file {name!r} cites no source")
    channels = tuple(str(c) for c in (data.get("channels") or ()))
    if len(channels) != 3:
        raise RadiometryError("sensing.band", f"band file {name!r} must name three channels, not {channels}")
    bands = data.get("bands")
    if not isinstance(bands, dict) or not bands:
        raise RadiometryError("sensing.band", f"band file {name!r} declares no bands")
    clean: Dict[str, Dict[str, Any]] = {}
    for band, entry in bands.items():
        window = (entry or {}).get("window_nm") if isinstance(entry, dict) else None
        channel = (entry or {}).get("channel") if isinstance(entry, dict) else None
        try:
            lo, hi = float(window[0]), float(window[1])
        except (TypeError, ValueError, IndexError):
            raise RadiometryError("sensing.band", f"band {band!r} of {name!r} has no [lo, hi] window_nm")
        if not (360.0 <= lo < hi <= 830.0):
            raise RadiometryError("sensing.band",
                                  f"band {band!r} of {name!r} window {lo:g}-{hi:g} nm is not inside "
                                  f"the 360-830 nm range V(lambda) is tabulated over")
        if channel not in channels:
            raise RadiometryError("sensing.band",
                                  f"band {band!r} of {name!r} names channel {channel!r}, not one of {channels}")
        clean[str(band)] = {"channel": str(channel), "window_nm": [lo, hi]}
    weights = data.get("weights")
    try:
        rows = tuple(tuple(float(x) for x in row) for row in weights)
    except (TypeError, ValueError):
        rows = ()
    if len(rows) != 3 or any(len(r) != 3 for r in rows) or any(
            not math.isfinite(x) for r in rows for x in r):
        raise RadiometryError("sensing.band", f"band file {name!r} weights are not a 3 x 3 matrix of numbers")
    return BandTable(name=name, proxy=True, basis=str(data.get("basis", "stated")),
                     source=str(data["source"]), channels=channels,
                     illuminant=str(data.get("illuminant", DEFAULT_ILLUMINANT)), bands=clean,
                     weights=rows, not_claimed=tuple(str(s) for s in (data.get("not_claimed") or ())),
                     sha256=_sha256_file(path), path=str(path))


def band_factor(window_nm: Sequence[float], vlambda: SpectralTable, illuminant: SpectralTable) -> float:
    """K_band = integral(S V w) / integral(S w) on the V(lambda) 1 nm
    grid with w the band's rectangular window and S the illuminant
    interpolated onto that grid. Dimensionless in [0, 1]; 683 K_band is
    the illuminant's luminous efficacy within the band (lm/W)."""
    import numpy as np

    lo, hi = float(window_nm[0]), float(window_nm[1])
    grid = np.asarray(vlambda.wavelength_nm)
    v = np.asarray(vlambda.values)
    s = np.interp(grid, np.asarray(illuminant.wavelength_nm), np.asarray(illuminant.values),
                  left=0.0, right=0.0)
    w = ((grid >= lo) & (grid <= hi)).astype(np.float64)
    denominator = float(np.trapezoid(s * w, grid))
    if denominator <= 0.0:
        raise RadiometryError("sensing.band",
                              f"the illuminant {illuminant.name} has no power in {lo:g}-{hi:g} nm; "
                              f"K_band is undefined there")
    return float(np.trapezoid(s * v * w, grid) / denominator)


def band_factors(bands: BandTable, vlambda: Optional[SpectralTable] = None,
                 illuminant: Optional[SpectralTable] = None) -> Dict[str, float]:
    """{band: K_band} from the cached tables (loaded when not given)."""
    vlambda = vlambda if vlambda is not None else load_vlambda()
    illuminant = illuminant if illuminant is not None else load_illuminant(bands.illuminant)
    return {name: band_factor(entry["window_nm"], vlambda, illuminant)
            for name, entry in bands.bands.items()}


def apply_band_weights(frame, bands: BandTable):
    """The radiance stage of the post-pass: the frame's three channels
    mixed by the band file's 3 x 3 weights (out = W in). Identity
    weights return the input array itself, bit for bit."""
    import numpy as np

    if bands.is_identity:
        return frame
    image = np.asarray(frame, dtype=np.float64)
    w = np.asarray(bands.weights, dtype=np.float64)
    return image @ w.T


def band_radiance(luminance_by_channel, bands: BandTable, factors: Mapping[str, float]) -> Dict[str, Any]:
    """{band: L_e (W m^-2 sr^-1) array} from per-channel luminance
    (cd/m^2): L_e = L_v / (683 K_band), taking the band's channel."""
    import numpy as np

    image = np.asarray(luminance_by_channel, dtype=np.float64)
    out: Dict[str, Any] = {}
    for name, entry in bands.bands.items():
        index = bands.channels.index(entry["channel"])
        k = float(factors[name])
        if k <= 0.0:
            raise RadiometryError("sensing.band", f"band {name!r} has K_band {k!r}; the proxy divides by it")
        out[name] = image[..., index] / (LUMINOUS_EFFICACY_MAX_LM_PER_W * k)
    return out


# -- the blocks and the records ---------------------------------------------------

def read_back_lens_attenuation(render_settings: Optional[Mapping[str, Any]]) -> Tuple[float, str]:
    """(A, basis): the console read-back from render.json when it carries
    one, else the documented default with a basis saying so."""
    console = (render_settings or {}).get("console") if isinstance(render_settings, Mapping) else None
    if isinstance(console, Mapping) and LENS_ATTENUATION_CVAR in console:
        value = check_lens_attenuation(console[LENS_ATTENUATION_CVAR])
        return value, f"read back from render.json render_settings.console[{LENS_ATTENUATION_CVAR}]"
    return LENS_ATTENUATION_DEFAULT, (f"the documented default of {LENS_ATTENUATION_CVAR} "
                                      f"[unverified here]; no render.json read-back")


def scene_sun_lux(stated, sun_elevation_deg: Optional[float], altitude_m: float = 0.0) -> Dict[str, Any]:
    """The sun the render is handed: the STATED ``scene.sun_lux`` (source
    user) when there is one, else the clear-sky model at the look's sun
    elevation (source model), else unstated with the reason. Never a
    refusal of the flight: an unstated sun leaves the engine's own."""
    from ..scenario.solar import illuminance_lux, sun_lux_problem

    if stated is not None:
        problem = sun_lux_problem(stated)
        if problem:
            from ..scenario.solar import SunLuxError

            raise SunLuxError(problem)
        return {"value": float(stated), "unit": "lx", "source": "user",
                "from": "scene.sun_lux as stated", "basis": "stated by the spec"}
    if sun_elevation_deg is None:
        return {"value": None, "unit": "lx", "source": "derived",
                "from": "unstated: no sun elevation to evaluate the clear-sky model at",
                "basis": "the engine's own sun stands (8.0, unitless, the defect this item names)"}
    sun = illuminance_lux(sun_elevation_deg, altitude_m=altitude_m)
    return {"value": sun.illuminance_lux, "unit": "lx", "source": "model",
            "from": f"clear-sky direct normal illuminance at sun elevation {sun.elevation_deg:g} deg, "
                    f"{sun.pressure_hpa:.1f} hPa: {sun.direct_normal_w_m2:.1f} W/m^2 x "
                    f"{sun.efficacy_lm_per_w:g} lm/W",
            "basis": sun.source, "air_mass": sun.air_mass,
            "transmittances": dict(sun.transmittances), "note": sun.note}


def camera_ev100(values: Mapping[str, Any]) -> float:
    """EV100 from a camera's exposure triple dict {aperture_f, shutter_s, iso}."""
    return _ev100(values["aperture_f"], values["shutter_s"], values["iso"])


def radiometry_block(ev100_value: float, exposure_compensation_ev: float = 0.0,
                     render_settings: Optional[Mapping[str, Any]] = None,
                     sun_lux: Optional[Mapping[str, Any]] = None,
                     calibration: Optional[Mapping[str, Any]] = None,
                     working_colour_space: Optional[str] = None,
                     lens_attenuation: Optional[float] = None) -> Dict[str, Any]:
    """The per-camera ``sensing.radiometry`` block: ev100, EC, A (with
    its basis), the luminance per unit, the working colour space, the
    grey-card prediction under the sun (when a sun is known), and the
    calibration status: ``measured`` only when ``calibration`` (S4's
    calibration.json) carries a finite ``ratio``; ``predicted`` else. ``lens_attenuation`` is a
    profile's stated A, used only when no render read one back."""
    a, a_basis = read_back_lens_attenuation(render_settings)
    if lens_attenuation is not None and "read back" not in a_basis:
        a = check_lens_attenuation(lens_attenuation)
        a_basis = "the profile's radiometry block (stated); no render.json read-back"
    ec = _finite(exposure_compensation_ev, "the exposure compensation")
    ev = _finite(ev100_value, "EV100")
    per_unit = luminance_per_unit(ev, ec, a)
    sun_value = (sun_lux or {}).get("value") if isinstance(sun_lux, Mapping) else None
    status = CALIBRATION_PREDICTED
    ratio = None
    if isinstance(calibration, Mapping) and isinstance(calibration.get("ratio"), (int, float)) \
            and math.isfinite(float(calibration["ratio"])):
        status = CALIBRATION_MEASURED
        ratio = float(calibration["ratio"])
    space = working_colour_space
    if space is None:
        recorded = (render_settings or {}).get("working_colour_space") if isinstance(render_settings, Mapping) else None
        space = str(recorded) if recorded else WORKING_COLOUR_SPACE_DEFAULT
    return {
        "model": "v = L_v / (1.2 x A x 2^(EV100 - EC)); ISO 2720 / ISO 12232 / Lagarde 2014 s5.1 "
                 "with Unreal's lens attenuation A",
        "ev100": ev,
        "exposure_compensation_ev": ec,
        "lens_attenuation": a,
        "lens_attenuation_basis": a_basis,
        "calibration_constant": CALIBRATION_CONSTANT,
        "luminance_cd_m2_per_unit": per_unit,
        "working_colour_space": space,
        "sun_lux": dict(sun_lux) if isinstance(sun_lux, Mapping) else None,
        "grey_card_predicted": (None if sun_value is None
                                else grey_card_prediction(sun_value, ev, ec, a)),
        "grey_card_measured_ratio": ratio,
        "calibration_status": status,
        "calibration_basis": ("measured: calibration.json's grey-card ratio (S4)" if ratio is not None
                              else "predicted: no calibration frame has been rendered (S4, Windows); "
                                   "the constant carries no traceable chain to a reference luminance"),
        "references": list(REFERENCES),
    }


def bands_block(bands: BandTable, vlambda: Optional[SpectralTable] = None,
                illuminant: Optional[SpectralTable] = None) -> Dict[str, Any]:
    """The per-camera ``sensing.bands`` block: the band file, the two
    tables (file, sha256) and every K_band, computed from the cached
    tables only."""
    vlambda = vlambda if vlambda is not None else load_vlambda()
    illuminant = illuminant if illuminant is not None else load_illuminant(bands.illuminant)
    factors = band_factors(bands, vlambda, illuminant)
    return {
        "model": "L_e,band = L_v,ch / (683 K_band); K_band = int(S V w_band) / int(S w_band)",
        "table": bands.to_dict(),
        "vlambda": vlambda.to_dict(),
        "illuminant": illuminant.to_dict(),
        "k_band": factors,
        "efficacy_lm_per_w": {name: LUMINOUS_EFFICACY_MAX_LM_PER_W * k for name, k in factors.items()},
        "identity_weights": bands.is_identity,
        "proxy": True,
    }


def radiometry_record(block: Mapping[str, Any], null_with: float, null_without: float):
    """The ``sensing.radiometry`` AppliedVariable (record 2): value = the
    luminance per unit; readback = A read back from render.json against
    the value the chain used (exact when read back; the default when
    not, said so); null test = EC +1 halves the luminance per unit
    (``reached``, threshold half the without value), measured by the
    caller on the synthetic frame (``null_with`` / ``null_without``)."""
    from ..records import AppliedVariable, Model, NullTest, Readback

    a = float(block["lens_attenuation"])
    read_back = "read back" in str(block.get("lens_attenuation_basis", ""))
    per_unit = float(block["luminance_cd_m2_per_unit"])
    return AppliedVariable(
        name="sensing.radiometry", value=per_unit, unit="cd/m^2 per unit",
        source="derived",
        model=str(block["model"]),
        parameters={k: block[k] for k in ("ev100", "exposure_compensation_ev", "lens_attenuation",
                                          "lens_attenuation_basis", "calibration_constant",
                                          "working_colour_space", "sun_lux", "grey_card_predicted",
                                          "grey_card_measured_ratio", "calibration_status",
                                          "calibration_basis")},
        references=tuple(block["references"]),
        properties_written=(),
        telemetry_columns=(),
        frame_keys=("radiometry.luminance_cd_m2_per_unit", "radiometry.calibration_status"),
        null_test=NullTest(
            quantity="luminance per unit at EC +1 against EC 0", unit="cd/m^2 per unit",
            with_value=float(null_with), without_value=float(null_without),
            threshold=0.5 * float(null_without), kind="reached",
            note="+1 stop of exposure compensation halves the luminance one unit stands for "
                 "(the picture doubles); measured on the synthetic frame"),
        not_claimed=("the constant is predicted, not measured: no grey card has been rendered (S4)",
                     "no traceable chain to a reference luminance (a stated gap)",
                     "the lens attenuation is the console default until read back" if not read_back
                     else "the read-back is the engine's console value, not a measurement of the lens",
                     "no spectral rendering; photometric luminance per channel"),
        frm=str(block.get("lens_attenuation_basis")),
        std="ISO 2720 / ISO 12232:2019 / Lagarde & de Rousiers 2014 s5.1 [unverified here]",
        readback=Readback(property=LENS_ATTENUATION_CVAR, value=a, written=a,
                          tolerance=0.0, tolerance_kind="absolute",
                          basis=("the console variable read back from render.json equals the A "
                                 "the chain used" if read_back else
                                 "no render here: the default 0.78 was used and is what the chain "
                                 "used; the read-back is a Windows step")),
        model_block=Model(name="manual exposure calibration chain",
                          standard="ISO 2720:1974; ISO 12232:2019", version="Lagarde 2014 s5.1 + UE lens attenuation",
                          parameters={"calibration_constant": CALIBRATION_CONSTANT, "lens_attenuation": a},
                          references=tuple(block["references"])),
    )


def bands_record(block: Mapping[str, Any], null_max_abs_difference: float, frame_shape: Sequence[int]):
    """The ``sensing.bands`` AppliedVariable (record 2): value = the band
    names; readback = K_band recomputed from the tables against the
    block's (exact); null test = identity weights reproduce the frame
    (``bounded``, threshold 0, the measured max |difference| given)."""
    from ..records import AppliedVariable, Model, NullTest, Readback

    factors = dict(block["k_band"])
    first = next(iter(factors))
    table = block["table"]
    return AppliedVariable(
        name="sensing.bands", value=list(factors), unit="band",
        source="user" if not block.get("defaulted") else "default",
        model=str(block["model"]),
        parameters={"band_file": table["name"], "band_file_sha256": table["sha256"],
                    "windows_nm": {k: v["window_nm"] for k, v in table["bands"].items()},
                    "weights": table["weights"], "k_band": factors,
                    "efficacy_lm_per_w": dict(block["efficacy_lm_per_w"]),
                    "vlambda_sha256": block["vlambda"]["sha256"],
                    "illuminant": block["illuminant"]["name"],
                    "illuminant_sha256": block["illuminant"]["sha256"],
                    "frame_shape": list(frame_shape), "proxy": True},
        references=("CIE 018:2019 V(lambda) (cached table)", "ASTM G173-03 (cached table)",
                    "docs/ADVANCEMENTS_BLUEPRINT.md section 3"),
        frame_keys=(),
        null_test=NullTest(
            quantity="max |frame with identity weights - frame|", unit="1",
            with_value=float(null_max_abs_difference), without_value=0.0, threshold=0.0,
            kind="bounded",
            note="identity weights reproduce the frame bit for bit; measured on the synthetic frame"),
        not_claimed=tuple(table["not_claimed"]),
        std="CIE 018:2019; ASTM G173-03 (both from cached tables, the mirrors named in their provenance)",
        readback=Readback(property=f"k_band[{first}]", value=float(factors[first]),
                          written=float(factors[first]), tolerance=0.0, tolerance_kind="absolute",
                          basis="K_band recomputed from the cached tables equals the block's"),
        model_block=Model(name="band proxy over three rendered channels", standard="CIE 018:2019; ASTM G173-03",
                          version="rgb_proxy", parameters={"k_band": factors},
                          references=("cached tables, sha256 recorded",)),
    )


# -- the per-camera sensing block, its frame keys and its records ---------------------------------
#
# The capture manifest's ``cameras[i].sensing`` (absent-canonical: written
# only when a camera, its profile or the scene asked for a sensing block)
# and the per-frame ``radiometry`` keys; core/capture/manifest.py calls
# these, flightsim/capture.py re-evaluates them after a render from the
# render.json read-backs (attach_render_radiometry).

SENSING_BLOCKS = ("radiometry", "bands", "optics", "motion_blur")


def sun_elevation_for_spec(spec) -> Tuple[Optional[float], str]:
    """(the sun's elevation the render will be lit at, its basis): the
    randomisation block's sun_elevation_deg when the block is on and the
    value is drawn, else the harness's default look (core/render/flags.py
    DEFAULT_LOOK, the noon 50 deg both render paths pass)."""
    block = getattr(spec, "randomization", None)
    if block is not None and not block.is_default():
        q = getattr(block, "sun_elevation_deg", None)
        value = getattr(q, "value", None)
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value), f"randomization.sun_elevation_deg ({q.source.value}: {q.frm})"
    from ..render.flags import DEFAULT_LOOK

    return float(DEFAULT_LOOK["sun_elev"]), "the harness's default look (core/render/flags.py DEFAULT_LOOK)"


def sun_lux_for_spec(spec) -> Dict[str, Any]:
    """The scene's sun block for a spec: the stated ``scene.sun_lux`` when
    the block carries the field and states it, else the clear-sky model
    at :func:`sun_elevation_for_spec` at the spec's initial altitude."""
    stated = None
    scene = getattr(spec, "scene", None)
    q = getattr(scene, "sun_lux", None) if scene is not None else None
    if q is not None and q.value is not None:
        stated = q.value
    elevation, basis = sun_elevation_for_spec(spec)
    altitude = float(getattr(getattr(spec, "terrain_elevation", None), "value", 0.0) or 0.0)
    block = scene_sun_lux(stated, elevation, altitude_m=altitude)
    block["sun_elevation_deg"] = elevation
    block["sun_elevation_basis"] = basis
    return block


def sensing_requested(camera, profile, spec=None) -> List[str]:
    """Who asked for a sensing block: the camera's stated fields, the
    profile's optional blocks, a stated scene sun. Empty = nobody, and
    the manifest writes no block (absent-canonical)."""
    asked: List[str] = []
    if hasattr(camera, "sensing_stated") and camera.sensing_stated():
        asked.append("camera")
    for key in SENSING_BLOCKS:
        if getattr(profile, key, None) is not None:
            asked.append(f"profile.{key}")
    scene = getattr(spec, "scene", None) if spec is not None else None
    q = getattr(scene, "sun_lux", None) if scene is not None else None
    if q is not None and q.value is not None:
        asked.append("scene.sun_lux")
    return asked


def camera_sensing_block(camera, profile, sun_lux: Optional[Mapping[str, Any]] = None,
                         render_settings: Optional[Mapping[str, Any]] = None,
                         calibration: Optional[Mapping[str, Any]] = None,
                         spec=None) -> Optional[Dict[str, Any]]:
    """``cameras[i].sensing`` for one camera: {requested_by, radiometry,
    bands, optics, motion_blur}, or None when nobody asked. Every block
    is built from the cached tables and the stated parameters only; a
    table absent refuses ``sensing.radiometry`` / ``sensing.band`` by
    name through the loaders."""
    asked = sensing_requested(camera, profile, spec)
    if not asked:
        return None
    exposure = {name: float(q.value) for name, q in camera.exposure.quantities()}
    ev = camera_ev100(exposure)
    ec = float(camera.exposure_compensation_ev.value or 0.0)
    profile_radiometry = getattr(profile, "radiometry", None) or {}
    attenuation = profile_radiometry.get("lens_attenuation")
    radiometry = radiometry_block(ev, ec, render_settings, sun_lux, calibration,
                                  working_colour_space=profile_radiometry.get("working_colour_space"),
                                  lens_attenuation=attenuation)
    band_name = camera.bands.value or (getattr(profile, "bands", None) or {}).get("name")
    bands = None
    if band_name is not None:
        bands = bands_block(load_bands(str(band_name)))
        bands["requested_by"] = "camera" if camera.bands.value is not None else "profile"
    optics = None
    if getattr(profile, "optics", None) is not None:
        from .optics import optics_block

        record = {"sensor_width_mm": float(camera.sensor_width_mm.value),
                  "width_px": float(camera.width_px.value)}
        optics = optics_block(profile.optics, record, exposure["aperture_f"])[1]
    motion_blur = None
    if getattr(profile, "motion_blur", None) is not None:
        motion_blur = dict(profile.motion_blur)
        motion_blur.update({"exposure_s": exposure["shutter_s"],
                            "streaks": "per frame in sensor.json (python_velocity_line) or the "
                                       "bundle's accumulation (engine_accumulation)"})
    return {"requested_by": asked, "exposure": exposure, "radiometry": radiometry,
            "bands": bands, "optics": optics, "motion_blur": motion_blur}


def frame_radiometry_block(sensing: Mapping[str, Any]) -> Dict[str, Any]:
    """The per-frame ``radiometry`` keys from the camera's sensing block."""
    r = sensing["radiometry"]
    return {"luminance_cd_m2_per_unit": r["luminance_cd_m2_per_unit"],
            "exposure_compensation_ev": r["exposure_compensation_ev"],
            "lens_attenuation": r["lens_attenuation"],
            "calibration_status": r["calibration_status"],
            "exposure_units": None}


def sensing_records(sensing: Mapping[str, Any]) -> List[Any]:
    """The AppliedVariables a sensing block returns (rule 0), each null
    test MEASURED here on a synthetic frame: radiometry (EC +1 halves
    the luminance per unit), bands (identity weights reproduce the
    frame), optics (absent -> bit-identical; the e-SFR MTF50 on a
    synthetic edge recorded beside the prediction), motion blur
    (exposure 0 -> identical)."""
    import numpy as np

    r = sensing["radiometry"]
    per_unit = float(r["luminance_cd_m2_per_unit"])
    halved = luminance_per_unit(float(r["ev100"]), float(r["exposure_compensation_ev"]) + 1.0,
                                float(r["lens_attenuation"]))
    out = [radiometry_record(r, null_with=halved, null_without=per_unit)]
    frame = np.round(np.random.default_rng(0).random((24, 32, 3)) * 255.0) / 255.0
    if sensing.get("bands") is not None:
        table = load_bands(str(sensing["bands"]["table"]["name"]))
        same = apply_band_weights(frame, table)
        out.append(bands_record(sensing["bands"], float(np.abs(np.asarray(same) - frame).max()), frame.shape))
    if sensing.get("optics") is not None:
        from .optics import convolve, esfr_mtf50, kernel, optics_record, slanted_edge_image

        o = sensing["optics"]
        psf, _ = kernel(o["wavelength_nm"] * 1e-9, o["f_number"], o["sigma_um"] * 1e-6,
                        o["pixel_pitch_um"] * 1e-6, o["support_px"])
        measured = esfr_mtf50(convolve(slanted_edge_image(160, 120, 5.0), psf))
        out.append(optics_record(o, 0.0, measured_mtf50=measured,
                                 measured_basis="e-SFR on a synthetic 5 degree edge blurred by this kernel"))
    if sensing.get("motion_blur") is not None:
        from .blur import blur_record, velocity_line_blur

        still, block = velocity_line_blur(frame, (6.0, 2.0), 0.0, float(sensing["motion_blur"]["dt_s"]))
        out.append(blur_record(block, float(np.abs(np.asarray(still) - frame).max())))
    return out


def attach_render_radiometry(run_dir, manifest: Dict[str, Any]) -> Dict[str, Any]:
    """After a render: re-evaluate every camera's radiometry block from its
    render.json read-backs (render_settings.console lens attenuation,
    look_applied.sun light units, a calibration.json beside the bundle)
    and write the per-frame status. The engine's sun not being in lux is
    the ``sensing.exposure_units`` refusal, recorded BY NAME in the
    block and every frame -- never a refusal of the run. Returns a
    summary {cameras, refused, measured}."""
    run_dir = Path(run_dir)
    summary = {"cameras": 0, "refused": [], "measured": []}
    for block in manifest.get("cameras", []):
        sensing = block.get("sensing")
        if not isinstance(sensing, Mapping):
            continue
        camera = str(block["camera_id"])
        folder = run_dir / "frames" / camera
        payload: Dict[str, Any] = {}
        if (folder / "render.json").is_file():
            try:
                payload = json.loads((folder / "render.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                payload = {}
        calibration = None
        if (folder / "calibration.json").is_file():
            try:
                calibration = json.loads((folder / "calibration.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                calibration = None
        r = sensing["radiometry"]
        sensing["radiometry"] = radiometry_block(
            float(r["ev100"]), float(r["exposure_compensation_ev"]), payload.get("render_settings"),
            r.get("sun_lux"), calibration, working_colour_space=None)
        units_refusal = None
        try:
            exposure_units_check(payload.get("look_applied"), float(r["ev100"]),
                                 (payload.get("render_settings") or {}).get("exposure_mode"))
        except RadiometryError as exc:
            units_refusal = {"constraint": exc.constraint, "message": exc.message}
            sensing["radiometry"]["calibration_status"] = CALIBRATION_REFUSED
            sensing["radiometry"]["calibration_basis"] = f"refused {exc.constraint}: {exc.message}"
            summary["refused"].append(camera)
        if sensing["radiometry"]["calibration_status"] == CALIBRATION_MEASURED:
            summary["measured"].append(camera)
        summary["cameras"] += 1
        for record in manifest.get("frames", []):
            if str(record.get("camera_id")) == camera and isinstance(record.get("radiometry"), dict):
                record["radiometry"] = frame_radiometry_block(sensing)
                record["radiometry"]["exposure_units"] = units_refusal
    return summary
