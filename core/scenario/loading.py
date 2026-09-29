"""Loading (P4): payload stations, fuel, and the centre of gravity read
back against the hand calculation.

What this module does
---------------------
A spec's ``loading`` block names payload stations by name (kg each) and
the fuel as a mass or as a fraction of capacity. The stations, their
arms, the tanks and their capacities are the loaded JSBSim model's own,
transcribed into ``assets/aircraft_config/<fdm>.json`` under ``loading``
with a source string each and CROSS-CHECKED against the live model
before anything is written (``loading.config`` otherwise). The plan
writes ``inertia/pointmass-weight-lbs[i]`` per stated station and
``propulsion/tank[i]/contents-lbs`` per tank ONCE, before the trim and
after the atmosphere writes (``EnvironmentStack.prepare``), re-latches
the initial conditions so FGMassBalance recomputes (measured: the CG
property is stale until a model pass), reads every property back, and
compares JSBSim's ``inertia/cg-x-in`` with the hand calculation

    CG = sum(m_i x_i) / sum(m_i)

over the empty weight, every station (stated or the XML's own weight)
and every tank, in the XML's own inches aft of the XML's own datum,
within :data:`CG_TOLERANCE_IN` = 0.1 in (V13). A write AFTER the trim
would leave the trim solved for the unloaded aircraft (measured on the
c172p: 300 lb written after the trim at the baggage station leaves the
elevator at its 4.31 deg and the aircraft pitches to 9.7 deg and climbs
20 m in 5 s; written before, the trim moves the elevator to 5.54 deg
and the loaded aircraft holds altitude like the unloaded one).

Refusals by name (``LoadingError.constraint``, the SAME list the
validator renders as ``Violation``s through :meth:`LoadingPlan.problems`):

* ``loading.config`` -- the airframe's block is malformed, or the
  configured arms, defaults and capacities are not the loaded model's;
* ``loading.station_unknown`` -- a station the airframe does not list,
  or one a system of the model rewrites every pass (the p51d's twelve
  weapon stations: 300 lb written reads 0.0 after one pass, measured);
* ``loading.station_mass`` -- a negative mass or one over the station's
  stated maximum;
* ``loading.fuel_range`` -- fuel below zero (a zero load leaves the
  engines nothing to start on), over the tanks' capacity, a fraction
  outside 0..1, or the mass and the fraction both stated;
* ``loading.max_weight`` -- the gross weight over the airframe's stated
  maximum takeoff weight;
* ``loading.cg_envelope`` -- the CG outside the handbook polygon, where
  the airframe's arm comparison admits the check;
* ``loading.datum_unverified`` -- the envelope check ASKED FOR on an
  airframe whose arm comparison is not green. The runner never asks: it
  flies the loading at the XML's arms and records the reason (lesson
  from wave 3: a refusal is for what the user asked and cannot have).

The arm comparison (``datum.arm_comparison.status`` in the config):
``inferred`` for the c172p (XML arms 36 / 70 / 95 in against the
handbook's 37 / 73 / 95 in: the XML datum is taken as the handbook
datum with a 3 in uncertainty, both recorded), ``unverified`` for the
A320, B747, DHC6 and p51d (no handbook arm transcribed, or an envelope
in percent MAC of a datum the XML does not name). Every airframe passes
the XML half of the comparison (the configured arms equal the loaded
model's, tests/test_loading.py); only the c172p has a handbook half.

What is NOT claimed: any handbook number (arms, maxima, the polygon,
the maximum weights are from memory and marked so in the config); the
lateral and vertical CG (only ``cg-x-in`` is compared); the fuel burn
during the engine crank (0.0055 lb on the c172p before the trim,
measured; the read-back is taken before it); tank priorities, unusable
fuel, or any fuel schedule; the engine side (the card block carries the
writes; no host applies them here).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..environment.base import AtmosphereProvider, Position, Term
from ..fdm import units as u
from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

#: V13: the hand CG and JSBSim's cg-x-in agree within this (measured
#: 1e-12 in on five airframes; the tolerance is the blueprint's).
CG_TOLERANCE_IN = 0.1
#: The fuel null test's floor in kg: a stated half kilogram (the c172p
#: crank burns 0.0025 kg before the trim, measured).
FUEL_NULL_FLOOR_KG = 0.5
#: How a stated fuel MASS is shared between the tanks.
FUEL_FILL_RULE = "each tank receives the stated mass times its capacity over the sum of capacities"
#: JSBSim's properties, read back.
PROPERTY_CG = "inertia/cg-x-in"
PROPERTY_IYY = "inertia/iyy-slugs_ft2"
PROPERTY_WEIGHT = "inertia/weight-lbs"
PROPERTY_EMPTY = "inertia/empty-weight-lbs"
PROPERTY_FUEL = "propulsion/total-fuel-lbs"
#: The telemetry columns the loading returns per step (recorded, not
#: graded by Gate 5): the CG in metres aft of the XML datum, the pitch
#: inertia in kg m^2, the gross mass.
TELEMETRY_COLUMNS = ("cg_x_m", "iyy_kgm2", "weight_kg")
#: The card block's keys, in the order the host reads them.
CARD_KEYS = ("stations", "tanks", "expected_cg_in", "tolerance_in", "datum")
WHEN = "once, before the trim (after the atmosphere writes; EnvironmentStack.prepare)"
MODEL = ("hand weight and balance: CG = sum(m x) / sum(m) over the empty weight, the "
         "point-mass stations and the tanks at the XML's own arms, compared with JSBSim "
         "1.2.4 FGMassBalance's inertia/cg-x-in")
REFERENCES = (
    "JSBSim v1.2.4 src/models/FGMassBalance.cpp: the point masses and tank contents summed "
    "into the CG and the inertia tensor each model pass; inertia/pointmass-weight-lbs[i] "
    "and propulsion/tank[i]/contents-lbs are read-write (probed on the live catalog)",
    "ADVANCEMENTS_BLUEPRINT section 1, work item P4: W&B CG = sum m x / sum m; the "
    "envelope polygon from the POH/AFM [unverified here]",
)
_ARM_COMPARISON_GREEN = ("verified", "inferred")

_SLUGFT2_TO_KGM2 = u.KGM3_PER_SLUGFT3 * u.M_PER_FT ** 5


class LoadingError(ValueError):
    """A loading the model cannot deliver, refused by name."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


def station_key(name: Any) -> str:
    """A station name as the spec may spell it (``Right Passenger``,
    ``right_passenger``, ``right-passenger``) reduced to one key."""
    return re.sub(r"[\s_\-]+", "_", str(name).strip().lower())


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _suffix(index: int) -> str:
    return "" if index == 0 else f"[{index}]"


# -- the configured airframe ---------------------------------------------------------

@dataclass(frozen=True)
class Station:
    """One point-mass station of the model, as the config lists it."""

    name: str
    index: int
    arm_in: float
    default_lb: float
    max_kg: float
    source: str
    poh_arm_in: Optional[float] = None
    loadable: bool = True
    reason: Optional[str] = None

    @property
    def key(self) -> str:
        return station_key(self.name)

    @property
    def jsbsim_property(self) -> str:
        return f"inertia/pointmass-weight-lbs{_suffix(self.index)}"

    @property
    def location_property(self) -> str:
        return f"inertia/pointmass-location-X-inches{_suffix(self.index)}"

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "index": self.index, "arm_in": self.arm_in,
                "poh_arm_in": self.poh_arm_in, "default_lb": self.default_lb,
                "max_kg": self.max_kg, "loadable": self.loadable, "source": self.source,
                "reason": self.reason, "property": self.jsbsim_property}


@dataclass(frozen=True)
class Tank:
    """One fuel tank of the model, as the config lists it."""

    index: int
    arm_in: float
    capacity_lb: float
    default_lb: float
    source: str
    poh_arm_in: Optional[float] = None

    @property
    def jsbsim_property(self) -> str:
        return f"propulsion/tank{_suffix(self.index)}/contents-lbs"

    @property
    def location_property(self) -> str:
        return f"propulsion/tank{_suffix(self.index)}/x-position"

    @property
    def pct_full_property(self) -> str:
        return f"propulsion/tank{_suffix(self.index)}/pct-full"

    def to_dict(self) -> Dict[str, Any]:
        return {"index": self.index, "arm_in": self.arm_in, "poh_arm_in": self.poh_arm_in,
                "capacity_lb": self.capacity_lb, "default_lb": self.default_lb,
                "source": self.source, "property": self.jsbsim_property}


@dataclass(frozen=True)
class LoadingConfig:
    """The airframe's ``loading`` block, parsed and checked."""

    aircraft: str
    source: str
    datum: Dict[str, Any]
    empty_lb: float
    empty_arm_in: float
    empty_source: str
    stations: Tuple[Station, ...]
    tanks: Tuple[Tank, ...]
    max_takeoff_weight_kg: float
    max_takeoff_weight_source: str
    envelope_polygon: Optional[Tuple[Tuple[float, float], ...]]
    envelope_source: Optional[str]
    envelope_reason: Optional[str]
    policy_station: Optional[str]
    policy_station_reason: str
    config_path: str = ""
    config_sha256: str = ""

    @property
    def arm_comparison_status(self) -> str:
        return str(self.datum.get("arm_comparison", {}).get("status", "unverified"))

    @property
    def envelope_admitted(self) -> bool:
        """The envelope check runs only for a polygon on an airframe whose
        arm comparison is green (verified or inferred)."""
        return (self.envelope_polygon is not None
                and self.arm_comparison_status in _ARM_COMPARISON_GREEN)

    def envelope_refusal(self) -> Optional[LoadingError]:
        """Why the envelope check cannot run, by name, or None when it can."""
        if self.envelope_admitted:
            return None
        if self.envelope_polygon is None:
            why = self.envelope_reason or "no handbook envelope is transcribed"
        else:
            why = str(self.datum.get("arm_comparison", {}).get(
                "reason", "the arm comparison is not green"))
        return LoadingError(
            "loading.datum_unverified",
            f"{self.aircraft}: the centre-of-gravity envelope cannot be checked -- {why}; "
            f"the loading is flown at the XML's own arms and the envelope is not claimed",
            actual=self.arm_comparison_status)

    def station(self, name: Any) -> Station:
        """The station a spec names, or ``loading.station_unknown``."""
        key = station_key(name)
        for station in self.stations:
            if station.key == key:
                if not station.loadable:
                    raise LoadingError(
                        "loading.station_unknown",
                        f"{self.aircraft}: station {station.name!r} cannot be loaded: "
                        f"{station.reason}", actual=str(name))
                return station
        loadable = [s.name for s in self.stations if s.loadable]
        raise LoadingError(
            "loading.station_unknown",
            f"{self.aircraft}: no payload station named {str(name)!r}; the loadable "
            f"stations are {loadable}" + ("" if loadable else " (the model declares none)"),
            actual=str(name))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "aircraft": self.aircraft, "source": self.source, "datum": dict(self.datum),
            "empty_weight": {"lb": self.empty_lb, "arm_in": self.empty_arm_in,
                             "source": self.empty_source},
            "stations": [s.to_dict() for s in self.stations],
            "tanks": [t.to_dict() for t in self.tanks],
            "max_takeoff_weight": {"kg": self.max_takeoff_weight_kg,
                                   "source": self.max_takeoff_weight_source},
            "cg_envelope": {"polygon": (None if self.envelope_polygon is None
                                        else [list(p) for p in self.envelope_polygon]),
                            "source": self.envelope_source, "reason": self.envelope_reason,
                            "admitted": self.envelope_admitted},
            "policy_station": self.policy_station,
            "policy_station_reason": self.policy_station_reason,
            "config_path": self.config_path, "config_sha256": self.config_sha256,
        }


def parse_loading_config(aircraft: str, block: Any, config_path: str = "",
                         config_sha256: str = "") -> LoadingConfig:
    """The block checked field by field; ``loading.config`` names the
    first thing wrong with it. Every number carries a source; a station
    that cannot be loaded carries its reason."""
    def refuse(message: str) -> LoadingError:
        return LoadingError("loading.config", f"{aircraft}: {message}")

    if not isinstance(block, dict):
        raise refuse("the loading block is not a mapping")
    for key in ("source", "datum", "empty_weight", "stations", "tanks", "max_takeoff_weight",
                "cg_envelope", "policy_station", "policy_station_reason"):
        if key not in block:
            raise refuse(f"the loading block has no {key!r}")
    if not _text(block["source"]):
        raise refuse("the loading block states no source")
    datum = block["datum"]
    if (not isinstance(datum, dict) or not _text(datum.get("xml"))
            or not isinstance(datum.get("arm_comparison"), dict)
            or datum["arm_comparison"].get("status") not in ("verified", "inferred", "unverified")):
        raise refuse("datum needs 'xml' and an arm_comparison with a status of verified, "
                     "inferred or unverified")
    empty = block["empty_weight"]
    if (not isinstance(empty, dict) or not _number(empty.get("lb")) or empty["lb"] <= 0.0
            or not _number(empty.get("arm_in")) or not _text(empty.get("source"))):
        raise refuse("empty_weight needs a positive lb, an arm_in and a source")
    stations: List[Station] = []
    seen = set()
    for i, entry in enumerate(block["stations"] if isinstance(block["stations"], list) else ()):
        if not isinstance(entry, dict):
            raise refuse(f"station {i} is not a mapping")
        for key in ("name", "index", "arm_in", "default_lb", "max_kg", "source"):
            if key not in entry:
                raise refuse(f"station {i} has no {key!r}")
        if not _text(entry["name"]) or station_key(entry["name"]) in seen:
            raise refuse(f"station {i}: the name is empty or repeats another station's")
        if (not isinstance(entry["index"], int) or isinstance(entry["index"], bool)
                or entry["index"] < 0 or not _number(entry["arm_in"])
                or not _number(entry["default_lb"]) or entry["default_lb"] < 0.0
                or not _number(entry["max_kg"]) or entry["max_kg"] < 0.0
                or not _text(entry["source"])):
            raise refuse(f"station {entry['name']!r}: index, arm_in, default_lb >= 0, "
                         f"max_kg >= 0 and a source are required")
        loadable = entry.get("loadable", True)
        if not isinstance(loadable, bool) or (not loadable and not _text(entry.get("reason"))):
            raise refuse(f"station {entry['name']!r}: loadable is true or false, and an "
                         f"unloadable station states its reason")
        poh = entry.get("poh_arm_in")
        if poh is not None and not _number(poh):
            raise refuse(f"station {entry['name']!r}: poh_arm_in is a number or null")
        seen.add(station_key(entry["name"]))
        stations.append(Station(name=str(entry["name"]), index=int(entry["index"]),
                                arm_in=float(entry["arm_in"]), default_lb=float(entry["default_lb"]),
                                max_kg=float(entry["max_kg"]), source=str(entry["source"]),
                                poh_arm_in=None if poh is None else float(poh),
                                loadable=loadable, reason=entry.get("reason")))
    if not isinstance(block["stations"], list):
        raise refuse("stations is a list")
    tanks: List[Tank] = []
    if not isinstance(block["tanks"], list) or not block["tanks"]:
        raise refuse("tanks is a non-empty list (every configured airframe carries fuel)")
    for i, entry in enumerate(block["tanks"]):
        if not isinstance(entry, dict):
            raise refuse(f"tank {i} is not a mapping")
        for key in ("index", "arm_in", "capacity_lb", "default_lb", "source"):
            if key not in entry:
                raise refuse(f"tank {i} has no {key!r}")
        if (not isinstance(entry["index"], int) or isinstance(entry["index"], bool)
                or entry["index"] != i or not _number(entry["arm_in"])
                or not _number(entry["capacity_lb"]) or entry["capacity_lb"] <= 0.0
                or not _number(entry["default_lb"]) or entry["default_lb"] < 0.0
                or entry["default_lb"] > entry["capacity_lb"] or not _text(entry["source"])):
            raise refuse(f"tank {i}: index {i}, arm_in, capacity_lb > 0, 0 <= default_lb <= "
                         f"capacity and a source are required")
        poh = entry.get("poh_arm_in")
        if poh is not None and not _number(poh):
            raise refuse(f"tank {i}: poh_arm_in is a number or null")
        tanks.append(Tank(index=i, arm_in=float(entry["arm_in"]),
                          capacity_lb=float(entry["capacity_lb"]),
                          default_lb=float(entry["default_lb"]), source=str(entry["source"]),
                          poh_arm_in=None if poh is None else float(poh)))
    mtow = block["max_takeoff_weight"]
    if (not isinstance(mtow, dict) or not _number(mtow.get("kg")) or mtow["kg"] <= 0.0
            or not _text(mtow.get("source"))):
        raise refuse("max_takeoff_weight needs a positive kg and a source")
    envelope = block["cg_envelope"]
    if not isinstance(envelope, dict) or "polygon" not in envelope:
        raise refuse("cg_envelope needs a polygon (a list of [arm_in, weight_lb] or null)")
    polygon: Optional[Tuple[Tuple[float, float], ...]] = None
    if envelope["polygon"] is not None:
        points = envelope["polygon"]
        if (not isinstance(points, list) or len(points) < 3
                or not all(isinstance(p, list) and len(p) == 2 and all(_number(v) for v in p)
                           for p in points) or not _text(envelope.get("source"))):
            raise refuse("cg_envelope.polygon is at least three [arm_in, weight_lb] points "
                         "with a source")
        polygon = tuple((float(p[0]), float(p[1])) for p in points)
    elif not _text(envelope.get("reason")):
        raise refuse("a null cg_envelope.polygon states its reason")
    policy_station = block["policy_station"]
    if policy_station is not None and not any(
            s.key == station_key(policy_station) and s.loadable for s in stations):
        raise refuse(f"policy_station {policy_station!r} is not a loadable station")
    if not _text(block["policy_station_reason"]):
        raise refuse("policy_station_reason is required")
    return LoadingConfig(
        aircraft=aircraft, source=str(block["source"]), datum=dict(datum),
        empty_lb=float(empty["lb"]), empty_arm_in=float(empty["arm_in"]),
        empty_source=str(empty["source"]), stations=tuple(stations), tanks=tuple(tanks),
        max_takeoff_weight_kg=float(mtow["kg"]), max_takeoff_weight_source=str(mtow["source"]),
        envelope_polygon=polygon, envelope_source=envelope.get("source"),
        envelope_reason=envelope.get("reason"),
        policy_station=None if policy_station is None else str(policy_station),
        policy_station_reason=str(block["policy_station_reason"]),
        config_path=config_path, config_sha256=config_sha256)


def load_loading_config(aircraft: str, config_dir: Optional[Path] = None) -> Optional[LoadingConfig]:
    """The airframe's block, or None when it has no config file or no
    ``loading`` block (not a refusal: an airframe without one flies the
    XML's own loading and a STATED block on it refuses by name)."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    path = directory / f"{aircraft}.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    try:
        config = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LoadingError("loading.config", f"{aircraft}: {path.name} is not readable JSON: {exc}") from exc
    if not isinstance(config, dict) or "loading" not in config:
        return None
    try:
        rel = path.resolve().relative_to(REPO).as_posix()   # the same string on Windows
    except ValueError:
        rel = str(path)
    return parse_loading_config(aircraft, config["loading"], config_path=rel,
                                config_sha256=hashlib.sha256(raw).hexdigest())


# -- the geometry ----------------------------------------------------------------------

def point_in_polygon(x: float, y: float, polygon: Sequence[Tuple[float, float]]) -> bool:
    """Even-odd (ray casting) test; a point ON an edge counts as inside
    (a CG exactly at a limit is at the limit, not beyond it -- the same
    strict comparison the limits monitor uses)."""
    n = len(polygon)
    inside = False
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        # On the edge: collinear and within the segment's bounding box.
        cross = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        if (abs(cross) <= 1e-9 * max(1.0, abs(x1 - x0), abs(y1 - y0))
                and min(x0, x1) - 1e-12 <= x <= max(x0, x1) + 1e-12
                and min(y0, y1) - 1e-12 <= y <= max(y0, y1) + 1e-12):
            return True
        if (y0 > y) != (y1 > y):
            x_at = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_at:
                inside = not inside
    return inside


def hand_cg_in(masses_lb: Sequence[float], arms_in: Sequence[float]) -> float:
    """CG = sum(m x) / sum(m), inches aft of the datum the arms are in."""
    total = sum(masses_lb)
    if total <= 0.0:
        raise ValueError("a hand CG needs a positive total mass")
    return sum(m * x for m, x in zip(masses_lb, arms_in)) / total


# -- the plan ----------------------------------------------------------------------------

@dataclass(frozen=True)
class StatedQuantity:
    """A spec value with its provenance, as the block carried it."""

    value: Any
    source: str = "user"
    frm: Optional[str] = None
    std: Optional[str] = None


@dataclass(frozen=True)
class StationLoad:
    station: Station
    kg: float

    @property
    def lb(self) -> float:
        return u.kg_to_lb(self.kg)


@dataclass(frozen=True)
class TankLoad:
    tank: Tank
    lb: float


@dataclass
class LoadingPlan:
    """What a spec's block asks of a configured airframe: the station
    writes, the tank writes, the hand CG, and every problem by name."""

    config: LoadingConfig
    payload: Optional[StatedQuantity] = None
    fuel_kg: Optional[StatedQuantity] = None
    fuel_fraction: Optional[StatedQuantity] = None
    #: What the runner decided not to do and why (the envelope check on
    #: an airframe whose datum is unverified), carried into the manifest.
    notes: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_spec(cls, spec, config: Optional[LoadingConfig] = None,
                  config_dir: Optional[Path] = None) -> Optional["LoadingPlan"]:
        """The plan a spec asks for, or None for the default block
        (nothing written, nothing recorded). A stated block on an
        airframe with no ``loading`` config refuses ``loading.config``."""
        block = spec.loading
        if block.is_default():
            return None
        aircraft = str(spec.aircraft.value)
        if config is None:
            config = load_loading_config(aircraft, config_dir)
        if config is None:
            raise LoadingError(
                "loading.config",
                f"{aircraft}: a loading is stated but assets/aircraft_config/{aircraft}.json "
                f"carries no loading block (stations, tanks and capacities are read from it)")

        def stated(name: str) -> Optional[StatedQuantity]:
            q = getattr(block, name)
            if q.value is None or str(q.source) == "default":
                return None
            return StatedQuantity(q.value, str(q.source), q.frm, q.std)

        return cls(config=config, payload=stated("payload"), fuel_kg=stated("fuel_kg"),
                   fuel_fraction=stated("fuel_fraction"))

    # -- what is written -------------------------------------------------------------

    def station_loads(self) -> List[StationLoad]:
        """The stated stations resolved by name (refuses by name)."""
        if self.payload is None:
            return []
        mapping = self.payload.value
        if not isinstance(mapping, dict):
            raise LoadingError("loading.station_unknown",
                               f"{self.config.aircraft}: payload must be a mapping of station "
                               f"name to kg, not {mapping!r}", actual=mapping)
        out: List[StationLoad] = []
        seen = set()
        for name, kg in mapping.items():
            station = self.config.station(name)
            if station.key in seen:
                raise LoadingError("loading.station_unknown",
                                   f"{self.config.aircraft}: station {station.name!r} is "
                                   f"named twice in the payload", actual=str(name))
            seen.add(station.key)
            if not _number(kg):
                raise LoadingError("loading.station_mass",
                                   f"{self.config.aircraft}: the mass at {station.name!r} "
                                   f"must be a number of kg, not {kg!r}", actual=kg, unit="kg")
            kg = float(kg)
            if kg < 0.0:
                raise LoadingError("loading.station_mass",
                                   f"{self.config.aircraft}: a negative mass at "
                                   f"{station.name!r}", actual=kg, limit=0.0, unit="kg")
            if kg > station.max_kg:
                raise LoadingError("loading.station_mass",
                                   f"{self.config.aircraft}: {kg:g} kg at {station.name!r} is "
                                   f"over its stated maximum ({station.source})",
                                   actual=kg, limit=station.max_kg, unit="kg")
            out.append(StationLoad(station, kg))
        return out

    def tank_loads(self) -> Optional[List[TankLoad]]:
        """The tank contents the stated fuel implies, or None when no
        fuel is stated (refuses by name)."""
        if self.fuel_kg is not None and self.fuel_fraction is not None:
            raise LoadingError("loading.fuel_range",
                               f"{self.config.aircraft}: fuel_kg and fuel_fraction are one "
                               f"quantity stated two ways; state one of them")
        tanks = self.config.tanks
        capacity_lb = sum(t.capacity_lb for t in tanks)
        if self.fuel_kg is not None:
            value = self.fuel_kg.value
            if not _number(value):
                raise LoadingError("loading.fuel_range",
                                   f"{self.config.aircraft}: fuel_kg must be a number, not "
                                   f"{value!r}", actual=value, unit="kg")
            kg = float(value)
            capacity_kg = u.lb_to_kg(capacity_lb)
            if kg <= 0.0:
                raise LoadingError("loading.fuel_range",
                                   f"{self.config.aircraft}: a fuel load of {kg:g} kg leaves the "
                                   f"engines nothing to start on (must be above 0)",
                                   actual=kg, limit=0.0, unit="kg")
            if kg > capacity_kg:
                raise LoadingError("loading.fuel_range",
                                   f"{self.config.aircraft}: {kg:g} kg of fuel is over the tanks' "
                                   f"capacity of {capacity_kg:.1f} kg ({len(tanks)} tanks)",
                                   actual=kg, limit=capacity_kg, unit="kg")
            total_lb = u.kg_to_lb(kg)
            return [TankLoad(t, total_lb * t.capacity_lb / capacity_lb) for t in tanks]
        if self.fuel_fraction is not None:
            value = self.fuel_fraction.value
            if not _number(value):
                raise LoadingError("loading.fuel_range",
                                   f"{self.config.aircraft}: fuel_fraction must be a number, "
                                   f"not {value!r}", actual=value)
            fraction = float(value)
            if not 0.0 < fraction <= 1.0:
                raise LoadingError("loading.fuel_range",
                                   f"{self.config.aircraft}: a fuel fraction lies in 0..1 "
                                   f"(above 0: the engines need fuel), not {fraction:g}",
                                   actual=fraction, limit="0..1")
            return [TankLoad(t, fraction * t.capacity_lb) for t in tanks]
        return None

    # -- the hand calculation ----------------------------------------------------------

    def masses_and_arms(self, live_station_lb: Optional[Dict[int, float]] = None,
                        live_tank_lb: Optional[Dict[int, float]] = None,
                        ) -> Tuple[List[str], List[float], List[float]]:
        """(labels, masses lb, arms in): the empty weight, every station
        (stated, else the live weight when given, else the config
        default) and every tank (stated, else live, else default)."""
        loads = {load.station.index: load for load in self.station_loads()}
        tank_loads = self.tank_loads()
        tank_lb = {} if tank_loads is None else {tl.tank.index: tl.lb for tl in tank_loads}
        labels = ["empty"]
        masses = [self.config.empty_lb]
        arms = [self.config.empty_arm_in]
        for station in self.config.stations:
            if station.index in loads:
                lb = loads[station.index].lb
            elif live_station_lb is not None and station.index in live_station_lb:
                lb = live_station_lb[station.index]
            else:
                lb = station.default_lb
            labels.append(f"station:{station.name}")
            masses.append(lb)
            arms.append(station.arm_in)
        for tank in self.config.tanks:
            if tank.index in tank_lb:
                lb = tank_lb[tank.index]
            elif live_tank_lb is not None and tank.index in live_tank_lb:
                lb = live_tank_lb[tank.index]
            else:
                lb = tank.default_lb
            labels.append(f"tank:{tank.index}")
            masses.append(lb)
            arms.append(tank.arm_in)
        return labels, masses, arms

    def hand_cg_in(self, live_station_lb: Optional[Dict[int, float]] = None,
                   live_tank_lb: Optional[Dict[int, float]] = None) -> float:
        _, masses, arms = self.masses_and_arms(live_station_lb, live_tank_lb)
        return hand_cg_in(masses, arms)

    def gross_lb(self, live_station_lb: Optional[Dict[int, float]] = None,
                 live_tank_lb: Optional[Dict[int, float]] = None) -> float:
        return sum(self.masses_and_arms(live_station_lb, live_tank_lb)[1])

    # -- the refusals ------------------------------------------------------------------

    def problems(self) -> List[LoadingError]:
        """Every way the stated loading is outside what the airframe
        admits, each by name, in order: the stations, the fuel, the
        gross weight, the envelope (where the datum admits it)."""
        out: List[LoadingError] = []
        try:
            self.station_loads()
        except LoadingError as exc:
            out.append(exc)
        try:
            self.tank_loads()
        except LoadingError as exc:
            out.append(exc)
        if out:
            return out
        gross_kg = u.lb_to_kg(self.gross_lb())
        if gross_kg > self.config.max_takeoff_weight_kg:
            out.append(LoadingError(
                "loading.max_weight",
                f"{self.config.aircraft}: the loaded weight {gross_kg:.1f} kg (empty weight, "
                f"every station and the fuel) is over the maximum takeoff weight "
                f"({self.config.max_takeoff_weight_source})",
                actual=round(gross_kg, 1), limit=self.config.max_takeoff_weight_kg, unit="kg"))
        envelope = self.envelope_check()
        if envelope.get("checked") and not envelope["inside"]:
            out.append(LoadingError(
                "loading.cg_envelope",
                f"{self.config.aircraft}: the centre of gravity at {envelope['cg_in']:.2f} in "
                f"aft of the datum with {envelope['weight_lb']:.0f} lb lies outside the handbook "
                f"envelope ({self.config.envelope_source}); on the arm comparison "
                f"{self.config.arm_comparison_status!r} with the stated datum uncertainty",
                actual=round(envelope["cg_in"], 2), unit="in"))
        return out

    def envelope_check(self) -> Dict[str, Any]:
        """The polygon test on (hand CG, gross weight), or the reason it
        did not run, recorded (never a refusal of the flight)."""
        refusal = self.config.envelope_refusal()
        cg = self.hand_cg_in()
        weight = self.gross_lb()
        if refusal is not None:
            note = {"check": "cg_envelope", "checked": False, "inside": None,
                    "constraint": refusal.constraint, "reason": refusal.message,
                    "cg_in": cg, "weight_lb": weight}
            if note not in self.notes:
                self.notes.append(note)
            return note
        polygon = self.config.envelope_polygon
        assert polygon is not None
        comparison = self.config.datum.get("arm_comparison", {})
        return {"check": "cg_envelope", "checked": True,
                "inside": point_in_polygon(cg, weight, polygon), "cg_in": cg,
                "weight_lb": weight, "polygon": [list(p) for p in polygon],
                "source": self.config.envelope_source,
                "arm_comparison_status": self.config.arm_comparison_status,
                "datum_uncertainty_in": comparison.get("max_station_difference_in"),
                "note": comparison.get("inference")}

    def require_envelope(self) -> Dict[str, Any]:
        """The envelope check ASKED FOR: refuses ``loading.datum_unverified``
        on an airframe whose arm comparison is not green, else returns
        the check. The runner never calls this (it records the reason
        instead); the API and the tests do."""
        refusal = self.config.envelope_refusal()
        if refusal is not None:
            raise refusal
        return self.envelope_check()

    # -- the card ------------------------------------------------------------------------

    def card_block(self) -> Dict[str, Any]:
        """The EXACT JSBSim writes for the UE host, in a fixed key order:
        the stations (name, property, lbs), the tanks (index, property,
        lbs), the CG the host must read back within ``tolerance_in``
        after the writes and before its trim, and the datum the arms
        are in."""
        stations = [{"name": load.station.name, "property": load.station.jsbsim_property,
                     "lbs": load.lb} for load in self.station_loads()]
        tank_loads = self.tank_loads() or []
        tanks = [{"index": tl.tank.index, "property": tl.tank.jsbsim_property, "lbs": tl.lb}
                 for tl in tank_loads]
        block = {
            "stations": stations,
            "tanks": tanks,
            "expected_cg_in": self.hand_cg_in(),
            "tolerance_in": CG_TOLERANCE_IN,
            "datum": {"frame": str(self.config.datum.get("xml")),
                      "arm_comparison_status": self.config.arm_comparison_status,
                      "applied": WHEN},
        }
        if tuple(block) != CARD_KEYS:
            raise RuntimeError(f"loading card keys {list(block)} are not the fixed order "
                               f"{list(CARD_KEYS)}")
        return block

    def to_dict(self) -> Dict[str, Any]:
        labels, masses, arms = self.masses_and_arms()
        return {
            "aircraft": self.config.aircraft,
            "stated": {
                "payload": None if self.payload is None else self.payload.__dict__,
                "fuel_kg": None if self.fuel_kg is None else self.fuel_kg.__dict__,
                "fuel_fraction": None if self.fuel_fraction is None else self.fuel_fraction.__dict__,
            },
            "hand": {"labels": labels, "masses_lb": masses, "arms_in": arms,
                     "cg_in": hand_cg_in(masses, arms), "gross_lb": sum(masses),
                     "datum": str(self.config.datum.get("xml"))},
            "fuel_fill_rule": FUEL_FILL_RULE,
            "notes": [dict(n) for n in self.notes],
        }


# -- the provider ---------------------------------------------------------------------------

class LoadingProvider(AtmosphereProvider):
    """The loading, written once before the trim through the stack's
    pre-trim hook. An ``AtmosphereProvider`` by TYPE so the existing
    ``EnvironmentStack.prepare`` runs it after the atmosphere writes
    (the stack's atmosphere slot is the one with a pre-trim hook); it
    writes nothing per step (``properties`` is empty) and reads back
    the post-trim state once at the first step (``observe``).
    """

    name = "loading"

    def __init__(self, plan: LoadingPlan) -> None:
        found = plan.problems()
        if found:
            raise found[0]
        self.plan = plan
        self.prepared: Optional[Dict[str, Any]] = None
        self.post_trim: Optional[Dict[str, Any]] = None

    @classmethod
    def from_spec(cls, spec, config_dir: Optional[Path] = None) -> Optional["LoadingProvider"]:
        """The provider a spec asks for, or None for the default block."""
        plan = LoadingPlan.from_spec(spec, config_dir=config_dir)
        if plan is None:
            return None
        return cls(plan)

    def properties(self, position: Position, time_s: float) -> Dict[str, float]:
        return {}

    def vocabulary(self) -> List[Term]:
        config = self.plan.config
        terms = [Term(f"station {s.name}", s.max_kg, "kg", s.source,
                      note=f"arm {s.arm_in} in (XML)"
                           + ("" if s.poh_arm_in is None else f", handbook {s.poh_arm_in} in")
                           + ("" if s.loadable else "; not loadable: " + str(s.reason)))
                 for s in config.stations]
        terms.append(Term("fuel_fraction", 1.0, "1", FUEL_FILL_RULE,
                          valid_range=(0.0, 1.0),
                          note=f"{len(config.tanks)} tanks, "
                               f"{sum(t.capacity_lb for t in config.tanks):.1f} lb capacity"))
        return terms

    # -- before the trim -----------------------------------------------------------------

    def _read(self, fdm) -> Dict[str, Any]:
        g = fdm.props.get
        return {
            "cg_x_in": g(PROPERTY_CG),
            "weight_lb": g(PROPERTY_WEIGHT),
            "iyy_slugft2": g(PROPERTY_IYY),
            "fuel_lb": g(PROPERTY_FUEL),
            "stations_lb": {s.index: g(s.jsbsim_property) for s in self.plan.config.stations
                            if fdm.props.has(s.jsbsim_property)},
            "tanks_lb": {t.index: g(t.jsbsim_property) for t in self.plan.config.tanks},
        }

    def _cross_check(self, fdm, live: Dict[str, Any]) -> Dict[str, Any]:
        """The configured airframe against the loaded model: the empty
        weight, every station's arm and default weight (loadable ones),
        every tank's arm and capacity (through pct-full where the tank
        holds fuel). ``loading.config`` on any mismatch: a hand CG over
        arms that are not the model's would be a wrong number read
        back against itself."""
        config = self.plan.config
        checks: Dict[str, Any] = {}

        def refuse(what: str, configured: float, live_value: float) -> LoadingError:
            return LoadingError(
                "loading.config",
                f"{config.aircraft}: the configured {what} ({configured:g}) is not the loaded "
                f"model's ({live_value:g}); assets/aircraft_config/{config.aircraft}.json "
                f"must transcribe the XML")

        empty = fdm.props.get(PROPERTY_EMPTY)
        checks["empty_lb"] = {"configured": config.empty_lb, "live": empty}
        if abs(empty - config.empty_lb) > 1e-6:
            raise refuse("empty weight lb", config.empty_lb, empty)
        for station in config.stations:
            if not fdm.props.has(station.jsbsim_property):
                raise LoadingError("loading.config",
                                   f"{config.aircraft}: the loaded model has no "
                                   f"{station.jsbsim_property} for station {station.name!r}")
            arm = fdm.props.get(station.location_property)
            entry = {"arm_in": {"configured": station.arm_in, "live": arm}}
            if abs(arm - station.arm_in) > 1e-6:
                raise refuse(f"arm of station {station.name!r} in", station.arm_in, arm)
            if station.loadable:
                entry["default_lb"] = {"configured": station.default_lb,
                                       "live": live["stations_lb"][station.index]}
                if abs(live["stations_lb"][station.index] - station.default_lb) > 1e-6:
                    raise refuse(f"default weight of station {station.name!r} lb",
                                 station.default_lb, live["stations_lb"][station.index])
            checks[f"station:{station.name}"] = entry
        for tank in config.tanks:
            arm = fdm.props.get(tank.location_property)
            entry = {"arm_in": {"configured": tank.arm_in, "live": arm},
                     "default_lb": {"configured": tank.default_lb,
                                    "live": live["tanks_lb"][tank.index]}}
            if abs(arm - tank.arm_in) > 1e-6:
                raise refuse(f"arm of tank {tank.index} in", tank.arm_in, arm)
            if abs(live["tanks_lb"][tank.index] - tank.default_lb) > 1e-6:
                raise refuse(f"default contents of tank {tank.index} lb", tank.default_lb,
                             live["tanks_lb"][tank.index])
            pct = fdm.props.get(tank.pct_full_property)
            if pct > 0.0:
                capacity = 100.0 * live["tanks_lb"][tank.index] / pct
                entry["capacity_lb"] = {"configured": tank.capacity_lb,
                                        "live_from_pct_full": capacity}
                if abs(capacity - tank.capacity_lb) > 1e-6 * max(1.0, tank.capacity_lb):
                    raise refuse(f"capacity of tank {tank.index} lb", tank.capacity_lb, capacity)
            else:
                entry["capacity_lb"] = {"configured": tank.capacity_lb,
                                        "live_from_pct_full": None,
                                        "note": "an empty tank reports pct-full 0: the "
                                                "capacity cannot be read back from it"}
            checks[f"tank:{tank.index}"] = entry
        return checks

    def prepare(self, fdm) -> Dict[str, Any]:
        """Write the loading before the trim and measure what it did:
        the configured airframe checked against the loaded model, the
        CG / weight / inertia before any write, after each station's
        write and after the tanks' (each followed by a re-latch of the
        initial conditions, which is what recomputes FGMassBalance --
        measured: ``cg-x-in`` reads its old value until then), the exact
        read-back of every property written, and JSBSim's CG against
        the hand calculation within :data:`CG_TOLERANCE_IN`."""
        before = self._read(fdm)
        checks = self._cross_check(fdm, before)
        plan = self.plan
        station_loads = plan.station_loads()
        tank_loads = plan.tank_loads()
        steps: List[Dict[str, Any]] = []
        previous = before
        writes: Dict[str, float] = {}
        for load in station_loads:
            fdm.props.set(load.station.jsbsim_property, load.lb)
            writes[load.station.jsbsim_property] = load.lb
            fdm.relatch_initial_conditions()
            now = self._read(fdm)
            steps.append({"variable": "payload", "station": load.station.name,
                          "property": load.station.jsbsim_property, "written_lb": load.lb,
                          "kg": load.kg, "arm_in": load.station.arm_in,
                          "cg_before_in": previous["cg_x_in"], "cg_after_in": now["cg_x_in"],
                          "weight_before_lb": previous["weight_lb"],
                          "weight_after_lb": now["weight_lb"]})
            previous = now
        if tank_loads:
            for tl in tank_loads:
                fdm.props.set(tl.tank.jsbsim_property, tl.lb)
                writes[tl.tank.jsbsim_property] = tl.lb
            fdm.relatch_initial_conditions()
            now = self._read(fdm)
            steps.append({"variable": "fuel_kg" if plan.fuel_kg is not None else "fuel_fraction",
                          "tanks": [{"index": tl.tank.index, "property": tl.tank.jsbsim_property,
                                     "written_lb": tl.lb, "arm_in": tl.tank.arm_in}
                                    for tl in tank_loads],
                          "cg_before_in": previous["cg_x_in"], "cg_after_in": now["cg_x_in"],
                          "fuel_before_lb": previous["fuel_lb"], "fuel_after_lb": now["fuel_lb"],
                          "weight_before_lb": previous["weight_lb"],
                          "weight_after_lb": now["weight_lb"]})
            previous = now
        after = previous
        readback = {}
        for prop, written in writes.items():
            read = fdm.props.get(prop)
            readback[prop] = {"written": written, "read": read, "abs_error": abs(read - written),
                              "tolerance": 0.0, "agrees": read == written}
        expected = plan.hand_cg_in(live_station_lb=before["stations_lb"],
                                   live_tank_lb=before["tanks_lb"])
        cg_check = {"property": PROPERTY_CG, "read": after["cg_x_in"], "hand": expected,
                    "abs_error": abs(after["cg_x_in"] - expected),
                    "tolerance_in": CG_TOLERANCE_IN,
                    "agrees": abs(after["cg_x_in"] - expected) <= CG_TOLERANCE_IN}
        if not cg_check["agrees"]:
            raise LoadingError(
                "loading.config",
                f"{plan.config.aircraft}: JSBSim's {PROPERTY_CG} {after['cg_x_in']:.4f} in is "
                f"not the hand calculation {expected:.4f} in within {CG_TOLERANCE_IN} in; the "
                f"configured arms are not the model's")
        self.prepared = {
            "checks": checks, "before": before, "after": after, "steps": steps,
            "writes": writes, "readback": readback, "cg": cg_check,
            "hand": plan.to_dict()["hand"],
            "iyy_kgm2": after["iyy_slugft2"] * _SLUGFT2_TO_KGM2,
            "cg_x_m": u.ft_to_m(after["cg_x_in"] / 12.0),
            "gross_kg": u.lb_to_kg(after["weight_lb"]),
        }
        return self.prepared

    def observe(self, fdm) -> None:
        """Once, at the first step after the trim: the post-trim CG,
        weight, inertia, fuel and elevator, so the record can say the
        trim did not move the mass and what the trim solved."""
        if self.post_trim is not None:
            return
        state = self._read(fdm)
        state["elevator_rad"] = fdm.props.get("fcs/elevator-pos-rad")
        state["throttle"] = fdm.props.get("fcs/throttle-cmd-norm")
        state["sim_time_s"] = fdm.sim_time
        state["cg_moved_by_trim_in"] = (None if self.prepared is None
                                        else state["cg_x_in"] - self.prepared["after"]["cg_x_in"])
        self.post_trim = state

    # -- the records -------------------------------------------------------------------

    def applied_variables(self) -> List[AppliedVariable]:
        """One record per stated field: ``loading.payload_kg`` (the
        stations, read back through ``inertia/cg-x-in`` against the
        hand CG), ``loading.fuel_kg`` or ``loading.fuel_fraction`` (the
        tank contents read back exactly). Refuses a run never prepared."""
        if self.prepared is None:
            raise ValueError("LoadingProvider.prepare(fdm) was never called; there is no "
                             "read-back or null test to record")
        prepared = self.prepared
        plan = self.plan
        out: List[AppliedVariable] = []
        common_parameters = {
            "datum": str(plan.config.datum.get("xml")),
            "arm_comparison": dict(plan.config.datum.get("arm_comparison", {})),
            "hand": prepared["hand"],
            "cg_readback": prepared["cg"],
            "pre_trim_pair": {"cg_before_in": prepared["before"]["cg_x_in"],
                              "cg_after_in": prepared["after"]["cg_x_in"],
                              "weight_before_lb": prepared["before"]["weight_lb"],
                              "weight_after_lb": prepared["after"]["weight_lb"],
                              "iyy_before_slugft2": prepared["before"]["iyy_slugft2"],
                              "iyy_after_slugft2": prepared["after"]["iyy_slugft2"]},
            "iyy_kgm2": prepared["iyy_kgm2"], "cg_x_m": prepared["cg_x_m"],
            "gross_kg": prepared["gross_kg"],
            "post_trim": self.post_trim,
            "envelope": plan.envelope_check(),
            "config_path": plan.config.config_path,
            "config_sha256": plan.config.config_sha256,
            "applied": WHEN,
        }
        model_block = Model(
            name="hand W&B", standard="CG = sum(m x) / sum(m) over the empty weight, the stations "
                                     "and the tanks, in the XML's inches aft of the XML datum",
            version="JSBSim 1.2.4 FGMassBalance",
            parameters={"empty_lb": plan.config.empty_lb, "empty_arm_in": plan.config.empty_arm_in,
                        "station_arms_in": {s.name: s.arm_in for s in plan.config.stations},
                        "tank_arms_in": {t.index: t.arm_in for t in plan.config.tanks},
                        "datum": str(plan.config.datum.get("xml")),
                        "fuel_fill_rule": FUEL_FILL_RULE, "tolerance_in": CG_TOLERANCE_IN},
            references=REFERENCES)
        not_claimed = (
            "any handbook number: the arms, the maxima, the polygon and the maximum "
            "takeoff weight are from memory and marked unverified in the config",
            "the lateral and vertical CG: only cg-x-in is compared with the hand value",
            "the envelope on an airframe whose arm comparison is not green (recorded as "
            "not checked, by name); on the c172p the XML datum is TAKEN AS the handbook "
            "datum with a 3 in uncertainty",
            "the fuel burn during the engine crank before the trim (0.0055 lb on the "
            "c172p, measured): the tank read-back is taken before it",
            "the engine side: the card block carries the writes; no host applies them yet",
        )
        station_steps = [s for s in prepared["steps"] if s["variable"] == "payload"]
        if plan.payload is not None:
            first = station_steps[0] if station_steps else None
            cg_before = prepared["before"]["cg_x_in"]
            cg_after = station_steps[-1]["cg_after_in"] if station_steps else cg_before
            out.append(AppliedVariable(
                name="loading.payload_kg",
                value={load.station.name: load.kg for load in plan.station_loads()},
                unit="kg per station", source=plan.payload.source, model=MODEL,
                parameters={**common_parameters,
                            "stations": [{**s, "readback": prepared["readback"][s["property"]]}
                                         for s in station_steps]},
                references=REFERENCES + ((plan.payload.std,) if plan.payload.std else ()),
                properties_written=tuple(s["property"] for s in station_steps),
                telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                null_test=NullTest(
                    quantity="JSBSim inertia/cg-x-in before the trim, after the station writes "
                             "against before them",
                    unit="in", with_value=cg_after, without_value=cg_before,
                    threshold=CG_TOLERANCE_IN, kind="reached",
                    note=f"measured on the FDM at the initial conditions before the trim; the "
                         f"stations written in order {[s['station'] for s in station_steps]}, "
                         f"each followed by a re-latch; threshold = the V13 tolerance"),
                not_claimed=not_claimed, frm=plan.payload.frm, std=plan.payload.std,
                readback=Readback(
                    property=PROPERTY_CG, value=prepared["cg"]["read"], written=prepared["cg"]["hand"],
                    tolerance=CG_TOLERANCE_IN, tolerance_kind="absolute",
                    basis="V13: JSBSim's cg-x-in after the writes and a re-latch against the hand "
                          "CG over the XML's own arms (measured 1e-12 in on five airframes; the "
                          "tolerance is the blueprint's 0.1 in); 'written' is the hand value, "
                          "not a property write"),
                jsbsim_writes=tuple(JsbsimWrite(s["property"], WHEN) for s in station_steps),
                model_block=model_block,
            ))
        fuel = plan.fuel_kg if plan.fuel_kg is not None else plan.fuel_fraction
        if fuel is not None:
            step = next(s for s in prepared["steps"] if s["variable"] != "payload")
            tank_loads = plan.tank_loads() or []
            tank0 = tank_loads[0]
            out.append(AppliedVariable(
                name="loading.fuel_kg" if plan.fuel_kg is not None else "loading.fuel_fraction",
                value=fuel.value, unit="kg" if plan.fuel_kg is not None else "1",
                source=fuel.source, model=MODEL,
                parameters={**common_parameters,
                            "fuel_fill_rule": FUEL_FILL_RULE,
                            "total_fuel_lb": sum(tl.lb for tl in tank_loads),
                            "total_fuel_kg": u.lb_to_kg(sum(tl.lb for tl in tank_loads)),
                            "capacity_lb": sum(t.capacity_lb for t in plan.config.tanks),
                            "tanks": [{**t, "readback": prepared["readback"][t["property"]]}
                                      for t in step["tanks"]],
                            "cg_before_in": step["cg_before_in"], "cg_after_in": step["cg_after_in"]},
                references=REFERENCES + ((fuel.std,) if fuel.std else ()),
                properties_written=tuple(t["property"] for t in step["tanks"]),
                telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                null_test=NullTest(
                    quantity="JSBSim propulsion/total-fuel-lbs (as kg) before the trim, after the "
                             "tank writes against before them",
                    unit="kg", with_value=u.lb_to_kg(step["fuel_after_lb"]),
                    without_value=u.lb_to_kg(step["fuel_before_lb"]),
                    threshold=FUEL_NULL_FLOOR_KG, kind="reached",
                    note=f"measured on the FDM at the initial conditions before the trim; the "
                         f"CG moved {step['cg_after_in'] - step['cg_before_in']:+.4f} in "
                         f"(tanks at the XML's arms); threshold a stated {FUEL_NULL_FLOOR_KG} kg"),
                not_claimed=not_claimed, frm=fuel.frm, std=fuel.std,
                readback=Readback(
                    property=tank0.tank.jsbsim_property, value=prepared["readback"][tank0.tank.jsbsim_property]["read"],
                    written=tank0.lb, tolerance=0.0, tolerance_kind="absolute",
                    basis="measured here on the c172p and A320 (JSBSim 1.2.4): a tank's contents-lbs "
                          "reads back the value written to the last bit before the engine start; "
                          "the crank then burns 0.0055 lb on the c172p before the trim (recorded "
                          "under post_trim, not graded here)"),
                jsbsim_writes=tuple(JsbsimWrite(t["property"], WHEN) for t in step["tanks"]),
                model_block=model_block,
            ))
        return out

    # -- the card and the manifest ----------------------------------------------------

    def card_block(self) -> Dict[str, Any]:
        return self.plan.card_block()

    def manifest_block(self) -> Dict[str, Any]:
        """The run manifest's ``loading`` block: the plan, the checks,
        the pre-trim measurement and the post-trim read-back."""
        return {"applied": self.prepared is not None, "plan": self.plan.to_dict(),
                "config": self.plan.config.to_dict(), "prepared": self.prepared,
                "post_trim": self.post_trim, "envelope": self.plan.envelope_check(),
                "notes": [dict(n) for n in self.plan.notes]}

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({"model": MODEL, "plan": self.plan.to_dict(),
                    "config_sha256": self.plan.config.config_sha256,
                    "applied": WHEN})
        return out
