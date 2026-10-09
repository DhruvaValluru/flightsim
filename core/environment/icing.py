"""The icing provider: a severity ramp driving the six injected axis
factors and the stall-onset cue (ADVANCEMENTS_BLUEPRINT section 1, work
item P5; the physics enters the stock model through P2's ``icing`` and
``icing_alpha`` XML injections, core/control/derive.py, never by editing
vendored data).

The model, stated
-----------------
Bragg, Hutchison, Merret, Oltman and Pokhariyal (AIAA 2000-0360) write the
iced aerodynamic coefficient of an axis as

    C_A,iced = (1 + eta k_A) C_A

with ``eta`` the icing severity (0 = clean) and ``k_A`` a per-axis, per-
airframe coefficient. The derived airframe carries ``icing/<axis>-factor``
wrapped around EVERY function of that axis (P2), so what is written here
every step is the factor ``1 + eta(t) k_A`` for each of the six axes, and
``eta(t)`` itself into ``icing/eta`` beside them. The severity ramp is

    eta(t) = eta_max * clamp((t - onset_s) / ramp_s, 0, 1)

on the RUN CLOCK (seconds since the run's first step, P3's convention: a
piston's engine start cranks for seconds before the first step); a ramp
of 0 s is a step to ``eta_max`` at ``onset_s``. The stall-onset cue is a
STATED linear cue, not a model of an iced aerofoil:

    icing/alpha-shift-rad = radians(alpha_shift_deg) * eta(t) / eta_max

(0 when nothing is iced). The trim is of the UN-ICED aircraft (every
property at its neutral value before the trim, a stated choice): ice that
the trim solver saw would be ice the trim compensated, and the null pair
would then measure the residual instead of the divergence.

The severity WORDS are a stated mapping -- trace 0.05, light 0.10,
moderate 0.20, severe 0.30 -- chosen inside the 0..0.3 range Bragg's Twin
Otter cases span. AIM 7-1-19's words (trace / light / moderate / severe)
are PILOT REPORTS of an accretion rate, not values of eta; the mapping is
this module's, said so in every record. The 14 CFR Part 25 Appendix C and
Appendix O envelope words are recorded as metadata only and applied
nowhere (no LWC, MVD or temperature enters the model).

The k-table is per airframe, from the ``icing`` block of
``assets/aircraft_config/<fdm>.json``: the DHC6 row is the published Twin
Otter set transcribed from memory and marked [unverified here]; the c172p
carries that row as a NAMED PROXY; an airframe with no block (A320, B747,
p51d) refuses ``icing.airframe_data`` by name -- a Twin Otter table on a
transport is a guess, not a proxy (blueprint correction 7).

The provider is an ``AtmosphereProvider`` by TYPE, not by physics (P4's
precedent): the stack's atmosphere slot is the one with the three hooks
this needs -- ``prepare(fdm)`` before the trim (the neutral writes, the
pre-trim with/without measurement per record), ``properties`` at every
step (the writes) and ``observe`` at the top of every step (the previous
step's writes read back BEFORE this step's). The factors do not compose
with anything in the stack: they go into P2's ``<product>`` wraps, which
is why base.py's warning against aerodynamic plugins does not apply.

Refusals by name (``IcingError.constraint``; the same list the validator
renders as Violations, through one function :func:`problems`):
``icing.severity`` (an unknown severity word), ``icing.eta_range``
(eta_max outside 0..1, a negative onset or ramp, an alpha shift that is
not a number within +-10 deg -- a stated bound), ``icing.envelope`` (an
unknown envelope word), ``icing.airframe_data`` (no k-table for this
airframe, or a malformed one).

NOT claimed: no airframe's icing response is validated; the factor form
scales WHOLE tables (Bragg's k applies to a coefficient, here it scales
the axis, C_L0 and C_Ldelta_e with C_Lalpha); no accretion, no LWC / MVD
or temperature dependence; the DHC6 table is a transcription from memory
[unverified here] and the c172p's is a proxy; the alpha shift moves the
LIFT table's alpha only (P2); the envelope words are metadata; the engine
side (the card block is pinned here, nothing applies it: P9's step).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from ..scenario.blocks import ICING_ENVELOPE_WORDS, ICING_SEVERITY_WORDS
from .base import AtmosphereProvider, Position, Term

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"

#: The severity words: a STATED mapping to eta (see the module docstring;
#: the one table is core/scenario/blocks.py's, the spec's vocabulary).
SEVERITY_WORDS: Dict[str, float] = ICING_SEVERITY_WORDS
SEVERITY_STANDARD = ("a stated mapping of the AIM 7-1-19 pilot-report words to Bragg's eta "
                     "(trace 0.05, light 0.10, moderate 0.20, severe 0.30), inside the 0..0.3 "
                     "range of Bragg et al. 2000's Twin Otter cases [unverified here]; the AIM "
                     "words report an accretion rate, not a value of eta")
#: The envelope words: recorded as metadata, never applied.
ENVELOPE_WORDS = ICING_ENVELOPE_WORDS
ENVELOPE_STANDARDS: Dict[str, str] = {
    "appendix_c": "14 CFR Part 25 Appendix C (continuous and intermittent maximum icing: "
                  "liquid water content, drop size and temperature) [unverified here]; "
                  "recorded as metadata, applied nowhere",
    "appendix_o": "14 CFR Part 25 Appendix O (supercooled large drops: freezing drizzle and "
                  "freezing rain) [unverified here]; recorded as metadata, applied nowhere",
}
#: eta_max lies in this closed range (0 = clean; 1 = every coefficient at 1 + k).
ETA_RANGE = (0.0, 1.0)
#: The alpha shift's stated bound, degrees (P2 measured the cue at 2 deg).
ALPHA_SHIFT_RANGE_DEG = (-10.0, 10.0)

#: The six axes, in the order the k-table and the card carry them.
AXES = ("lift", "drag", "pitch", "roll", "yaw", "side")
K_KEYS = tuple(f"k_{axis}" for axis in AXES)
PROPERTY_ETA = "icing/eta"
PROPERTY_SHIFT = "icing/alpha-shift-rad"
FACTOR_PROPERTIES: Dict[str, str] = {axis: f"icing/{axis}-factor" for axis in AXES}
#: Every property the provider writes, in write order.
PROPERTIES = (PROPERTY_ETA, *FACTOR_PROPERTIES.values(), PROPERTY_SHIFT)
#: The recorder columns (core/fdm/state.py reads the properties where the
#: loaded airframe declares them; 0 / 1.0 / 0 where it does not).
TELEMETRY_COLUMNS = ("icing_eta", *(f"icing_{axis}_factor" for axis in AXES),
                     "icing_alpha_shift_deg")
#: The injections a stated block flies with (core/control/derive.py's names).
INJECTIONS = ("icing", "icing_alpha")
#: The card block's keys, in the fixed order the host reads.
CARD_KEYS = ("eta_max", "onset_s", "ramp_s", "alpha_shift_deg", "k_table", "source")
#: The aero properties each axis's pre-trim measurement reads (JSBSim's own
#: wind-axis forces and body moments), with the unit of the record.
AXIS_MEASURES: Dict[str, Tuple[str, str]] = {
    "lift": ("forces/fwz-aero-lbs", "N"), "drag": ("forces/fwx-aero-lbs", "N"),
    "side": ("forces/fwy-aero-lbs", "N"), "roll": ("moments/l-aero-lbsft", "N m"),
    "pitch": ("moments/m-aero-lbsft", "N m"), "yaw": ("moments/n-aero-lbsft", "N m"),
}
#: The pre-trim null tests' thresholds: forces the P2 force floor (1 N, the
#: lift factor 0.8 moved 1666 N); moments a STATED 1 N m (the trimmed c172p's
#: pitch moment at the initial conditions is 4046 N m, measured; its one-
#: relatch wander 1e-3 N m).
NULL_FLOOR_FORCE_N = 1.0
NULL_FLOOR_MOMENT_NM = 1.0
LBF_TO_N = 4.4482216152605
LBFFT_TO_NM = LBF_TO_N * 0.3048

WHEN_ETA = ("0 before the trim (the trim is of the un-iced aircraft, a stated choice); "
            "eta(t) at the top of every step from the run's first step, t on the run clock")
WHEN_FACTOR = "1.0 before the trim; 1 + eta(t) k at the top of every step"
WHEN_SHIFT = ("0 before the trim; radians(alpha_shift_deg) eta(t) / eta_max at the top of "
              "every step")
MODEL = ("Bragg et al. 2000 factor form C_A,iced = (1 + eta k_A) C_A per axis through P2's "
         "icing injection, eta(t) = eta_max clamp((t - onset_s) / ramp_s, 0, 1) on the run "
         "clock, and a stated linear stall-onset cue alpha_shift = alpha_shift_deg eta / eta_max "
         "through the icing_alpha injection")
REFERENCES = (
    "Bragg, Hutchison, Merret, Oltman, Pokhariyal, 'Effect of ice accretion on aircraft "
    "flight dynamics', AIAA 2000-0360 (the eta k coefficient form and the Twin Otter "
    "k-table) [unverified here: not reachable from this container]",
    "Ratvasky, Van Zante, Riley, NASA TM-1999-209371 / Twin Otter icing flight research "
    "(the airframe the published set was measured on) [unverified here]",
    "FAA AIM 7-1-19 (icing intensity pilot-report words: trace, light, moderate, severe) "
    "[unverified here]",
    "14 CFR Part 25 Appendix C and Appendix O (the icing envelopes named, metadata only) "
    "[unverified here]",
    "14 CFR Part 60 FSTD Directive 2 (the stall-onset cue the alpha shift stands in for) "
    "[unverified here]",
    "ADVANCEMENTS_BLUEPRINT section 1 (work items P2, P5; correction 7: the DHC6 IS the "
    "Twin Otter, the c172p a proxy, the transports and the p51d refused)",
)


class IcingError(ValueError):
    """An icing refusal, by name (``.constraint``)."""

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


# -- the k-table -------------------------------------------------------------------

@dataclass(frozen=True)
class KTable:
    """One airframe's per-axis coefficients with their sources."""

    aircraft: str
    values: Dict[str, float]          # axis -> k
    sources: Dict[str, str]           # axis -> the source string
    source: str                       # the block's own source sentence
    model: str
    proxy: bool
    proxy_of: Optional[str]
    config_path: str
    config_sha256: str

    def factors(self, eta: float) -> Dict[str, float]:
        """The six factors at a severity: ``1 + eta k`` per axis (Bragg)."""
        return {axis: 1.0 + eta * self.values[axis] for axis in AXES}

    def to_dict(self) -> Dict[str, Any]:
        return {"aircraft": self.aircraft, "model": self.model, "source": self.source,
                "proxy": self.proxy, "proxy_of": self.proxy_of,
                "k_table": {f"k_{axis}": {"value": self.values[axis], "source": self.sources[axis]}
                            for axis in AXES},
                "config_path": self.config_path, "config_sha256": self.config_sha256}


def parse_icing_config(aircraft: str, block: Any, config_path: str = "",
                       config_sha256: str = "") -> KTable:
    """The ``icing`` block of an airframe's config, refused
    ``icing.airframe_data`` field by field: ``source``, ``model``,
    ``proxy`` (a boolean; ``proxy_of`` names the airframe when true) and
    ``k_table`` with exactly the six ``k_<axis>`` entries, each
    ``{value: finite number, source: text}``."""
    def refuse(message: str) -> IcingError:
        return IcingError("icing.airframe_data",
                          f"{aircraft}: the icing block of assets/aircraft_config/{aircraft}.json "
                          f"is not usable: {message}")

    if not isinstance(block, Mapping):
        raise refuse("it is not a mapping")
    unknown = set(block) - {"source", "model", "proxy", "proxy_of", "k_table"}
    if unknown:
        raise refuse(f"unknown keys {sorted(unknown)}")
    for key in ("source", "model"):
        if not isinstance(block.get(key), str) or not block[key].strip():
            raise refuse(f"no {key} sentence")
    proxy = block.get("proxy", False)
    if not isinstance(proxy, bool):
        raise refuse("proxy must be true or false")
    proxy_of = block.get("proxy_of")
    if proxy and not (isinstance(proxy_of, str) and proxy_of.strip()):
        raise refuse("a proxy row names the airframe it was measured on")
    if not proxy and proxy_of is not None:
        raise refuse("a row that is not a proxy names no other airframe")
    table = block.get("k_table")
    if not isinstance(table, Mapping) or set(table) != set(K_KEYS):
        raise refuse(f"k_table must carry exactly {list(K_KEYS)}")
    values: Dict[str, float] = {}
    sources: Dict[str, str] = {}
    for axis in AXES:
        entry = table[f"k_{axis}"]
        if not isinstance(entry, Mapping) or set(entry) != {"value", "source"}:
            raise refuse(f"k_{axis} must be {{value, source}}")
        if not _number(entry["value"]):
            raise refuse(f"k_{axis} value is not a finite number")
        if not isinstance(entry["source"], str) or not entry["source"].strip():
            raise refuse(f"k_{axis} has no source")
        values[axis] = float(entry["value"])
        sources[axis] = entry["source"]
    return KTable(aircraft=aircraft, values=values, sources=sources, source=block["source"],
                  model=block["model"], proxy=proxy, proxy_of=proxy_of,
                  config_path=config_path, config_sha256=config_sha256)


def load_k_table(aircraft: str, config_dir: Optional[Path] = None) -> Optional[KTable]:
    """The airframe's k-table, or None when it has no config file or no
    ``icing`` block (the caller refuses ``icing.airframe_data`` when a
    block is stated for it); a malformed block refuses by name here."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    path = directory / f"{aircraft}.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    block = data.get("icing")
    if block is None:
        return None
    try:
        rel = path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        rel = path.as_posix()
    return parse_icing_config(aircraft, block, rel, hashlib.sha256(raw).hexdigest())


def require_k_table(aircraft: str, config_dir: Optional[Path] = None) -> KTable:
    """The k-table, or ``icing.airframe_data`` by name."""
    table = load_k_table(aircraft, config_dir)
    if table is None:
        raise IcingError(
            "icing.airframe_data",
            f"{aircraft}: no icing k-table is configured for this airframe (no icing block "
            f"in assets/aircraft_config/{aircraft}.json); the Twin Otter set is the DHC6's, "
            f"the c172p carries it as a named proxy, and a table for another airframe would "
            f"be a guess, not a proxy")
    return table


# -- the refusals, one list --------------------------------------------------------

def problems(severity: Any, eta_max: Any, onset_s: Any, ramp_s: Any, alpha_shift_deg: Any,
             envelope: Any, aircraft: Optional[str] = None,
             config_dir: Optional[Path] = None) -> List[IcingError]:
    """Every way a stated icing block cannot be delivered, by name: the
    one list the validator renders and the provider refuses. ``eta_max``
    is the RESOLVED value (a stated number, else the word's, else 0)."""
    out: List[IcingError] = []
    if severity is not None and (not isinstance(severity, str) or severity not in SEVERITY_WORDS):
        out.append(IcingError(
            "icing.severity",
            f"icing.severity must be one of {list(SEVERITY_WORDS)} (a stated mapping to eta), "
            f"not {severity!r}", actual=severity))
    if not _number(eta_max):
        out.append(IcingError("icing.eta_range",
                              f"icing.eta_max must be a number in {ETA_RANGE[0]:g}..{ETA_RANGE[1]:g}, "
                              f"not {eta_max!r}", actual=eta_max))
    elif not ETA_RANGE[0] <= float(eta_max) <= ETA_RANGE[1]:
        out.append(IcingError("icing.eta_range",
                              f"icing.eta_max {eta_max:g} is outside {ETA_RANGE[0]:g}..{ETA_RANGE[1]:g} "
                              f"(0 is clean; 1 puts every coefficient at 1 + k)",
                              actual=float(eta_max), limit=ETA_RANGE[1], unit="1"))
    for name, value in (("onset_s", onset_s), ("ramp_s", ramp_s)):
        if not _number(value):
            out.append(IcingError("icing.eta_range",
                                  f"icing.{name} must be a number of seconds, not {value!r}",
                                  actual=value))
        elif float(value) < 0.0:
            out.append(IcingError("icing.eta_range",
                                  f"icing.{name} cannot be negative (the run clock starts at 0)",
                                  actual=float(value), limit=0.0, unit="s"))
    if not _number(alpha_shift_deg):
        out.append(IcingError("icing.eta_range",
                              f"icing.alpha_shift_deg must be a number of degrees, not "
                              f"{alpha_shift_deg!r}", actual=alpha_shift_deg))
    elif not ALPHA_SHIFT_RANGE_DEG[0] <= float(alpha_shift_deg) <= ALPHA_SHIFT_RANGE_DEG[1]:
        out.append(IcingError("icing.eta_range",
                              f"icing.alpha_shift_deg {alpha_shift_deg:g} is outside the stated "
                              f"bound {ALPHA_SHIFT_RANGE_DEG[0]:g}..{ALPHA_SHIFT_RANGE_DEG[1]:g} deg",
                              actual=float(alpha_shift_deg), limit=ALPHA_SHIFT_RANGE_DEG[1],
                              unit="deg"))
    if envelope is not None and (not isinstance(envelope, str) or envelope not in ENVELOPE_WORDS):
        out.append(IcingError(
            "icing.envelope",
            f"icing.envelope must be one of {list(ENVELOPE_WORDS)} (recorded as metadata, "
            f"never applied), not {envelope!r}", actual=envelope))
    if aircraft is not None:
        try:
            require_k_table(aircraft, config_dir)
        except IcingError as exc:
            out.append(exc)
    return out


# -- the provider ------------------------------------------------------------------

@dataclass(frozen=True)
class Stated:
    """One stated field with its provenance, as the spec carried it."""

    value: Any
    source: str = "user"
    frm: Optional[str] = None
    std: Optional[str] = None


def _stated(quantity) -> Optional[Stated]:
    """A block field as a :class:`Stated`, or None when it is at its default
    or unstated (``value: null`` with any source: the null pair's spelling
    of "nothing said", core/record_null.py)."""
    if quantity is None or str(quantity.source) == "default" or quantity.value is None:
        return None
    return Stated(quantity.value, str(quantity.source), quantity.frm, quantity.std)


def eta_at(t: float, eta_max: float, onset_s: float, ramp_s: float) -> float:
    """``eta_max * clamp((t - onset_s) / ramp_s, 0, 1)``; a ramp of 0 is a
    step to ``eta_max`` at ``onset_s``."""
    if ramp_s <= 0.0:
        fraction = 1.0 if t >= onset_s else 0.0
    else:
        fraction = min(1.0, max(0.0, (t - onset_s) / ramp_s))
    return eta_max * fraction


def icing_injections_for(spec) -> Tuple[str, ...]:
    """The XML injections a spec's icing block needs: ``("icing",
    "icing_alpha")`` when the block is stated, nothing otherwise (the
    stock airframe, hashes unchanged)."""
    block = getattr(spec, "icing", None)
    if block is None or block.is_default():
        return ()
    return INJECTIONS


class IcingProvider(AtmosphereProvider):
    """The severity ramp, written to the derived airframe every step and
    read back before the next write (see the module docstring)."""

    name = "icing"

    def __init__(self, aircraft: str, k_table: KTable, eta_max: Any, onset_s: Any = 0.0,
                 ramp_s: Any = 0.0, alpha_shift_deg: Any = 0.0, severity: Any = None,
                 envelope: Any = None, rate_hz: float = 120.0, duration_s: float = 0.0) -> None:
        self.aircraft = aircraft
        self.k_table = k_table
        self.stated: Dict[str, Optional[Stated]] = {
            "severity": severity if isinstance(severity, Stated) or severity is None else Stated(severity),
            "eta_max": eta_max if isinstance(eta_max, Stated) else Stated(eta_max),
            "onset_s": onset_s if isinstance(onset_s, Stated) else Stated(onset_s),
            "ramp_s": ramp_s if isinstance(ramp_s, Stated) else Stated(ramp_s),
            "alpha_shift_deg": (alpha_shift_deg if isinstance(alpha_shift_deg, Stated)
                                else Stated(alpha_shift_deg)),
            "envelope": envelope if isinstance(envelope, Stated) or envelope is None else Stated(envelope),
        }
        found = problems(
            None if self.stated["severity"] is None else self.stated["severity"].value,
            self.stated["eta_max"].value, self.stated["onset_s"].value,
            self.stated["ramp_s"].value, self.stated["alpha_shift_deg"].value,
            None if self.stated["envelope"] is None else self.stated["envelope"].value)
        if found:
            raise found[0]
        if k_table.aircraft != aircraft:
            raise IcingError("icing.airframe_data",
                             f"the k-table is {k_table.aircraft}'s, not {aircraft}'s")
        self.eta_max = float(self.stated["eta_max"].value)
        self.onset_s = float(self.stated["onset_s"].value)
        self.ramp_s = float(self.stated["ramp_s"].value)
        self.alpha_shift_deg = float(self.stated["alpha_shift_deg"].value)
        self.rate_hz = float(rate_hz)
        self.duration_s = float(duration_s)
        #: Per-step bookkeeping: the run clock's zero (JSBSim's sim time at
        #: the first step after the trim), the writes made, the read-backs.
        self._run_clock_zero: Optional[float] = None
        self._last_written: Dict[str, float] = {}
        self._last_t: Optional[float] = None
        self.steps_written = 0
        self.readback: Dict[str, Any] = {"steps_checked": 0, "max_abs_error": {},
                                         "last_written": {}, "last_read": {},
                                         "pre_trim_after_trim": None}
        self.schedule: Dict[str, Any] = {"first_step_eta": None, "eta_at_end": None,
                                         "t_first_ice_s": None, "t_full_s": None,
                                         "steps_with_ice": 0, "steps_at_full": 0,
                                         "steps_first_ice_to_full": None,
                                         "first_ice_step": None, "full_step": None}
        self.prepared: Optional[Dict[str, Any]] = None

    @classmethod
    def from_spec(cls, spec, config_dir: Optional[Path] = None) -> Optional["IcingProvider"]:
        """The provider a spec asks for, or None for the default block
        (nothing derived, nothing written, nothing recorded). Refuses by
        name what the validator refuses (the k-table included)."""
        block = spec.icing
        if block.is_default():
            return None
        aircraft = str(spec.aircraft.value)
        resolved = block.resolved()
        table = require_k_table(aircraft, config_dir)
        return cls(aircraft, table,
                   eta_max=Stated(resolved["eta_max"].value, str(resolved["eta_max"].source),
                                  resolved["eta_max"].frm, resolved["eta_max"].std),
                   onset_s=Stated(block.onset_s.value, str(block.onset_s.source),
                                  block.onset_s.frm, block.onset_s.std),
                   ramp_s=Stated(block.ramp_s.value, str(block.ramp_s.source),
                                 block.ramp_s.frm, block.ramp_s.std),
                   alpha_shift_deg=Stated(block.alpha_shift_deg.value,
                                          str(block.alpha_shift_deg.source),
                                          block.alpha_shift_deg.frm, block.alpha_shift_deg.std),
                   severity=_stated(block.severity), envelope=_stated(block.envelope),
                   rate_hz=float(spec.rate.value), duration_s=float(spec.duration.value))

    # -- the schedule --------------------------------------------------------------

    def eta_at(self, t: float) -> float:
        return eta_at(t, self.eta_max, self.onset_s, self.ramp_s)

    def factors_at(self, eta: float) -> Dict[str, float]:
        return self.k_table.factors(eta)

    def shift_rad_at(self, eta: float) -> float:
        """The stated linear cue: the full shift at eta_max, 0 at 0."""
        if self.eta_max <= 0.0:
            return 0.0
        return math.radians(self.alpha_shift_deg) * (eta / self.eta_max)

    def writes_at(self, t: float) -> Dict[str, float]:
        """Every property the step at run-clock ``t`` writes."""
        eta = self.eta_at(t)
        factors = self.factors_at(eta)
        writes = {PROPERTY_ETA: eta}
        for axis in AXES:
            writes[FACTOR_PROPERTIES[axis]] = factors[axis]
        writes[PROPERTY_SHIFT] = self.shift_rad_at(eta)
        return writes

    @staticmethod
    def neutral_writes() -> Dict[str, float]:
        writes = {PROPERTY_ETA: 0.0}
        for axis in AXES:
            writes[FACTOR_PROPERTIES[axis]] = 1.0
        writes[PROPERTY_SHIFT] = 0.0
        return writes

    # -- the hooks -----------------------------------------------------------------

    def properties(self, position: Position, time_s: float) -> Dict[str, float]:
        """The per-step writes (the stack writes them every step). The run
        clock starts at the first call; the schedule bookkeeping counts
        the iced and the full steps."""
        if self._run_clock_zero is None:
            self._run_clock_zero = float(time_s)
        t = float(time_s) - self._run_clock_zero
        eta = self.eta_at(t)
        writes = self.writes_at(t)
        s = self.schedule
        if self.steps_written == 0:
            s["first_step_eta"] = eta
        if eta > 0.0:
            s["steps_with_ice"] += 1
            if s["t_first_ice_s"] is None:
                s["t_first_ice_s"] = t
                s["first_ice_step"] = self.steps_written
        if self.eta_max > 0.0 and eta >= self.eta_max:
            s["steps_at_full"] += 1
            if s["t_full_s"] is None:
                s["t_full_s"] = t
                s["full_step"] = self.steps_written
                s["steps_first_ice_to_full"] = self.steps_written - s["first_ice_step"] + 1
        s["eta_at_end"] = eta
        self.steps_written += 1
        self._last_t = t
        self._last_written = dict(writes)
        return writes

    def observe(self, fdm) -> None:
        """Read back what the previous step was given, BEFORE this step's
        write (the stack calls this at the top of every ``apply``). On the
        first call after the trim the run clock is latched and the neutral
        pre-trim writes are read back: they survived the trim."""
        if self._run_clock_zero is None:
            self._run_clock_zero = float(fdm.sim_time)
            if self.prepared is not None:
                self.readback["pre_trim_after_trim"] = {
                    prop: {"written": written, "read": fdm.props.get(prop),
                           "agrees": fdm.props.get(prop) == written}
                    for prop, written in self.prepared["neutral_writes"].items()}
        if not self._last_written:
            return
        errors = self.readback["max_abs_error"]
        read_now: Dict[str, float] = {}
        for prop, written in self._last_written.items():
            read = fdm.props.get(prop)
            read_now[prop] = read
            errors[prop] = max(errors.get(prop, 0.0), abs(read - written))
        self.readback["last_written"] = dict(self._last_written)
        self.readback["last_read"] = read_now
        self.readback["steps_checked"] += 1

    def _measure(self, fdm) -> Dict[str, float]:
        g = fdm.props.get
        out = {"alpha_deg": g("aero/alpha-deg"), "qbar_psf": g("aero/qbar-psf")}
        for axis, (prop, unit) in AXIS_MEASURES.items():
            raw = g(prop)
            out[axis] = raw * (LBF_TO_N if unit == "N" else LBFFT_TO_NM)
            out[f"{axis}_raw"] = raw
        return out

    def prepare(self, fdm) -> Dict[str, Any]:
        """Before the trim: check the derived airframe declares every
        property (a programming error otherwise: the runner derives the
        airframe for a stated block), measure the pre-trim with/without
        pair per record at the initial conditions -- the six aero forces
        and moments with the factors at ``eta_max`` against neutral, then
        with the full alpha shift against unshifted (each followed by a
        re-latch of the initial conditions, which is what recomputes the
        aerodynamics: measured, the lift moves 1476 -> 1184 lbf for the
        factor 0.8 only after it) -- and leave every property at its
        neutral value, read back exactly, so the trim is of the un-iced
        aircraft."""
        missing = [p for p in PROPERTIES if not fdm.props.has(p)]
        if missing:
            raise ValueError(f"the loaded airframe declares no {missing}: a stated icing block "
                             f"flies the airframe derived with {INJECTIONS} "
                             f"(core/scenario/runner.py); this one was not")
        neutral = self.neutral_writes()
        fdm.props.set_many(neutral)
        fdm.relatch_initial_conditions()
        baseline = self._measure(fdm)
        full = self.eta_max
        factors = self.factors_at(full)
        writes = {FACTOR_PROPERTIES[axis]: factors[axis] for axis in AXES}
        writes[PROPERTY_ETA] = full
        fdm.props.set_many(writes)
        fdm.relatch_initial_conditions()
        with_factors = self._measure(fdm)
        factor_readback = {prop: fdm.props.get(prop) for prop in writes}
        fdm.props.set_many(neutral)
        fdm.relatch_initial_conditions()
        baseline_2 = self._measure(fdm)
        shift = self.shift_rad_at(full)
        fdm.props.set(PROPERTY_SHIFT, shift)
        fdm.relatch_initial_conditions()
        with_shift = self._measure(fdm)
        shift_readback = fdm.props.get(PROPERTY_SHIFT)
        fdm.props.set_many(neutral)
        fdm.relatch_initial_conditions()
        restored = self._measure(fdm)
        readback = {prop: {"written": written, "read": fdm.props.get(prop),
                           "agrees": fdm.props.get(prop) == written}
                    for prop, written in neutral.items()}
        derived = getattr(fdm, "derived", None)
        self.prepared = {
            "altitude_m": fdm.state().altitude_m,
            "eta_max": full, "factors_at_eta_max": factors, "shift_rad_at_eta_max": shift,
            "baseline": baseline, "with_factors": with_factors, "baseline_2": baseline_2,
            "with_shift": with_shift, "restored": restored,
            "lift_ratio_with_factors": (with_factors["lift"] / baseline["lift"]
                                        if baseline["lift"] else None),
            "factor_readback": {p: {"written": writes[p], "read": r, "agrees": r == writes[p]}
                                for p, r in factor_readback.items()},
            "shift_readback": {"written": shift, "read": shift_readback,
                               "agrees": shift_readback == shift},
            "neutral_writes": neutral, "readback": readback,
            "relatches": 5,
            "derived_aircraft": None if derived is None else derived.name,
            "derived_sha256": None if derived is None else derived.derived_sha256,
            "injections": [] if derived is None else list(derived.injection_names),
        }
        return self.prepared

    # -- the records -----------------------------------------------------------------

    def _readback_of(self, prop: str) -> Readback:
        """The last per-step read-back of a property (the write before it,
        read at the top of the following step), or the pre-trim neutral
        read-back when no step was checked."""
        checked = self.readback["last_written"]
        if prop in checked:
            return Readback(property=prop, value=self.readback["last_read"][prop],
                            written=checked[prop], tolerance=0.0, tolerance_kind="absolute",
                            basis=READBACK_BASIS)
        pre = (self.prepared or {}).get("readback", {}).get(prop)
        if pre is None:
            raise ValueError(f"{prop} was never written by this provider")
        return Readback(property=prop, value=pre["read"], written=pre["written"], tolerance=0.0,
                        tolerance_kind="absolute", basis=READBACK_BASIS + " (the pre-trim "
                        "neutral write: no step was checked)")

    def _model_block(self) -> Model:
        return Model(
            name="Bragg factor form with a severity ramp",
            standard=("C_A,iced = (1 + eta k_A) C_A per axis (Bragg et al. 2000); eta(t) = "
                      "eta_max clamp((t - onset_s) / ramp_s, 0, 1) on the run clock; "
                      "alpha_shift = alpha_shift_deg eta / eta_max (a stated linear cue)"),
            version="JSBSim 1.2.4; P2 icing.xml / icing_alpha.xml injections",
            parameters={"k_table": {f"k_{axis}": self.k_table.values[axis] for axis in AXES},
                        "k_source": self.k_table.source, "k_proxy": self.k_table.proxy,
                        "k_proxy_of": self.k_table.proxy_of,
                        "eta_max": self.eta_max, "onset_s": self.onset_s, "ramp_s": self.ramp_s,
                        "alpha_shift_deg": self.alpha_shift_deg,
                        "severity_words": dict(SEVERITY_WORDS),
                        "severity_words_basis": SEVERITY_STANDARD,
                        "envelope_words": {w: ENVELOPE_STANDARDS[w] for w in ENVELOPE_WORDS},
                        "trim": "of the un-iced aircraft (neutral values before the trim)",
                        "run_clock": "seconds since the run's first step"},
            references=REFERENCES)

    def _common_parameters(self) -> Dict[str, Any]:
        prepared = self.prepared or {}
        return {
            "eta_max": self.eta_max, "onset_s": self.onset_s, "ramp_s": self.ramp_s,
            "alpha_shift_deg": self.alpha_shift_deg,
            "severity": None if self.stated["severity"] is None else self.stated["severity"].value,
            "envelope": None if self.stated["envelope"] is None else self.stated["envelope"].value,
            "k_table": self.k_table.to_dict(),
            "factors_at_eta_max": prepared.get("factors_at_eta_max"),
            "shift_rad_at_eta_max": prepared.get("shift_rad_at_eta_max"),
            "pre_trim": {k: prepared.get(k) for k in ("altitude_m", "baseline", "with_factors",
                                                       "baseline_2", "with_shift", "restored",
                                                       "lift_ratio_with_factors", "relatches",
                                                       "readback", "factor_readback",
                                                       "shift_readback")},
            "per_step_readback": {"steps_checked": self.readback["steps_checked"],
                                  "max_abs_error": dict(self.readback["max_abs_error"]),
                                  "tolerance": 0.0,
                                  "agrees": all(e == 0.0 for e in self.readback["max_abs_error"].values()),
                                  "basis": READBACK_BASIS,
                                  "steps_written": self.steps_written,
                                  "pre_trim_after_trim": self.readback["pre_trim_after_trim"]},
            "schedule": dict(self.schedule),
            "run_clock_zero_sim_time_s": self._run_clock_zero,
            "derived_aircraft": prepared.get("derived_aircraft"),
            "derived_sha256": prepared.get("derived_sha256"),
            "injections": prepared.get("injections"),
        }

    def _not_claimed(self) -> Tuple[str, ...]:
        return (
            "no airframe's icing response is validated: the DHC6 k-table is a transcription "
            "from memory of the published Twin Otter set [unverified here]; the c172p carries "
            "it as a named proxy",
            "the factor form scales WHOLE tables: Bragg's k applies to one coefficient, here the "
            "axis's every function is multiplied (C_L0 and the control terms with C_Lalpha)",
            "no accretion, no liquid water content, drop size or temperature dependence; the "
            "envelope words are metadata and enter nothing",
            "the severity words are a stated mapping, not AIM 7-1-19's meaning (a pilot report "
            "of an accretion rate)",
            "the alpha shift moves the LIFT table's alpha only (drag, the moments and the other "
            "axes keep the true alpha): a stated cue, not a model of an iced aerofoil",
            "the trim is of the un-iced aircraft (a stated choice); the pre-trim measurement "
            "re-latches the initial conditions five times, which moves the trimmed state at "
            "the floating-point floor",
            "the engine side: the card block carries the schedule; no host applies it (P9)",
        )

    def _pre_trim_null(self, axis: str) -> NullTest:
        prepared = self.prepared
        prop, unit = AXIS_MEASURES[axis]
        with_ = prepared["with_factors"][axis]
        without = prepared["baseline"][axis]
        threshold = NULL_FLOOR_FORCE_N if unit == "N" else NULL_FLOOR_MOMENT_NM
        note = (f"measured on the FDM at the initial conditions before the trim ({prepared['altitude_m']:.1f} m, "
                f"alpha {prepared['baseline']['alpha_deg']:.3f} deg): JSBSim's {prop} with the six "
                f"factors at eta_max {self.eta_max:g} (this axis's factor {prepared['factors_at_eta_max'][axis]:.6f}) "
                f"against neutral, each after a re-latch; threshold {threshold:g} {unit}")
        if abs(without) < threshold:
            note += ("; the axis is near zero at the symmetric initial conditions, so a factor "
                     "on it scales nothing there and the test is honestly not reached")
        return NullTest(quantity=f"{axis} aero {'force' if unit == 'N' else 'moment'} at the initial "
                                 f"conditions before the trim, factors at eta_max against neutral",
                        unit=unit, with_value=with_, without_value=without, threshold=threshold,
                        kind="reached", note=note)

    def applied_variables(self) -> List[AppliedVariable]:
        """One record per stated field (the word, the number, the onset,
        the ramp, the shift, the envelope) and one per factor written --
        each with its read-back, its writes, the model block and the
        null test measured before the trim or on the eta channel written.
        Refuses a run never prepared."""
        if self.prepared is None:
            raise ValueError("IcingProvider.prepare(fdm) was never called; there is no read-back "
                             "or null test to record")
        prepared = self.prepared
        common = self._common_parameters()
        model = self._model_block()
        not_claimed = self._not_claimed()
        all_writes = (JsbsimWrite(PROPERTY_ETA, WHEN_ETA),) + tuple(
            JsbsimWrite(FACTOR_PROPERTIES[axis], WHEN_FACTOR) for axis in AXES) + (
            JsbsimWrite(PROPERTY_SHIFT, WHEN_SHIFT),)
        out: List[AppliedVariable] = []
        lift_null = self._pre_trim_null("lift")

        def eta_record(name: str, stated: Stated, unit: str, null: NullTest,
                       extra: Optional[Dict[str, Any]] = None) -> AppliedVariable:
            return AppliedVariable(
                name=name, value=stated.value, unit=unit, source=stated.source, model_name=MODEL,
                parameters={**common, **(extra or {})}, references=REFERENCES + ((stated.std,) if stated.std else ()),
                properties_written=PROPERTIES, telemetry_columns=TELEMETRY_COLUMNS,
                frame_keys=TELEMETRY_COLUMNS, null_test=null, not_claimed=not_claimed,
                frm=stated.frm, std=stated.std, readback=self._readback_of(PROPERTY_ETA),
                jsbsim_writes=all_writes, model=model)

        severity = self.stated["severity"]
        if severity is not None:
            out.append(eta_record("icing.severity", severity, "word", lift_null,
                                  {"word_to_eta": SEVERITY_WORDS[severity.value],
                                   "mapping": SEVERITY_STANDARD,
                                   "number_stated_beside_it": self.stated["eta_max"].source != "inferred"}))
        eta = self.stated["eta_max"]
        if eta.source != "inferred":
            out.append(eta_record("icing.eta", eta, "1", lift_null))
        s = self.schedule
        dt = 1.0 / self.rate_hz
        onset = self.stated["onset_s"]
        if onset.source != "default":
            first = s["t_first_ice_s"]
            out.append(eta_record(
                "icing.onset_s", onset, "s",
                NullTest(quantity="run-clock time of the first step written with eta > 0",
                         unit="s", with_value=self.duration_s if first is None else first,
                         without_value=0.0, threshold=dt, kind="reached",
                         note=(f"measured on the eta channel written: {s['steps_with_ice']} iced steps "
                               f"of {self.steps_written}; without = the null onset (the first step, "
                               f"t = 0); threshold one step ({dt:.6f} s)"
                               + ("" if first is not None else
                                  "; the onset lies beyond the run, so the ice never began and "
                                  "the value is the run's duration"))),
                {"t_first_ice_s": first, "first_ice_step": s["first_ice_step"]}))
        ramp = self.stated["ramp_s"]
        if ramp.source != "default":
            steps = s["steps_first_ice_to_full"]
            out.append(eta_record(
                "icing.ramp_s", ramp, "s",
                NullTest(quantity="steps from the first iced step to the first step at full eta",
                         unit="steps", with_value=(self.steps_written if steps is None else steps),
                         without_value=1.0, threshold=1.0, kind="reached",
                         note=(f"measured on the eta channel written: first iced step "
                               f"{s['first_ice_step']}, first full step {s['full_step']}; without = a "
                               f"ramp of 0 (full on the first iced step: 1 step)"
                               + ("" if steps is not None else
                                  "; full eta was not reached in the run, so the value is the "
                                  "steps written"))),
                {"steps_first_ice_to_full": steps, "full_step": s["full_step"]}))
        shift = self.stated["alpha_shift_deg"]
        if shift.source != "default":
            out.append(AppliedVariable(
                name="icing.alpha_shift_rad", value=math.radians(self.alpha_shift_deg), unit="rad",
                source=shift.source, model_name=MODEL,
                parameters={**common, "alpha_shift_deg": self.alpha_shift_deg,
                            "cue": "linear in eta: the full shift at eta_max, 0 at 0"},
                references=REFERENCES + ((shift.std,) if shift.std else ()),
                properties_written=(PROPERTY_SHIFT,), telemetry_columns=TELEMETRY_COLUMNS,
                frame_keys=TELEMETRY_COLUMNS,
                null_test=NullTest(
                    quantity="lift at the initial conditions before the trim, the LIFT table's "
                             "alpha shifted by the full cue against unshifted",
                    unit="N", with_value=prepared["with_shift"]["lift"],
                    without_value=prepared["baseline_2"]["lift"], threshold=NULL_FLOOR_FORCE_N,
                    kind="reached",
                    note=(f"measured on the FDM at the initial conditions before the trim: the shift "
                          f"{prepared['shift_rad_at_eta_max']:.6f} rad ({self.alpha_shift_deg:g} deg at "
                          f"eta_max) written alone, factors neutral, each after a re-latch; the "
                          f"stall-onset movement itself is P2's static-sweep measurement (-2.0 deg "
                          f"for 2 deg on the c172p), re-measured in tests/test_icing.py")),
                not_claimed=not_claimed, frm=shift.frm, std=shift.std,
                readback=self._readback_of(PROPERTY_SHIFT),
                jsbsim_writes=(JsbsimWrite(PROPERTY_SHIFT, WHEN_SHIFT),), model=model))
        envelope = self.stated["envelope"]
        if envelope is not None:
            written_for_word = [p for p in PROPERTIES if "envelope" in p]
            out.append(AppliedVariable(
                name="icing.envelope", value=envelope.value, unit="word", source=envelope.source,
                model_name=MODEL + " (the envelope word is metadata: applied nowhere)",
                parameters={**common, "standard": ENVELOPE_STANDARDS[envelope.value],
                            "applied": False},
                references=REFERENCES + ((envelope.std,) if envelope.std else ()),
                properties_written=(), telemetry_columns=(), frame_keys=(),
                null_test=NullTest(
                    quantity="properties written on account of the envelope word",
                    unit="properties", with_value=float(len(written_for_word)), without_value=0.0,
                    threshold=0.0, kind="bounded",
                    note="the word is recorded as metadata and applied nowhere: the write set "
                         "carries no envelope property (measured on the provider's write set), "
                         "so the invariance is bounded at 0"),
                not_claimed=not_claimed + ("the envelope word enters no equation: no LWC, MVD or "
                                           "temperature is modelled",),
                frm=envelope.frm, std=envelope.std, model=model))
        row = "a named proxy row" if self.k_table.proxy else "the airframe's own row"
        for axis in AXES:
            prop = FACTOR_PROPERTIES[axis]
            out.append(AppliedVariable(
                name=f"icing.{axis}_factor", value=prepared["factors_at_eta_max"][axis], unit="1",
                source="derived", model_name=MODEL,
                parameters={**common, "axis": axis, "k": self.k_table.values[axis],
                            "k_source": self.k_table.sources[axis],
                            "factor_at_eta_max": prepared["factors_at_eta_max"][axis],
                            "pre_trim_readback": prepared["factor_readback"][prop]},
                references=REFERENCES, properties_written=(prop,),
                telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                null_test=self._pre_trim_null(axis), not_claimed=not_claimed,
                frm=f"1 + eta k_{axis} with k_{axis} = {self.k_table.values[axis]:g} ({row})",
                std=self.k_table.sources[axis], readback=self._readback_of(prop),
                jsbsim_writes=(JsbsimWrite(prop, WHEN_FACTOR),), model=model))
        return out

    # -- the card, the manifest, the vocabulary ------------------------------------------

    def card_block(self) -> Dict[str, Any]:
        """The schedule for the UE host, keys in the fixed order
        ``CARD_KEYS`` and the k-table in ``K_KEYS`` order: the host writes
        eta(t) and the six factors at the top of every step of its own run
        clock and the shift beside them, and refuses ``card.icing_schedule``
        when a key is missing or out of order or the table is not six
        numbers."""
        source = self.k_table.source
        if self.k_table.proxy:
            source = f"PROXY of {self.k_table.proxy_of}: {source}"
        block = {
            "eta_max": self.eta_max,
            "onset_s": self.onset_s,
            "ramp_s": self.ramp_s,
            "alpha_shift_deg": self.alpha_shift_deg,
            "k_table": {f"k_{axis}": self.k_table.values[axis] for axis in AXES},
            "source": source,
        }
        if tuple(block) != CARD_KEYS or tuple(block["k_table"]) != K_KEYS:
            raise RuntimeError(f"icing card keys {list(block)} / {list(block['k_table'])} are not "
                               f"the fixed order {list(CARD_KEYS)} / {list(K_KEYS)}")
        return block

    def manifest_block(self) -> Dict[str, Any]:
        """The run manifest's ``icing`` block: the stated fields, the
        k-table, the pre-trim measurement, the per-step read-back and the
        schedule as delivered."""
        return {"applied": self.prepared is not None,
                "stated": {f: None if s is None else {"value": s.value, "source": s.source,
                                                       "from": s.frm, "std": s.std}
                           for f, s in self.stated.items()},
                "eta_max": self.eta_max, "onset_s": self.onset_s, "ramp_s": self.ramp_s,
                "alpha_shift_deg": self.alpha_shift_deg,
                "k_table": self.k_table.to_dict(), "prepared": self.prepared,
                "per_step_readback": {"steps_checked": self.readback["steps_checked"],
                                      "max_abs_error": dict(self.readback["max_abs_error"]),
                                      "last_written": dict(self.readback["last_written"]),
                                      "last_read": dict(self.readback["last_read"]),
                                      "steps_written": self.steps_written,
                                      "pre_trim_after_trim": self.readback["pre_trim_after_trim"]},
                "schedule": dict(self.schedule),
                "run_clock_zero_sim_time_s": self._run_clock_zero,
                "card": self.card_block()}

    def vocabulary(self) -> List[Term]:
        terms = [Term(word, eta, "1", SEVERITY_STANDARD, valid_range=ETA_RANGE,
                      note="a stated mapping; the AIM word reports an accretion rate")
                 for word, eta in SEVERITY_WORDS.items()]
        for word in ENVELOPE_WORDS:
            terms.append(Term(word, "metadata", None, ENVELOPE_STANDARDS[word],
                              note="recorded, never applied"))
        return terms

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({"model": MODEL, "eta_max": self.eta_max, "onset_s": self.onset_s,
                    "ramp_s": self.ramp_s, "alpha_shift_deg": self.alpha_shift_deg,
                    "severity": None if self.stated["severity"] is None else self.stated["severity"].value,
                    "envelope": None if self.stated["envelope"] is None else self.stated["envelope"].value,
                    "k_table": self.k_table.to_dict(), "injections": list(INJECTIONS),
                    "steps_written": self.steps_written})
        return out


READBACK_BASIS = ("measured here on the c172p (JSBSim 1.2.4): a <property> declared by an injected "
                  "system reads back the value written to the last bit, before and after stepping "
                  "(P2, tests/test_derive_injections.py); the provider reads each of its eight "
                  "properties back at the top of the following step, before that step's write, "
                  "and keeps the largest error (0.0 on every step, tests/test_icing.py)")
