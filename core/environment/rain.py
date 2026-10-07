"""The rain provider: what falling rain does to the aircraft and to the runway.

W3 (core/scene/precipitation.py) gave the rain its LOOK from one stated
rate R (``environment.precipitation_rate_mmh``). This module gives the
same rate its PHYSICS, opt-in through the ``rain`` block (absent-
canonical: no block, nothing derived, nothing written, every digest as it
was). Three effects, each from the same drop-size distribution the look
uses, so the rain in the image and the rain in the trajectory are one
rain.

The water in the air
--------------------
The liquid water content and the mass-weighted fall speed are the fitted
Marshall-Palmer distribution's own moments (precipitation.fitted_lambda,
closure to the stated R within 1e-9):

    LWC = pi rho_w N0 / Lambda^4            (precipitation.liquid_water_g_m3)
    v_m = rho_w R / LWC                      (the mass flux R carries, exact)

so 50 mm/h is about 2.3 g/m^3 falling at about 6.1 m/s (measured here).

1. The momentum of the drops (exact under one stated assumption)
------------------------------------------------------------------
Every drop the aircraft sweeps up is brought to the aircraft's velocity
(perfectly inelastic: the momentum-penalty assumption of Haines & Luers
1983 [unverified here]; a splash that keeps some of its momentum makes
this an upper bound). In body axes, with u the drops' velocity RELATIVE
to the aircraft (the drops fall at v_m through the air mass, the aircraft
moves through it at (u, v, w)_aero):

    u_b = v_m d_b - (u, v, w)_aero,    d_b = (-sin th, sin ph cos th, cos ph cos th)
    m'  = LWC |u_b| (A_front |u_x| + A_plan |u_z|) / |u_b|
    F_b = m' u_b

A_plan is the wing area (``metrics/Sw-sqft``); A_front is the airframe's
frontal area (``rain.frontal_area_m2``, else the airframe config's ``rain``
block, else ``rain.airframe_data`` by name). The force goes into a JSBSim
``<external_reactions>`` force in the BODY frame at the aerodynamic
reference point (the ``rain`` injection, core/control/derive.py): its
direction and magnitude are written every step. It is both a drag (the
swept-up water accelerated to the airspeed: about LWC V^2 A_front plus
LWC V v_m A_plan) and a down-force (the falling water's own momentum).

2. The wetted wing (a stated mapping, like icing's severity words)
------------------------------------------------------------------
Wind-tunnel tests in simulated heavy rain (Bezos, Dunham, Gentry & Melson,
NASA TP-3184, 1992: a NACA 64-210 section at LWC 16 to 46 g/m^3) measured
a loss of maximum lift and a rise in drag that grow with the water
content, worst for high-lift configurations [the abstract is cited; the
tables are unverified here: not reachable from this container]. The
model is a STATED linear mapping in LWC, capped at the top of the tested
range rather than extrapolated beyond it:

    phi = min(LWC / LWC_REF, 1),  LWC_REF = 46 g/m^3
    rain/lift-factor = 1 - lift_loss_at_ref phi
    rain/drag-factor = 1 + drag_rise_at_ref phi

with lift_loss_at_ref 0.15 and drag_rise_at_ref 0.30 by default (stated
values inside the spans those studies report; both are spec fields). The
``rain`` injection wraps every function of the LIFT and DRAG axes in a
``<product>`` with the factor (the icing injection's form). At 50 mm/h
the factors are about 0.993 / 1.015; the effect is a heavy-rain effect.

3. The runway (14 CFR 25.109 and Horne)
---------------------------------------
JSBSim scales every contact's static (braking and cornering) friction by
``ground/static-friction-factor`` (measured here on the c172p: 0.5 turns
a full-brake stop from 50 kt of 313 ft into 498 ft). The provider writes
it every step from the runway condition and the ground speed V (kt):

* ``dry`` -- 1.0 (the airframe's own coefficients, JSBSim's default);
* ``wet`` -- the 14 CFR 25.109(c)(1) maximum tyre-to-ground wet-runway
  braking coefficient, a cubic in V/100 per tyre pressure (50, 100, 200,
  300 psi, linearly interpolated, clamped to that span; V clamped to
  0..200 kt) [coefficients from memory and a search snippet, the signs
  checked by monotonicity: unverified here], divided by the airframe's
  dry static coefficient and capped at 1: the wet runway never grips
  better than the dry one. No anti-skid efficiency is applied (the
  airframes here carry none);
* ``standing_water`` -- the wet value below the dynamic hydroplaning
  speed V_p = 9 sqrt(p) kt (Horne & Dreher, NASA TN D-2056, 1963, p the
  tyre pressure in psi [unverified here]) and a STATED 0.05 above it
  (braking in total hydroplaning is close to none; the number is this
  module's, not a standard's).

A stated rate with no runway word implies ``wet`` (rain is falling on
it); a runway word is accepted without a rate (a runway still wet after
the shower). The tyre pressure comes from ``rain.tire_pressure_psi``,
else the airframe config's ``rain`` block, else ``rain.airframe_data``.

Refusals by name (``RainError.constraint``, one list, :func:`problems`):
``rain.rate_missing`` (aerodynamics asked for with no rain rate),
``rain.runway_condition`` (an unknown word), ``rain.factor_range`` (a
penalty outside its stated bound), ``rain.airframe_data`` (no frontal
area or tyre pressure for this airframe, or a malformed config block).

NOT claimed: no airframe's rain response is validated; the roughness
factors scale WHOLE axes (the studies measure a loss of MAXIMUM lift and
little change at low alpha, so the scale overstates the cruise effect and
understates the stall); the drops' splash, the water film's mass, the
engine's water ingestion, a wet windscreen, standing water's displacement
drag and spray, and the rolling resistance of a wet runway are not
modelled; the box projection ignores the side area (sideslip); the rain
rate is uniform in space and time; Atlas's fall-speed law is for sea-
level air; the engine side (the manifest carries the numbers, no host
applies them yet).
"""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from ..scenario.blocks import (
    RAIN_DRAG_RISE_RANGE, RAIN_LIFT_LOSS_RANGE, RAIN_RUNWAY_WORDS,
)
from ..scene import precipitation as precip
from .base import AtmosphereProvider, Position, Term

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

RHO_WATER = 1000.0                      # kg/m^3
LBF_TO_N = 4.4482216152605
FT_TO_M = 0.3048
SQFT_TO_M2 = FT_TO_M * FT_TO_M
KT_PER_FPS = 0.592483801

#: The wetted-wing mapping (module docstring, effect 2).
LWC_REF_G_M3 = 46.0
RUNWAY_WORDS = RAIN_RUNWAY_WORDS
LIFT_LOSS_RANGE = RAIN_LIFT_LOSS_RANGE
DRAG_RISE_RANGE = RAIN_DRAG_RISE_RANGE

#: 14 CFR 25.109(c)(1): mu = a3 x^3 + a2 x^2 + a1 x + a0, x = V / 100 (kt).
WET_MU_TABLE: Tuple[Tuple[float, Tuple[float, float, float, float]], ...] = (
    (50.0, (-0.0350, 0.306, -0.851, 0.883)),
    (100.0, (-0.0437, 0.320, -0.805, 0.804)),
    (200.0, (-0.0331, 0.252, -0.658, 0.692)),
    (300.0, (-0.0401, 0.263, -0.611, 0.614)),
)
WET_MU_SPEED_MAX_KT = 200.0
#: Horne & Dreher 1963: V_p = 9 sqrt(p) kt, p in psi.
HORNE_K = 9.0
#: The stated braking coefficient above V_p on standing water.
HYDROPLANING_MU = 0.05

#: The properties the rain injection declares (core/control/derive.py).
FORCE_NAME = "rain-momentum"
PROPERTY_LIFT = "rain/lift-factor"
PROPERTY_DRAG = "rain/drag-factor"
PROPERTY_LWC = "rain/lwc-gm3"
PROPERTY_MAGNITUDE = f"external_reactions/{FORCE_NAME}/magnitude"
PROPERTY_DIRECTION = tuple(f"external_reactions/{FORCE_NAME}/{axis}" for axis in "xyz")
PROPERTY_FRICTION = "ground/static-friction-factor"
AERO_PROPERTIES = (PROPERTY_LWC, PROPERTY_LIFT, PROPERTY_DRAG, PROPERTY_MAGNITUDE,
                   *PROPERTY_DIRECTION)
INJECTIONS = ("rain",)

#: The recorder columns (only where the stack holds a rain provider, so a
#: run without the block keeps its columns and its digest).
TELEMETRY_COLUMNS = ("rain_lwc_gm3", "rain_lift_factor", "rain_drag_factor",
                     "rain_momentum_drag_n", "rain_momentum_down_n",
                     "ground_friction_factor", "hydroplaning")
CARD_KEYS = ("rate_mmh", "lwc_g_m3", "fall_speed_mps", "aerodynamics", "lift_factor",
             "drag_factor", "frontal_area_m2", "runway_condition", "tire_pressure_psi",
             "hydroplaning_speed_kt")

MODEL = ("rain momentum (inelastic drop capture, box projection) through an external force, "
         "a stated linear wetted-wing mapping in LWC through the rain injection, and the "
         "14 CFR 25.109 wet-runway braking coefficient with Horne's hydroplaning speed "
         "through ground/static-friction-factor")
REFERENCES = (
    "Marshall & Palmer 1948 and Atlas, Srivastava & Sekhon 1973 through "
    "core/scene/precipitation.py (the fitted drop-size distribution: LWC and fall speed)",
    "Haines & Luers, 'Aerodynamic penalties of heavy rain on landing airplanes', J. Aircraft "
    "20(2), 1983 (the momentum penalty) [unverified here]",
    "Bezos, Dunham, Gentry & Melson, NASA TP-3184, 1992, 'Wind tunnel aerodynamic "
    "characteristics of a transport-type airfoil in a simulated heavy rain environment' "
    "(LWC 16-46 g/m^3; maximum-lift loss and drag rise grow with LWC) [abstract cited; "
    "tables unverified here]",
    "14 CFR 25.109(c)(1): the maximum tyre-to-ground wet-runway braking coefficient "
    "[coefficients from memory and a search snippet; unverified here]",
    "Horne & Dreher, NASA TN D-2056, 1963, 'Phenomena of pneumatic tire hydroplaning' "
    "(V_p = 9 sqrt(p) kt) [unverified here]",
)
NOT_CLAIMED = (
    "no airframe's rain response is validated",
    "the wetted-wing factors scale WHOLE LIFT and DRAG axes; the studies measure a loss of "
    "maximum lift with little change at low alpha, so the cruise effect is overstated and "
    "the stall understated; the default penalties are stated, not transcribed",
    "the drops' capture is perfectly inelastic (an upper bound: a splash keeps some of its "
    "momentum); the side area is ignored; the water film's mass, engine water ingestion, "
    "a wet windscreen and spray are not modelled",
    "the runway: rolling resistance, standing water's displacement drag and anti-skid "
    "efficiency are not modelled; the hydroplaning coefficient 0.05 is this module's",
    "the rain rate is uniform in space and time; Atlas's fall-speed law is for sea-level air",
    "the engine side: the manifest's rain block carries the numbers (card_block); no "
    "host applies them yet",
)


class RainError(ValueError):
    """A rain refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


# -- the water in the air -------------------------------------------------------------

def water(rate_mmh: float) -> Dict[str, float]:
    """The fitted distribution's liquid water content (g/m^3) and mass-
    weighted fall speed (m/s) at a rain rate: ``v_m = rho_w R / LWC``."""
    lam = precip.fitted_lambda(rate_mmh)
    lwc = precip.liquid_water_g_m3(lam)
    rate_mps = float(rate_mmh) / 3.6e6
    fall = RHO_WATER * rate_mps / (lwc * 1e-3)
    return {"lambda_per_mm": lam, "lwc_g_m3": lwc, "fall_speed_mps": fall}


def roughness_factors(lwc_g_m3: float, lift_loss_at_ref: float,
                      drag_rise_at_ref: float) -> Dict[str, float]:
    """The stated wetted-wing mapping: ``phi = min(LWC / 46, 1)``, lift
    ``1 - loss phi``, drag ``1 + rise phi``."""
    phi = min(max(float(lwc_g_m3), 0.0) / LWC_REF_G_M3, 1.0)
    return {"phi": phi, "lift": 1.0 - float(lift_loss_at_ref) * phi,
            "drag": 1.0 + float(drag_rise_at_ref) * phi}


def body_down(phi_rad: float, theta_rad: float) -> Tuple[float, float, float]:
    """The local vertical (down) in body axes."""
    return (-math.sin(theta_rad), math.sin(phi_rad) * math.cos(theta_rad),
            math.cos(phi_rad) * math.cos(theta_rad))


def momentum_force_body(lwc_g_m3: float, fall_speed_mps: float,
                        uvw_aero_mps: Tuple[float, float, float], phi_rad: float,
                        theta_rad: float, frontal_area_m2: float,
                        plan_area_m2: float) -> Tuple[float, float, float]:
    """The swept-up drops' force on the aircraft, body axes, N (effect 1)."""
    down = body_down(phi_rad, theta_rad)
    rel = tuple(fall_speed_mps * d - v for d, v in zip(down, uvw_aero_mps))
    speed = math.sqrt(sum(c * c for c in rel))
    if speed == 0.0 or lwc_g_m3 <= 0.0:
        return (0.0, 0.0, 0.0)
    area = frontal_area_m2 * abs(rel[0]) / speed + plan_area_m2 * abs(rel[2]) / speed
    mass_rate = lwc_g_m3 * 1e-3 * speed * area
    return tuple(mass_rate * c for c in rel)


# -- the runway -----------------------------------------------------------------------

def _cubic(coeffs: Tuple[float, float, float, float], x: float) -> float:
    a3, a2, a1, a0 = coeffs
    return ((a3 * x + a2) * x + a1) * x + a0


def wet_mu(groundspeed_kt: float, tire_pressure_psi: float) -> float:
    """14 CFR 25.109(c)(1)'s maximum wet-runway braking coefficient,
    linearly interpolated in tyre pressure (clamped to 50..300 psi) at a
    ground speed clamped to 0..200 kt."""
    x = min(max(float(groundspeed_kt), 0.0), WET_MU_SPEED_MAX_KT) / 100.0
    p = min(max(float(tire_pressure_psi), WET_MU_TABLE[0][0]), WET_MU_TABLE[-1][0])
    for (p_lo, c_lo), (p_hi, c_hi) in zip(WET_MU_TABLE, WET_MU_TABLE[1:]):
        if p <= p_hi:
            w = (p - p_lo) / (p_hi - p_lo)
            return (1.0 - w) * _cubic(c_lo, x) + w * _cubic(c_hi, x)
    return _cubic(WET_MU_TABLE[-1][1], x)


def hydroplaning_speed_kt(tire_pressure_psi: float) -> float:
    """Horne & Dreher 1963: V_p = 9 sqrt(p) kt."""
    return HORNE_K * math.sqrt(float(tire_pressure_psi))


def runway_mu(condition: str, groundspeed_kt: float,
              tire_pressure_psi: Optional[float]) -> Optional[float]:
    """The braking coefficient a runway condition allows at a ground
    speed, or None for ``dry`` (the airframe's own coefficients)."""
    if condition == "dry":
        return None
    if condition == "standing_water" and groundspeed_kt > hydroplaning_speed_kt(tire_pressure_psi):
        return HYDROPLANING_MU
    return wet_mu(groundspeed_kt, tire_pressure_psi)


def friction_factor(condition: str, groundspeed_kt: float, tire_pressure_psi: Optional[float],
                    dry_static_mu: float) -> float:
    """``ground/static-friction-factor``: the runway's coefficient over the
    airframe's dry one, capped at 1 (1.0 on a dry runway)."""
    mu = runway_mu(condition, groundspeed_kt, tire_pressure_psi)
    if mu is None:
        return 1.0
    return min(1.0, max(0.0, mu) / float(dry_static_mu))


def dry_static_mu(xml_path: Path) -> float:
    """The largest ``static_friction`` of the airframe's BOGEY contacts
    (the wheels; a STRUCTURE contact's coefficient is a skid's)."""
    root = ET.parse(str(xml_path)).getroot()
    values = []
    for contact in root.iter("contact"):
        if contact.get("type", "").upper() != "BOGEY":
            continue
        node = contact.find("static_friction")
        if node is not None and node.text is not None:
            values.append(float(node.text))
    if not values:
        raise RainError("rain.airframe_data",
                        f"{xml_path.name} declares no BOGEY contact with a static_friction: "
                        f"there is no dry braking coefficient to scale")
    return max(values)


# -- the airframe data ----------------------------------------------------------------

@dataclass(frozen=True)
class AirframeRain:
    """An airframe config's ``rain`` block: each value with its source."""

    aircraft: str
    frontal_area_m2: Optional[float]
    frontal_area_source: Optional[str]
    tire_pressure_psi: Optional[float]
    tire_pressure_source: Optional[str]
    config_path: str
    config_sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {"aircraft": self.aircraft,
                "frontal_area_m2": {"value": self.frontal_area_m2,
                                    "source": self.frontal_area_source},
                "tire_pressure_psi": {"value": self.tire_pressure_psi,
                                      "source": self.tire_pressure_source},
                "config_path": self.config_path, "config_sha256": self.config_sha256}


def load_airframe_rain(aircraft: str, config_dir: Optional[Path] = None) -> Optional[AirframeRain]:
    """The airframe config's ``rain`` block, or None when there is none;
    a malformed block refuses ``rain.airframe_data`` by name."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    path = directory / f"{aircraft}.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    block = json.loads(raw.decode("utf-8")).get("rain")
    if block is None:
        return None

    def refuse(message: str) -> RainError:
        return RainError("rain.airframe_data",
                         f"{aircraft}: the rain block of assets/aircraft_config/{aircraft}.json "
                         f"is not usable: {message}")

    if not isinstance(block, Mapping):
        raise refuse("it is not a mapping")
    unknown = set(block) - {"frontal_area_m2", "tire_pressure_psi"}
    if unknown:
        raise refuse(f"unknown keys {sorted(unknown)}")
    values: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
    for key in ("frontal_area_m2", "tire_pressure_psi"):
        entry = block.get(key)
        if entry is None:
            values[key] = (None, None)
            continue
        if not isinstance(entry, Mapping) or set(entry) != {"value", "source"}:
            raise refuse(f"{key} must be {{value, source}}")
        if not _number(entry["value"]) or float(entry["value"]) <= 0.0:
            raise refuse(f"{key} value is not a positive number")
        if not isinstance(entry["source"], str) or not entry["source"].strip():
            raise refuse(f"{key} has no source")
        values[key] = (float(entry["value"]), entry["source"])
    try:
        rel = path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        rel = path.as_posix()
    return AirframeRain(aircraft=aircraft,
                        frontal_area_m2=values["frontal_area_m2"][0],
                        frontal_area_source=values["frontal_area_m2"][1],
                        tire_pressure_psi=values["tire_pressure_psi"][0],
                        tire_pressure_source=values["tire_pressure_psi"][1],
                        config_path=rel, config_sha256=hashlib.sha256(raw).hexdigest())


# -- the refusals, one list -----------------------------------------------------------

@dataclass(frozen=True)
class Stated:
    """One field's value with its provenance."""

    value: Any
    source: str = "user"
    frm: Optional[str] = None
    std: Optional[str] = None


def resolve(rate_mmh: Any, aerodynamics: Any, lift_loss_at_ref: Any, drag_rise_at_ref: Any,
            frontal_area_m2: Any, runway_condition: Any, tire_pressure_psi: Any,
            aircraft: Optional[str], config_dir: Optional[Path] = None
            ) -> Tuple[Dict[str, Stated], List[RainError]]:
    """The effective values of a stated block (each a :class:`Stated`
    whose source says where it came from) and every way it cannot be
    delivered, by name: the one list the validator renders and the
    provider refuses. Inputs are the block's raw values (None =
    unstated)."""
    out: List[RainError] = []
    eff: Dict[str, Stated] = {}
    aero = True if aerodynamics is None else aerodynamics
    if not isinstance(aero, bool):
        out.append(RainError("rain.factor_range",
                             f"rain.aerodynamics must be true or false, not {aerodynamics!r}",
                             actual=aerodynamics))
        aero = False
    eff["aerodynamics"] = Stated(aero, "user" if aerodynamics is not None else "default")
    if aero and rate_mmh is None:
        out.append(RainError(
            "rain.rate_missing",
            "the rain block asks for the rain's aerodynamics but environment."
            "precipitation_rate_mmh states no rain rate; state the rate, or set "
            "rain.aerodynamics false for a wet runway after the rain"))
    for name, value, (lo, hi), default in (
            ("lift_loss_at_ref", lift_loss_at_ref, LIFT_LOSS_RANGE, 0.15),
            ("drag_rise_at_ref", drag_rise_at_ref, DRAG_RISE_RANGE, 0.30)):
        if value is None:
            eff[name] = Stated(default, "default")
        elif not _number(value) or not lo <= float(value) <= hi:
            out.append(RainError("rain.factor_range",
                                 f"rain.{name} must be a number in {lo:g}..{hi:g} (a stated "
                                 f"bound), not {value!r}", actual=value, limit=hi, unit="1"))
        else:
            eff[name] = Stated(float(value))
    if runway_condition is None:
        word = "wet" if rate_mmh is not None else "dry"
        eff["runway_condition"] = Stated(
            word, "derived", frm=("rain is falling on the runway (a rate is stated)"
                                  if rate_mmh is not None else "no rain rate: a dry runway"))
    elif not isinstance(runway_condition, str) or runway_condition not in RUNWAY_WORDS:
        out.append(RainError("rain.runway_condition",
                             f"rain.runway_condition must be one of {list(RUNWAY_WORDS)}, not "
                             f"{runway_condition!r}", actual=runway_condition))
    else:
        eff["runway_condition"] = Stated(runway_condition)
    config = None
    if aircraft is not None:
        try:
            config = load_airframe_rain(aircraft, config_dir)
        except RainError as exc:
            out.append(exc)
    for name, value, needed in (
            ("frontal_area_m2", frontal_area_m2, aero),
            ("tire_pressure_psi", tire_pressure_psi,
             eff.get("runway_condition", Stated("dry")).value != "dry")):
        if value is not None:
            if not _number(value) or float(value) <= 0.0:
                out.append(RainError("rain.airframe_data",
                                     f"rain.{name} must be a positive number, not {value!r}",
                                     actual=value))
            else:
                eff[name] = Stated(float(value))
            continue
        from_config = None if config is None else getattr(config, name)
        if from_config is not None:
            eff[name] = Stated(from_config, "model",
                               frm=f"assets/aircraft_config/{aircraft}.json rain.{name}",
                               std=getattr(config, name.replace("_m2", "").replace("_psi", "")
                                           + "_source"))
        elif needed and aircraft is not None:
            out.append(RainError(
                "rain.airframe_data",
                f"{aircraft}: no {name} is stated (rain.{name}) or configured (the rain block "
                f"of assets/aircraft_config/{aircraft}.json), and the "
                f"{'momentum of the drops' if name == 'frontal_area_m2' else 'wet runway'} "
                f"needs it"))
    if rate_mmh is not None:
        problem = precip.rate_problem(rate_mmh)
        if problem is not None:
            out.append(RainError("rain.rate_missing", problem, actual=rate_mmh))
    return eff, out


def problems(spec, config_dir: Optional[Path] = None) -> List[RainError]:
    """Every refusal a spec's stated ``rain`` block raises (none for the
    default block)."""
    block = getattr(spec, "rain", None)
    if block is None or block.is_default():
        return []
    return resolve(*_raw(spec), aircraft=str(spec.aircraft.value), config_dir=config_dir)[1]


def _raw(spec) -> Tuple[Any, ...]:
    block = spec.rain
    rate = spec.precipitation_rate_mmh.value
    return (rate, block.aerodynamics.value, block.lift_loss_at_ref.value,
            block.drag_rise_at_ref.value, block.frontal_area_m2.value,
            block.runway_condition.value, block.tire_pressure_psi.value)


def rain_injections_for(spec) -> Tuple[str, ...]:
    """``("rain",)`` when a stated block asks for the aerodynamics, nothing
    otherwise (a runway-only block writes JSBSim's own ground property and
    flies the stock airframe, hashes unchanged)."""
    block = getattr(spec, "rain", None)
    if block is None or block.is_default():
        return ()
    aero = block.aerodynamics.value
    return INJECTIONS if aero is None or aero is True else ()


# -- the provider ---------------------------------------------------------------------

class RainProvider(AtmosphereProvider):
    """The rain's three effects, written every step and read back before
    the next write (see the module docstring)."""

    name = "rain"

    def __init__(self, aircraft: str, rate_mmh: Optional[float], effective: Mapping[str, Stated],
                 rate_source: Optional[Stated] = None, rate_hz: float = 120.0) -> None:
        self.aircraft = aircraft
        self.effective = dict(effective)
        self.rate_mmh = None if rate_mmh is None else float(rate_mmh)
        self.rate_source = rate_source
        self.rate_hz = float(rate_hz)
        self.aerodynamics = bool(self.effective["aerodynamics"].value)
        self.runway_condition = str(self.effective["runway_condition"].value)
        self.lift_loss_at_ref = float(self.effective["lift_loss_at_ref"].value)
        self.drag_rise_at_ref = float(self.effective["drag_rise_at_ref"].value)
        frontal = self.effective.get("frontal_area_m2")
        self.frontal_area_m2 = None if frontal is None else float(frontal.value)
        tire = self.effective.get("tire_pressure_psi")
        self.tire_pressure_psi = None if tire is None else float(tire.value)
        if self.rate_mmh is not None:
            self.water = water(self.rate_mmh)
        else:
            self.water = {"lambda_per_mm": None, "lwc_g_m3": 0.0, "fall_speed_mps": 0.0}
        self.factors = (roughness_factors(self.water["lwc_g_m3"], self.lift_loss_at_ref,
                                          self.drag_rise_at_ref)
                        if self.aerodynamics else {"phi": 0.0, "lift": 1.0, "drag": 1.0})
        self.hydroplaning_speed_kt = (None if self.tire_pressure_psi is None
                                      else hydroplaning_speed_kt(self.tire_pressure_psi))
        #: Read once in prepare: wing area, the dry static coefficient.
        self.plan_area_m2: Optional[float] = None
        self.dry_static_mu: Optional[float] = None
        #: The state the last observe read (the writes are computed from it).
        self._state: Optional[Dict[str, float]] = None
        self._last_written: Dict[str, float] = {}
        self.steps_written = 0
        self.last: Dict[str, float] = {column: 0.0 for column in TELEMETRY_COLUMNS}
        self.peaks: Dict[str, float] = {"momentum_drag_n": 0.0, "momentum_down_n": 0.0,
                                        "min_friction_factor": 1.0, "steps_hydroplaning": 0}
        self.readback: Dict[str, Any] = {"steps_checked": 0, "max_abs_error": {},
                                         "last_written": {}, "last_read": {}}
        self.prepared: Optional[Dict[str, Any]] = None

    @classmethod
    def from_spec(cls, spec, config_dir: Optional[Path] = None) -> Optional["RainProvider"]:
        """The provider a spec asks for, or None for the default block.
        Refuses by name what the validator refuses."""
        block = getattr(spec, "rain", None)
        if block is None or block.is_default():
            return None
        aircraft = str(spec.aircraft.value)
        effective, found = resolve(*_raw(spec), aircraft=aircraft, config_dir=config_dir)
        if found:
            raise found[0]
        for name in ("aerodynamics", "lift_loss_at_ref", "drag_rise_at_ref",
                     "frontal_area_m2", "runway_condition", "tire_pressure_psi"):
            q = getattr(block, name)
            if name in effective and str(q.source) != "default" and q.value is not None:
                effective[name] = Stated(effective[name].value, str(q.source), q.frm, q.std)
        rate_q = spec.precipitation_rate_mmh
        rate_stated = (None if rate_q.value is None else
                       Stated(rate_q.value, str(rate_q.source), rate_q.frm, rate_q.std))
        return cls(aircraft, rate_q.value, effective, rate_source=rate_stated,
                   rate_hz=float(spec.rate.value))

    # -- the per-step computation --------------------------------------------------

    def writes_for(self, state: Mapping[str, float]) -> Dict[str, float]:
        """Every property one step writes, from the state it starts in."""
        writes: Dict[str, float] = {}
        if self.aerodynamics:
            force = momentum_force_body(
                self.water["lwc_g_m3"], self.water["fall_speed_mps"],
                (state["u_mps"], state["v_mps"], state["w_mps"]), state["phi_rad"],
                state["theta_rad"], self.frontal_area_m2, self.plan_area_m2)
            magnitude = math.sqrt(sum(c * c for c in force))
            direction = ((1.0, 0.0, 0.0) if magnitude == 0.0
                         else tuple(c / magnitude for c in force))
            writes[PROPERTY_LWC] = self.water["lwc_g_m3"]
            writes[PROPERTY_LIFT] = self.factors["lift"]
            writes[PROPERTY_DRAG] = self.factors["drag"]
            writes[PROPERTY_MAGNITUDE] = magnitude / LBF_TO_N
            for prop, component in zip(PROPERTY_DIRECTION, direction):
                writes[prop] = component
        writes[PROPERTY_FRICTION] = friction_factor(
            self.runway_condition, state["groundspeed_kt"], self.tire_pressure_psi,
            self.dry_static_mu)
        return writes

    def _bookkeep(self, state: Mapping[str, float], writes: Mapping[str, float]) -> None:
        force_n = writes.get(PROPERTY_MAGNITUDE, 0.0) * LBF_TO_N
        direction = [writes.get(p, 0.0) for p in PROPERTY_DIRECTION]
        # The drag is the force against the airspeed vector, the down-force
        # the component along the local vertical.
        u, v, w = state["u_mps"], state["v_mps"], state["w_mps"]
        airspeed = math.sqrt(u * u + v * v + w * w)
        force = [force_n * d for d in direction]
        drag = (0.0 if airspeed == 0.0 else
                -(force[0] * u + force[1] * v + force[2] * w) / airspeed)
        down = sum(f * d for f, d in zip(force, body_down(state["phi_rad"], state["theta_rad"])))
        hydro = (self.runway_condition == "standing_water" and state["on_ground"]
                 and state["groundspeed_kt"] > self.hydroplaning_speed_kt)
        friction = writes[PROPERTY_FRICTION]
        self.last = {"rain_lwc_gm3": self.water["lwc_g_m3"] if self.aerodynamics else 0.0,
                     "rain_lift_factor": writes.get(PROPERTY_LIFT, 1.0),
                     "rain_drag_factor": writes.get(PROPERTY_DRAG, 1.0),
                     "rain_momentum_drag_n": drag, "rain_momentum_down_n": down,
                     "ground_friction_factor": friction, "hydroplaning": 1.0 if hydro else 0.0}
        self.peaks["momentum_drag_n"] = max(self.peaks["momentum_drag_n"], drag)
        self.peaks["momentum_down_n"] = max(self.peaks["momentum_down_n"], down)
        if state["on_ground"]:
            self.peaks["min_friction_factor"] = min(self.peaks["min_friction_factor"], friction)
        if hydro:
            self.peaks["steps_hydroplaning"] += 1

    @staticmethod
    def read_state(fdm) -> Dict[str, float]:
        g = fdm.props.get
        return {"u_mps": g("velocities/u-aero-fps") * FT_TO_M,
                "v_mps": g("velocities/v-aero-fps") * FT_TO_M,
                "w_mps": g("velocities/w-aero-fps") * FT_TO_M,
                "phi_rad": g("attitude/phi-rad"), "theta_rad": g("attitude/theta-rad"),
                "groundspeed_kt": g("velocities/vg-fps") * KT_PER_FPS,
                "on_ground": bool(g("gear/wow"))}

    # -- the hooks ---------------------------------------------------------------

    def properties(self, position: Position, time_s: float) -> Dict[str, float]:
        """The per-step writes, from the state :meth:`observe` read at the
        top of this step."""
        if self._state is None:
            raise ValueError("RainProvider.properties before observe(fdm): the stack calls "
                             "observe at the top of every apply")
        writes = self.writes_for(self._state)
        self._bookkeep(self._state, writes)
        self._last_written = dict(writes)
        self.steps_written += 1
        return writes

    def observe(self, fdm) -> None:
        """Read back the previous step's writes, BEFORE this step's, and
        read the state this step's writes are computed from."""
        if self._last_written:
            errors = self.readback["max_abs_error"]
            read_now: Dict[str, float] = {}
            for prop, written in self._last_written.items():
                read = fdm.props.get(prop)
                read_now[prop] = read
                errors[prop] = max(errors.get(prop, 0.0), abs(read - written))
            self.readback["last_written"] = dict(self._last_written)
            self.readback["last_read"] = read_now
            self.readback["steps_checked"] += 1
        self._state = self.read_state(fdm)

    def neutral_writes(self) -> Dict[str, float]:
        writes = {PROPERTY_FRICTION: 1.0}
        if self.aerodynamics:
            writes.update({PROPERTY_LWC: 0.0, PROPERTY_LIFT: 1.0, PROPERTY_DRAG: 1.0,
                           PROPERTY_MAGNITUDE: 0.0, PROPERTY_DIRECTION[0]: 1.0,
                           PROPERTY_DIRECTION[1]: 0.0, PROPERTY_DIRECTION[2]: 0.0})
        return writes

    def _measure(self, fdm) -> Dict[str, float]:
        g = fdm.props.get
        # JSBSim's wind-axis forces are the magnitudes: lift and drag positive.
        return {"lift_n": g("forces/fwz-aero-lbs") * LBF_TO_N,
                "drag_n": g("forces/fwx-aero-lbs") * LBF_TO_N,
                "alpha_deg": g("aero/alpha-deg")}

    def prepare(self, fdm) -> Dict[str, Any]:
        """Before the trim: check the airframe declares what the block
        writes, read the wing area and the dry coefficient, measure the
        pre-trim with/without pair of the wetted-wing factors (lift and drag
        at the initial conditions, each after a re-latch) and the drops'
        force there, and leave every property neutral -- the trim is of
        the dry aircraft (a stated choice, icing's)."""
        wanted = list(self.neutral_writes())
        missing = [p for p in wanted if not fdm.props.has(p)]
        if missing:
            raise ValueError(f"the loaded airframe declares no {missing}: a rain block with "
                             f"aerodynamics flies the airframe derived with {INJECTIONS} "
                             f"(core/scenario/runner.py); this one was not")
        self.plan_area_m2 = fdm.props.get("metrics/Sw-sqft") * SQFT_TO_M2
        self.dry_static_mu = dry_static_mu(fdm.model.xml_path)
        neutral = self.neutral_writes()
        fdm.props.set_many(neutral)
        fdm.relatch_initial_conditions()
        baseline = self._measure(fdm)
        with_factors = baseline
        state = self.read_state(fdm)
        force = (0.0, 0.0, 0.0)
        if self.aerodynamics:
            fdm.props.set_many({PROPERTY_LIFT: self.factors["lift"],
                                PROPERTY_DRAG: self.factors["drag"]})
            fdm.relatch_initial_conditions()
            with_factors = self._measure(fdm)
            fdm.props.set_many(neutral)
            fdm.relatch_initial_conditions()
            force = momentum_force_body(
                self.water["lwc_g_m3"], self.water["fall_speed_mps"],
                (state["u_mps"], state["v_mps"], state["w_mps"]), state["phi_rad"],
                state["theta_rad"], self.frontal_area_m2, self.plan_area_m2)
        readback = {prop: {"written": written, "read": fdm.props.get(prop),
                           "agrees": fdm.props.get(prop) == written}
                    for prop, written in neutral.items()}
        derived = getattr(fdm, "derived", None)
        self.prepared = {
            "altitude_m": fdm.state().altitude_m, "tas_mps": math.sqrt(
                state["u_mps"] ** 2 + state["v_mps"] ** 2 + state["w_mps"] ** 2),
            "plan_area_m2": self.plan_area_m2, "dry_static_mu": self.dry_static_mu,
            "baseline": baseline, "with_factors": with_factors,
            "momentum_force_body_n": list(force),
            "neutral_writes": neutral, "readback": readback,
            "derived_aircraft": None if derived is None else derived.name,
            "derived_sha256": None if derived is None else derived.derived_sha256,
            "injections": [] if derived is None else list(derived.injection_names),
        }
        return self.prepared

    # -- the records -------------------------------------------------------------

    def _readback_of(self, prop: str) -> Readback:
        checked = self.readback["last_written"]
        if prop in checked:
            return Readback(property=prop, value=self.readback["last_read"][prop],
                            written=checked[prop], tolerance=0.0, tolerance_kind="absolute",
                            basis=READBACK_BASIS)
        pre = (self.prepared or {}).get("readback", {}).get(prop)
        if pre is None:
            raise ValueError(f"{prop} was never written by this provider")
        return Readback(property=prop, value=pre["read"], written=pre["written"], tolerance=0.0,
                        tolerance_kind="absolute",
                        basis=READBACK_BASIS + " (the pre-trim neutral write: no step was checked)")

    def _model_block(self) -> Model:
        return Model(
            name="rain momentum, wetted wing and wet runway",
            standard=("F_b = LWC |u| (A_front |u_x| + A_plan |u_z|) u, u = v_m d_b - (u,v,w)_aero; "
                      "lift 1 - loss min(LWC/46, 1), drag 1 + rise min(LWC/46, 1); friction "
                      "min(1, mu_25.109(V, p) / mu_dry), 0.05 above 9 sqrt(p) kt on standing water"),
            version="JSBSim 1.2.4; the rain injection (core/control/systems/rain.xml)",
            parameters=self._common_parameters(),
            references=REFERENCES)

    def _common_parameters(self) -> Dict[str, Any]:
        return {"rate_mmh": self.rate_mmh, "water": dict(self.water),
                "aerodynamics": self.aerodynamics, "factors": dict(self.factors),
                "lift_loss_at_ref": self.lift_loss_at_ref,
                "drag_rise_at_ref": self.drag_rise_at_ref, "lwc_ref_g_m3": LWC_REF_G_M3,
                "frontal_area_m2": self.frontal_area_m2, "plan_area_m2": self.plan_area_m2,
                "runway_condition": self.runway_condition,
                "tire_pressure_psi": self.tire_pressure_psi,
                "hydroplaning_speed_kt": self.hydroplaning_speed_kt,
                "hydroplaning_mu": HYDROPLANING_MU, "dry_static_mu": self.dry_static_mu,
                "trim": "of the dry aircraft (neutral values before the trim)"}

    def applied_variables(self) -> List[AppliedVariable]:
        """One record per effect delivered: the rate's aerodynamics (with
        the pre-trim lift and drag null pair), and the runway condition
        (with the friction factor at a reference ground speed against the
        dry 1.0). Refuses a run never prepared."""
        if self.prepared is None:
            raise ValueError("RainProvider.prepare(fdm) was never called; there is no read-back "
                             "or null test to record")
        prepared = self.prepared
        model = self._model_block()
        out: List[AppliedVariable] = []
        if self.aerodynamics:
            props = AERO_PROPERTIES
            rate = self.rate_source or Stated(self.rate_mmh)
            out.append(AppliedVariable(
                name="rain.aerodynamics", value=self.rate_mmh, unit="mm/h", source=rate.source,
                model_name=MODEL, parameters={**self._common_parameters(),
                                              "pre_trim": {k: prepared[k] for k in (
                                                  "baseline", "with_factors",
                                                  "momentum_force_body_n", "tas_mps",
                                                  "altitude_m")},
                                              "per_step": self._readback_report(),
                                              "peaks": dict(self.peaks)},
                references=REFERENCES + ((rate.std,) if rate.std else ()),
                properties_written=props, telemetry_columns=TELEMETRY_COLUMNS[:5],
                frame_keys=TELEMETRY_COLUMNS[:5],
                null_test=NullTest(
                    quantity="drag at the initial conditions before the trim, the wetted-wing "
                             "factors against neutral", unit="N",
                    with_value=prepared["with_factors"]["drag_n"],
                    without_value=prepared["baseline"]["drag_n"], threshold=1.0, kind="reached",
                    note=(f"measured on the FDM at {prepared['altitude_m']:.1f} m before the trim, "
                          f"each after a re-latch: drag factor {self.factors['drag']:.6f}, lift "
                          f"factor {self.factors['lift']:.6f} at LWC "
                          f"{self.water['lwc_g_m3']:.3f} g/m^3; threshold 1 N (P2's force floor)")),
                not_claimed=NOT_CLAIMED, frm=rate.frm, std=rate.std,
                readback=self._readback_of(PROPERTY_DRAG),
                jsbsim_writes=tuple(JsbsimWrite(p, "neutral before the trim; every step from the "
                                                   "state read at its top") for p in props),
                model=model))
        word = self.effective["runway_condition"]
        reference_kt = 60.0
        wet = friction_factor(self.runway_condition, reference_kt, self.tire_pressure_psi,
                              self.dry_static_mu)
        out.append(AppliedVariable(
            name="rain.runway_condition", value=self.runway_condition, unit="word",
            source=word.source, model_name=MODEL,
            parameters={**self._common_parameters(), "reference_groundspeed_kt": reference_kt,
                        "friction_factor_at_reference": wet,
                        "per_step": self._readback_report(), "peaks": dict(self.peaks)},
            references=REFERENCES + ((word.std,) if word.std else ()),
            properties_written=(PROPERTY_FRICTION,),
            telemetry_columns=("ground_friction_factor", "hydroplaning"),
            frame_keys=("ground_friction_factor", "hydroplaning"),
            null_test=NullTest(
                quantity=f"ground/static-friction-factor at {reference_kt:g} kt ground speed",
                unit="1", with_value=wet, without_value=1.0, threshold=1e-6,
                kind="reached" if self.runway_condition != "dry" else "bounded",
                note=("computed from the provider's own law at the reference speed against the "
                      "dry runway's 1.0; the braking it moves is measured in tests/test_rain.py "
                      "(stopping distance on the c172p)")),
            not_claimed=NOT_CLAIMED, frm=word.frm, std=word.std,
            readback=self._readback_of(PROPERTY_FRICTION),
            jsbsim_writes=(JsbsimWrite(PROPERTY_FRICTION, "1.0 before the trim; every step from "
                                                          "the ground speed at its top"),),
            model=model))
        return out

    def _readback_report(self) -> Dict[str, Any]:
        errors = dict(self.readback["max_abs_error"])
        return {"steps_checked": self.readback["steps_checked"], "max_abs_error": errors,
                "tolerance": 0.0, "agrees": all(e == 0.0 for e in errors.values()),
                "steps_written": self.steps_written, "basis": READBACK_BASIS}

    # -- the card, the manifest, the columns, the vocabulary -------------------------

    def card_block(self) -> Dict[str, Any]:
        """The numbers for the UE host, keys in the fixed order CARD_KEYS."""
        block = {"rate_mmh": self.rate_mmh, "lwc_g_m3": self.water["lwc_g_m3"],
                 "fall_speed_mps": self.water["fall_speed_mps"],
                 "aerodynamics": self.aerodynamics, "lift_factor": self.factors["lift"],
                 "drag_factor": self.factors["drag"], "frontal_area_m2": self.frontal_area_m2,
                 "runway_condition": self.runway_condition,
                 "tire_pressure_psi": self.tire_pressure_psi,
                 "hydroplaning_speed_kt": self.hydroplaning_speed_kt}
        if tuple(block) != CARD_KEYS:
            raise RuntimeError(f"rain card keys {list(block)} are not the fixed order "
                               f"{list(CARD_KEYS)}")
        return block

    def manifest_block(self) -> Dict[str, Any]:
        return {"applied": self.prepared is not None,
                "effective": {k: {"value": s.value, "source": s.source, "from": s.frm,
                                  "std": s.std} for k, s in self.effective.items()},
                "rate": None if self.rate_source is None else {
                    "value": self.rate_source.value, "source": self.rate_source.source},
                **self._common_parameters(), "prepared": self.prepared,
                "per_step_readback": self._readback_report(), "peaks": dict(self.peaks),
                "card": self.card_block(), "not_claimed": list(NOT_CLAIMED)}

    def recorder_extras(self) -> Dict[str, Any]:
        """The rain columns (TELEMETRY_COLUMNS): the last step's values."""
        return {column: (lambda _fdm, c=column: float(self.last[c]))
                for column in TELEMETRY_COLUMNS}

    def vocabulary(self) -> List[Term]:
        terms = [
            Term("dry", 1.0, "1", "the airframe's own static coefficients",
                 note="ground/static-friction-factor 1"),
            Term("wet", "mu(V, p) / mu_dry", "1", "14 CFR 25.109(c)(1) [unverified here]",
                 valid_range=(0.0, WET_MU_SPEED_MAX_KT), note="ground speed in kt"),
            Term("standing_water", HYDROPLANING_MU, "1",
                 "Horne & Dreher 1963 V_p = 9 sqrt(p) kt [unverified here]; 0.05 is stated",
                 note="the wet value below V_p"),
        ]
        return terms

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({"model": MODEL, "rate_mmh": self.rate_mmh,
                    "aerodynamics": self.aerodynamics, "factors": dict(self.factors),
                    "runway_condition": self.runway_condition,
                    "injections": list(INJECTIONS) if self.aerodynamics else [],
                    "steps_written": self.steps_written})
        return out


READBACK_BASIS = ("a <property> declared by an injected system, an external force's magnitude "
                  "and direction, and ground/static-friction-factor read back the value written "
                  "to the last bit at the top of the following step (measured on the c172p, "
                  "JSBSim 1.2.4, tests/test_rain.py); the provider keeps the largest error")
