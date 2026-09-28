"""Layered wind shear: a piecewise-linear profile, the MIL-F-8785C
surface log law, and a cached NWP fixture (gap P2 of
docs/PHASE3_GAP_ANALYSIS.md, the shear half; blueprint section 1; P6).

Three :class:`WindProvider` subclasses, each carrying the WHOLE horizontal
wind (``carries_base_wind``): when a spec names one through its
``wind_profile`` block the runner adds it in place of the uniform
``SteadyWind`` / surface ``LogProfileWind`` and trims in the profile's
wind at the initial altitude, so the aircraft is trimmed in the air it
flies (the same rule the steady wind follows). Every one reports, per
evaluation, the layer it is in and the vertical speed gradient
(``last`` -> the recorder's ``wind_layer_index`` and ``shear_dv_dz_per_s``
columns); the delivered speed itself is read back from JSBSim's
``atmosphere/wind-*-fps`` (the recorder's ``wind_profile_speed_mps``).

* :class:`LayeredWind`: layers ``[altitude_m, speed_kt, direction_deg]``
  (altitude above mean sea level, the spec's own datum for altitude;
  at least two, strictly ascending, none negative -- refused by name
  ``wind_profile.layers`` at validation and ValueError here), linear in
  speed and in direction along the shorter arc between layers, HELD at
  the first layer below it and at the last above it (stated: no
  extrapolation). The layer index is the index of the layer at or
  below the altitude (0 below the first); dV/dz is the layer's speed
  gradient in (m/s)/m = 1/s (0 outside the layers).
* :class:`MilSpecShear`: MIL-F-8785C 3.7.3.2 ``u(h) = W20 ln(h/z0) /
  ln(20/z0)`` with h in ft above ground, ``z0 = 0.15 ft`` (Category C
  flight phases) or ``2.0 ft`` (other phases) as the specification
  states them [unverified here: the two values and their phase
  assignment are from memory; the log-law form is the same one
  core/environment/wind.py's LogProfileWind cites from Stull], valid
  ``3 ft <= h <= 1000 ft``: a scene that starts outside the range is
  refused by name (``wind_profile.kind``) at validation; along the
  flight the profile is HELD at u(3 ft) below and u(1000 ft) above
  (counted, recorded, not refused mid-flight). W20 is the spec's wind
  speed, taken as the 20-ft wind; the direction the spec's.
* :class:`NwpFixture`: a cached numerical-weather-prediction profile
  ``assets/nwp/<name>.json`` (``levels`` of ``[pressure_hpa, u_mps,
  v_mps]``, u eastward, v northward) with its provenance sidecar
  ``assets/nwp/<name>.provenance.json`` (``url``, ``fetched_at``,
  ``sha256`` of the data file's bytes, ``synthetic``). The levels become
  a :class:`LayeredWind` at the STANDARD-atmosphere height of each
  level pressure (the ISA inversion core/environment/atmosphere.py
  transcribed from FGStandardAtmosphere; stated: geopotential heights
  from the model are not read). Refuses ``weather.fixture_missing``
  (either file absent) and ``weather.fixture_digest`` (the data file's
  sha256 is not the sidecar's, or the sidecar names none).

NOT claimed: any time evolution (every profile is frozen); a wind
component with height beyond the horizontal one (no vertical wind);
the NWP model's own heights (standard-atmosphere heights of the level
pressures are used and said so); any fixture fetched from a live
service (the committed fixture is a synthetic stand-in and its sidecar
says so); the MIL-F-8785C constants beyond the transcription above;
stability corrections to the log law; the engine side (the card block
is pinned; nothing applies it here).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..fdm import units as u
from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from .base import Position, Term, WindNED, WindProvider

#: Where the cached fixtures live (committed, small, with sidecars).
NWP_DIR = Path(__file__).resolve().parents[2] / "assets" / "nwp"
#: The wind profile kinds a spec may name.
PROFILE_KINDS = ("uniform", "layered", "milspec", "nwp")
#: MIL-F-8785C 3.7.3.2: the two roughness lengths and the validity range, ft.
MILSPEC_Z0_FT = (0.15, 2.0)
MILSPEC_Z0_DEFAULT_FT = 0.15
MILSPEC_REFERENCE_HEIGHT_FT = 20.0
MILSPEC_MIN_HEIGHT_FT = 3.0
MILSPEC_MAX_HEIGHT_FT = 1000.0
MILSPEC_STANDARD = ("MIL-F-8785C 3.7.3.2 wind shear: u(h) = W20 ln(h/z0)/ln(20/z0), "
                    "z0 0.15 ft (Category C) or 2.0 ft (other phases), 3 ft <= h <= "
                    "1000 ft [unverified here]")
LAYERED_STANDARD = ("piecewise-linear wind speed and direction between stated layers, "
                    "held beyond the first and last (a stated interpolation, no standard)")
NWP_STANDARD = ("a cached NWP profile at the standard-atmosphere height of each level "
                "pressure (US Standard Atmosphere 1976 layer inversion as JSBSim's "
                "FGStandardAtmosphere has it) [unverified here]")
#: The JSBSim properties the stack writes for the summed wind, NED order.
WIND_PROPERTIES = ("atmosphere/wind-north-fps", "atmosphere/wind-east-fps",
                   "atmosphere/wind-down-fps")
#: The telemetry columns a wind profile returns (recorded, not graded).
TELEMETRY_COLUMNS = ("wind_profile_speed_mps", "wind_layer_index", "shear_dv_dz_per_s")
#: The card block's keys, in the order the host reads them.
CARD_KEYS = ("kind", "layers", "z0_ft", "source")
#: The heights (ft AGL) the milspec card samples the log law at, so the
#: host interpolates between stated points and derives nothing.
MILSPEC_CARD_HEIGHTS_FT = (3.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0)
REFERENCES = (
    "MIL-F-8785C (1980) 3.7.3.2 wind shear (the log law, z0, the validity range) "
    "[unverified here: the specification is not reachable from this container]",
    "Stull, R. B. (1988) An Introduction to Boundary Layer Meteorology, 9.7: the "
    "neutral surface-layer log profile (the same law, as core/environment/wind.py cites it)",
    "US Standard Atmosphere 1976 (NOAA/NASA/USAF): the pressure-to-height inversion "
    "as JSBSim v1.2.4 FGStandardAtmosphere::CalculatePressureAltitude has it "
    "[the tables are unverified here]",
)


class ShearError(ValueError):
    """A wind profile the model cannot deliver, refused by name."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


# -- the refusals, one list for the validator and the providers ----------------------

def layer_problems(layers: Any) -> List[ShearError]:
    """Every way a ``layers`` value is not a profile: not a list of at
    least two ``[altitude_m, speed_kt, direction_deg]`` triples of numbers,
    a negative altitude, a negative speed, a direction outside 0..360, or
    altitudes not strictly ascending (``wind_profile.layers``)."""
    out: List[ShearError] = []
    if not isinstance(layers, (list, tuple)) or len(layers) < 2:
        out.append(ShearError("wind_profile.layers",
                              "a layered profile needs at least two layers of "
                              "[altitude_m, speed_kt, direction_deg]",
                              actual=None if not isinstance(layers, (list, tuple)) else len(layers),
                              limit=2, unit="layers"))
        return out
    altitudes: List[float] = []
    for index, layer in enumerate(layers):
        if (not isinstance(layer, (list, tuple)) or len(layer) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in layer)):
            out.append(ShearError("wind_profile.layers",
                                  f"layer {index} is not a [altitude_m, speed_kt, "
                                  f"direction_deg] triple of numbers: {layer!r}"))
            return out
        altitude, speed, direction = (float(v) for v in layer)
        if altitude < 0.0:
            out.append(ShearError("wind_profile.layers",
                                  f"layer {index} has a negative altitude",
                                  actual=altitude, limit=0.0, unit="m"))
        if speed < 0.0:
            out.append(ShearError("wind_profile.layers",
                                  f"layer {index} has a negative wind speed",
                                  actual=speed, limit=0.0, unit="kt"))
        if not 0.0 <= direction <= 360.0:
            out.append(ShearError("wind_profile.layers",
                                  f"layer {index} direction must lie in [0, 360] degrees",
                                  actual=direction, limit=360.0, unit="deg"))
        altitudes.append(altitude)
    if any(b <= a for a, b in zip(altitudes, altitudes[1:])):
        out.append(ShearError("wind_profile.layers",
                              f"layer altitudes must be strictly ascending, not {altitudes}"))
    return out


def milspec_problems(roughness_ft: Optional[float], initial_agl_ft: float) -> List[ShearError]:
    """``wind_profile.kind`` for the milspec profile: z0 must be one of the
    specification's two values and the scene must start inside 3..1000
    ft above ground (the law's stated range)."""
    out: List[ShearError] = []
    if roughness_ft is not None and float(roughness_ft) not in MILSPEC_Z0_FT:
        out.append(ShearError("wind_profile.kind",
                              f"the milspec profile takes z0 of {MILSPEC_Z0_FT[0]:g} ft "
                              f"(Category C) or {MILSPEC_Z0_FT[1]:g} ft (other phases), "
                              f"not {roughness_ft!r}",
                              actual=roughness_ft, limit=f"{MILSPEC_Z0_FT[0]:g} or "
                                                        f"{MILSPEC_Z0_FT[1]:g}", unit="ft"))
    if not MILSPEC_MIN_HEIGHT_FT <= initial_agl_ft <= MILSPEC_MAX_HEIGHT_FT:
        out.append(ShearError("wind_profile.kind",
                              f"the milspec log law is stated for {MILSPEC_MIN_HEIGHT_FT:g}.."
                              f"{MILSPEC_MAX_HEIGHT_FT:g} ft above ground; the scene starts "
                              f"at {initial_agl_ft:.1f} ft",
                              actual=initial_agl_ft,
                              limit=f"{MILSPEC_MIN_HEIGHT_FT:g}..{MILSPEC_MAX_HEIGHT_FT:g}",
                              unit="ft AGL"))
    return out


# -- the providers -------------------------------------------------------------------

def _shorter_arc(a_deg: float, b_deg: float, f: float) -> float:
    """Direction interpolated from a to b along the shorter arc, f in [0, 1]."""
    delta = (b_deg - a_deg + 180.0) % 360.0 - 180.0
    return (a_deg + f * delta) % 360.0


class _ProfileProvider(WindProvider):
    """What the three profiles share: the whole wind, the per-evaluation
    layer report, the stack's delivery record turned into the record."""

    carries_base_wind = True
    kind = "profile"

    def __init__(self) -> None:
        #: The last evaluation: {"altitude_m", "speed_mps", "layer_index", "dv_dz_per_s"}.
        self.last: Dict[str, float] = {"altitude_m": math.nan, "speed_mps": 0.0,
                                       "layer_index": 0.0, "dv_dz_per_s": 0.0}
        self.evaluations = 0
        self.stated: Dict[str, Any] = {}
        self.uniform_speed_mps: Optional[float] = None
        self.initial_altitude_m: Optional[float] = None

    def profile_at(self, position: Position) -> Tuple[float, float, int, float]:
        """``(speed_mps, from_deg, layer_index, dv_dz_per_s)`` at a position."""
        raise NotImplementedError

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        speed, from_deg, layer, dv_dz = self.profile_at(position)
        self.last = {"altitude_m": float(position.altitude_m), "speed_mps": float(speed),
                     "layer_index": float(layer), "dv_dz_per_s": float(dv_dz)}
        self.evaluations += 1
        return WindNED.from_meteorological(speed, from_deg)

    def model_block(self) -> Model:
        raise NotImplementedError

    def null_reference(self) -> Tuple[float, float, str]:
        """``(with, without, note)`` for the in-run null test: the profile's
        speed at the initial altitude against the uniform spec wind."""
        if self.initial_altitude_m is None:
            raise ValueError("the profile's initial altitude was never given")
        speed = self.profile_at(Position(0.0, 0.0, self.initial_altitude_m,
                                         self.initial_agl_m, self.terrain_m))[0]
        uniform = 0.0 if self.uniform_speed_mps is None else self.uniform_speed_mps
        return speed, uniform, (f"with = the profile's speed at the initial altitude "
                                f"{self.initial_altitude_m:.1f} m; without = the uniform "
                                f"wind the spec states ({uniform:.3f} m/s), the wind_profile "
                                f"kind 'uniform' delivers")

    def set_scene(self, initial_altitude_m: float, terrain_m: float,
                  uniform_speed_mps: float) -> None:
        self.initial_altitude_m = float(initial_altitude_m)
        self.terrain_m = float(terrain_m)
        self.initial_agl_m = self.initial_altitude_m - self.terrain_m
        self.uniform_speed_mps = float(uniform_speed_mps)

    def applied_variables(self, delivery: Optional[Dict[str, Any]] = None) -> List[AppliedVariable]:
        """One record per stated ``wind_profile`` field (``kind`` always,
        ``layers`` / ``roughness_ft`` / ``fixture`` when stated) with the
        wind channel's read-back the stack measured."""
        delivery = dict(delivery or {})
        wind = delivery.get("wind") or {}
        errors = wind.get("max_abs_error") or {}
        last_written = wind.get("last_written") or {}
        last_read = wind.get("last_read") or {}
        prop = WIND_PROPERTIES[0]
        readback = None
        if prop in last_written and prop in last_read:
            readback = Readback(
                property=prop, value=float(last_read[prop]), written=float(last_written[prop]),
                tolerance=0.0, tolerance_kind="absolute",
                basis=("read back before the next step's write; JSBSim holds the wind "
                       "written (a uniform wind set once persists, measured in "
                       "tests/test_environment.py); the per-step maximum over the run "
                       "is in parameters.per_step_readback"))
        with_, without, note = self.null_reference()
        null = NullTest(
            quantity="wind speed delivered at the initial altitude", unit="m/s",
            with_value=with_, without_value=without, threshold=u.kt_to_mps(0.1), note=note)
        parameters: Dict[str, Any] = {
            "kind": self.kind,
            "delivery": {"wind_channel": "atmosphere/wind-*-fps every step (the summed "
                                         "WindProvider wind; the profile carries the "
                                         "whole horizontal wind)",
                         "steps_written": wind.get("steps_written", 0),
                         "evaluations": self.evaluations,
                         "trim": "trimmed in the profile's wind at the initial altitude"},
            "per_step_readback": {
                "steps_checked": wind.get("steps_checked", 0),
                "max_abs_error": dict(errors), "tolerance": 0.0,
                "agrees": all(e == 0.0 for e in errors.values()),
                "basis": "each wind property read back before the next step's write"},
            "last": dict(self.last),
            "initial_altitude_m": self.initial_altitude_m,
            "uniform_speed_mps": self.uniform_speed_mps,
        }
        parameters.update(self.record_parameters())
        common = dict(model=self.model_block().name, model_block=self.model_block(),
                      references=REFERENCES, properties_written=WIND_PROPERTIES,
                      jsbsim_writes=tuple(JsbsimWrite(p, "before trim (at the initial "
                                                          "altitude) and every step")
                                          for p in WIND_PROPERTIES),
                      telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                      readback=readback, null_test=null, not_claimed=self.not_claimed())
        out: List[AppliedVariable] = []
        kind_stated = self.stated.get("kind") or {"value": self.kind, "source": "user"}
        out.append(AppliedVariable(
            name="wind_profile.kind", value=kind_stated.get("value", self.kind), unit="word",
            source=str(kind_stated.get("source", "user")), frm=kind_stated.get("from"),
            std=kind_stated.get("std"), parameters=parameters, **common))
        for field, unit in (("layers", "[m, kt, deg]"), ("roughness_ft", "ft"),
                            ("fixture", "name")):
            stated = self.stated.get(field)
            if not stated or stated.get("value") is None:
                continue
            out.append(AppliedVariable(
                name=f"wind_profile.{field}", value=stated["value"], unit=unit,
                source=str(stated.get("source", "user")), frm=stated.get("from"),
                std=stated.get("std"),
                parameters={"applied_to": f"the {self.kind} profile",
                            "delivery": parameters["delivery"],
                            "per_step_readback": parameters["per_step_readback"],
                            **self.record_parameters()},
                **common))
        return out

    def record_parameters(self) -> Dict[str, Any]:
        return {}

    def not_claimed(self) -> Tuple[str, ...]:
        return (
            "any time evolution of the profile (frozen)",
            "a vertical wind component",
            "the engine side: the card block is pinned; nothing applies it here",
        )


class LayeredWind(_ProfileProvider):
    """Piecewise-linear speed and direction by altitude layers (see the
    module docstring). ``layers``: ``[[altitude_m, speed_kt,
    direction_deg], ...]``, checked by :func:`layer_problems`."""

    name = "layered_wind"
    kind = "layered"

    def __init__(self, layers: Sequence[Sequence[float]], source: str = "spec") -> None:
        super().__init__()
        problems = layer_problems(layers)
        if problems:
            raise problems[0]
        self.layers: Tuple[Tuple[float, float, float], ...] = tuple(
            (float(a), float(s), float(d)) for a, s, d in layers)
        self.source = str(source)

    def profile_at(self, position: Position) -> Tuple[float, float, int, float]:
        z = float(position.altitude_m)
        first = self.layers[0]
        if z <= first[0]:
            return u.kt_to_mps(first[1]), first[2], 0, 0.0
        for index, (lower, upper) in enumerate(zip(self.layers, self.layers[1:])):
            if z <= upper[0]:
                f = (z - lower[0]) / (upper[0] - lower[0])
                speed = u.kt_to_mps(lower[1] + f * (upper[1] - lower[1]))
                dv_dz = u.kt_to_mps(upper[1] - lower[1]) / (upper[0] - lower[0])
                return speed, _shorter_arc(lower[2], upper[2], f), index, dv_dz
        last = self.layers[-1]
        return u.kt_to_mps(last[1]), last[2], len(self.layers) - 1, 0.0

    def card_block(self) -> Dict[str, Any]:
        return {"kind": self.kind, "layers": [list(layer) for layer in self.layers],
                "z0_ft": None, "source": self.source}

    def model_block(self) -> Model:
        return Model(name="layered wind (piecewise linear by altitude)", standard=LAYERED_STANDARD,
                     version="1", parameters={"layers": [list(l) for l in self.layers],
                                              "altitude_datum": "above mean sea level (the "
                                                                "spec's altitude datum)",
                                              "beyond_the_layers": "held at the first / last",
                                              "direction": "shorter arc", "source": self.source},
                     references=REFERENCES[1:2])

    def record_parameters(self) -> Dict[str, Any]:
        return {"layers": [list(l) for l in self.layers], "source": self.source}

    def vocabulary(self) -> List[Term]:
        return [Term("layered", f"{len(self.layers)} layers", None, LAYERED_STANDARD,
                     note="[altitude_m, speed_kt, direction_deg]; linear between, held beyond")]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(), "kind": self.kind,
                "layers": [list(l) for l in self.layers], "source": self.source,
                "carries_base_wind": True}


class MilSpecShear(_ProfileProvider):
    """The MIL-F-8785C 3.7.3.2 log law (see the module docstring)."""

    name = "milspec_shear"
    kind = "milspec"

    def __init__(self, w20_kt: float, from_deg: float,
                 roughness_ft: Optional[float] = None) -> None:
        super().__init__()
        z0 = MILSPEC_Z0_DEFAULT_FT if roughness_ft is None else float(roughness_ft)
        if z0 not in MILSPEC_Z0_FT:
            raise milspec_problems(z0, MILSPEC_REFERENCE_HEIGHT_FT)[0]
        if float(w20_kt) < 0.0:
            raise ValueError("W20 is a wind speed at or above 0 kt")
        self.w20_kt = float(w20_kt)
        self.from_deg = float(from_deg) % 360.0
        self.z0_ft = z0
        self.held_steps = 0

    def speed_kt_at_agl_ft(self, h_ft: float) -> float:
        """u(h), held at the range's ends."""
        h = min(max(float(h_ft), MILSPEC_MIN_HEIGHT_FT), MILSPEC_MAX_HEIGHT_FT)
        return (self.w20_kt * math.log(h / self.z0_ft)
                / math.log(MILSPEC_REFERENCE_HEIGHT_FT / self.z0_ft))

    def dv_dz_per_s(self, h_ft: float) -> float:
        """du/dh in (m/s)/m: W20 / (h ln(20/z0)), 0 where the profile is held."""
        if not MILSPEC_MIN_HEIGHT_FT <= h_ft <= MILSPEC_MAX_HEIGHT_FT:
            return 0.0
        return (u.kt_to_mps(self.w20_kt) / (u.ft_to_m(h_ft)
                * math.log(MILSPEC_REFERENCE_HEIGHT_FT / self.z0_ft)))

    def profile_at(self, position: Position) -> Tuple[float, float, int, float]:
        h_ft = u.m_to_ft(position.agl_m)
        if not MILSPEC_MIN_HEIGHT_FT <= h_ft <= MILSPEC_MAX_HEIGHT_FT:
            self.held_steps += 1
        layer = 0 if h_ft < MILSPEC_MIN_HEIGHT_FT else (2 if h_ft > MILSPEC_MAX_HEIGHT_FT else 1)
        return (u.kt_to_mps(self.speed_kt_at_agl_ft(h_ft)), self.from_deg, layer,
                self.dv_dz_per_s(h_ft))

    def card_block(self) -> Dict[str, Any]:
        """The log law sampled at fixed heights (ft AGL -> m AGL) so the
        host interpolates between stated points; ``z0_ft`` names the law."""
        layers = [[u.ft_to_m(h), self.speed_kt_at_agl_ft(h), self.from_deg]
                  for h in MILSPEC_CARD_HEIGHTS_FT]
        return {"kind": self.kind, "layers": layers, "z0_ft": self.z0_ft,
                "source": f"MIL-F-8785C 3.7.3.2 log law, W20 {self.w20_kt:g} kt, heights AGL"}

    def model_block(self) -> Model:
        return Model(name="MIL-F-8785C 3.7.3.2 log-law wind shear", standard=MILSPEC_STANDARD,
                     version="1",
                     parameters={"w20_kt": self.w20_kt, "z0_ft": self.z0_ft,
                                 "reference_height_ft": MILSPEC_REFERENCE_HEIGHT_FT,
                                 "valid_ft_agl": [MILSPEC_MIN_HEIGHT_FT, MILSPEC_MAX_HEIGHT_FT],
                                 "outside_the_range": "held at the ends, counted",
                                 "height_datum": "above ground"},
                     references=REFERENCES[:2])

    def record_parameters(self) -> Dict[str, Any]:
        return {"w20_kt": self.w20_kt, "z0_ft": self.z0_ft, "held_steps": self.held_steps}

    def vocabulary(self) -> List[Term]:
        return [Term(f"z0 {z0:g} ft", z0, "ft", MILSPEC_STANDARD,
                     (MILSPEC_MIN_HEIGHT_FT, MILSPEC_MAX_HEIGHT_FT),
                     note="Category C flight phases" if z0 == 0.15 else "other flight phases")
                for z0 in MILSPEC_Z0_FT]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(), "kind": self.kind, "w20_kt": self.w20_kt,
                "from_deg": self.from_deg, "z0_ft": self.z0_ft,
                "valid_ft_agl": [MILSPEC_MIN_HEIGHT_FT, MILSPEC_MAX_HEIGHT_FT],
                "carries_base_wind": True}

    def not_claimed(self) -> Tuple[str, ...]:
        return super().not_claimed() + (
            "the specification's z0 values and phase assignment beyond memory (unverified here)",
            "stability corrections to the log law",
        )


# -- the NWP fixture ------------------------------------------------------------------

def fixture_paths(name: str, directory: Optional[Path] = None) -> Tuple[Path, Path]:
    base = Path(directory) if directory is not None else NWP_DIR
    return base / f"{name}.json", base / f"{name}.provenance.json"


def load_fixture(name: str, directory: Optional[Path] = None) -> Dict[str, Any]:
    """The fixture's data and sidecar, digest-checked: ``{name, levels,
    provenance, sha256, path}``. Refuses ``weather.fixture_missing`` and
    ``weather.fixture_digest`` by name."""
    if not isinstance(name, str) or not name.strip() or "/" in name or "\\" in name:
        raise ShearError("weather.fixture_missing",
                         f"a fixture is named by its file stem under assets/nwp, not {name!r}")
    data_path, sidecar_path = fixture_paths(name, directory)
    if not data_path.is_file() or not sidecar_path.is_file():
        raise ShearError("weather.fixture_missing",
                         f"no cached fixture {name!r}: {data_path.name} and "
                         f"{sidecar_path.name} must both exist under {data_path.parent}")
    raw = data_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    expected = sidecar.get("sha256")
    if not isinstance(expected, str) or expected != digest:
        raise ShearError("weather.fixture_digest",
                         f"fixture {name!r}: the data file's sha256 {digest[:12]}... is not the "
                         f"sidecar's {str(expected)[:12]}...; the cache was altered or the "
                         f"sidecar names none")
    data = json.loads(raw.decode("utf-8"))
    levels = data.get("levels")
    if (not isinstance(levels, list) or len(levels) < 2
            or any(not isinstance(l, list) or len(l) != 3 for l in levels)):
        raise ShearError("weather.fixture_digest",
                         f"fixture {name!r}: levels are [pressure_hpa, u_mps, v_mps] "
                         f"triples, at least two")
    return {"name": name, "levels": levels, "provenance": sidecar, "sha256": digest,
            "path": data_path.as_posix(), "data": data}


def standard_height_m(pressure_hpa: float) -> float:
    """The US Standard Atmosphere 1976 geometric height of a pressure level
    (the inversion core/environment/atmosphere.py transcribes)."""
    from .atmosphere import hpa_to_psf, pressure_altitude_ft

    return u.ft_to_m(pressure_altitude_ft(hpa_to_psf(float(pressure_hpa))))


def layers_from_levels(levels: Sequence[Sequence[float]]) -> List[List[float]]:
    """``[[altitude_m, speed_kt, direction_deg], ...]`` ascending in
    height from ``[pressure_hpa, u_mps (east), v_mps (north)]`` levels."""
    out = []
    for p, east, north in levels:
        speed = math.hypot(float(north), float(east))
        from_deg = (math.degrees(math.atan2(-float(east), -float(north))) % 360.0
                    if speed > 0.0 else 0.0)
        out.append([standard_height_m(p), u.mps_to_kt(speed), from_deg])
    out.sort(key=lambda layer: layer[0])
    return out


class NwpFixture(LayeredWind):
    """A cached NWP profile as a layered wind at standard heights."""

    name = "nwp_fixture"
    kind = "nwp"

    def __init__(self, fixture_name: str, directory: Optional[Path] = None) -> None:
        loaded = load_fixture(fixture_name, directory)
        self.fixture = loaded
        super().__init__(layers_from_levels(loaded["levels"]),
                         source=f"nwp fixture {fixture_name} sha256 {loaded['sha256']}")
        self.fixture_name = fixture_name

    def card_block(self) -> Dict[str, Any]:
        block = super().card_block()
        block["kind"] = self.kind
        return block

    def model_block(self) -> Model:
        prov = self.fixture["provenance"]
        return Model(name="NWP fixture as a layered wind at standard-atmosphere heights",
                     standard=NWP_STANDARD, version="1",
                     parameters={"fixture": self.fixture_name, "url": prov.get("url"),
                                 "fetched_at": prov.get("fetched_at"),
                                 "sha256": self.fixture["sha256"],
                                 "synthetic": bool(prov.get("synthetic", False)),
                                 "levels": self.fixture["levels"],
                                 "layers": [list(l) for l in self.layers],
                                 "height_basis": "standard-atmosphere height of each level pressure"},
                     references=REFERENCES[2:3])

    def record_parameters(self) -> Dict[str, Any]:
        prov = self.fixture["provenance"]
        return {"fixture": self.fixture_name, "url": prov.get("url"),
                "fetched_at": prov.get("fetched_at"), "sha256": self.fixture["sha256"],
                "synthetic": bool(prov.get("synthetic", False)),
                "levels": self.fixture["levels"], "layers": [list(l) for l in self.layers]}

    def not_claimed(self) -> Tuple[str, ...]:
        extra = ("the model's own heights: standard-atmosphere heights of the level pressures",)
        if self.fixture["provenance"].get("synthetic"):
            extra += ("a real forecast: the fixture is a synthetic stand-in (its sidecar says so)",)
        return super().not_claimed() + extra

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(), "kind": self.kind, "fixture": self.fixture_name,
                "sha256": self.fixture["sha256"],
                "url": self.fixture["provenance"].get("url"),
                "fetched_at": self.fixture["provenance"].get("fetched_at"),
                "synthetic": bool(self.fixture["provenance"].get("synthetic", False))}
