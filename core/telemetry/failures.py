"""The failure schedule: engine out, control jam, hardover, float and
authority loss, each applied at the FIRST integration step whose time is
at or past the stated time and read back on the following step
(ADVANCEMENTS_BLUEPRINT section 1, work item P3; gap P6 of
docs/PHASE3_GAP_ANALYSIS.md).

A schedule is a list of events ``{kind, target, at_s, value}`` read from
the spec's ``failures.events`` field. The schedule is bound to a
trimmed FDM once (``bind``: every property the events need must exist
on the loaded airframe, refused by name otherwise) and then applied by
the per-step hook ``apply(fdm)``, which the runner registers on the FDM
(``FlightDynamics.register_step_hook``) so both of the runner's step
loops -- the stack's ``run_for`` and the explicit guidance loop -- see
it without either loop changing. On every call the hook first reads
back the properties written on the previous call, then writes the
events that are due. What it did is ``applied[]``, one entry per
event in the fixed key order ``APPLIED_KEYS``.

The writes are JSBSim 1.2.4's own controls, chosen by MEASUREMENT here
(tests/test_failures.py; the source lines are the sdist fetched into the
scratchpad and read for this item):

* ``engine_out`` on a TURBINE writes JSBSim's cutoff for that engine:
  ``propulsion/active_engine`` = i, ``propulsion/cutoff_cmd`` = 1,
  ``propulsion/active_engine`` = -1 (FGPropulsion.cpp L651-L680
  ``SetCutoff`` acts on the active engine, or on every turbine when the
  active engine is -1; L721 ``SetActiveEngine``; the ties at L814 and
  L823). The engine then runs ``FGTurbine::Off`` (FGTurbine.cpp L150
  ``if (Cutoff && (phase != tpSpinUp)) phase = tpOff``; L175-L196:
  ``Running = false``, thrust 0, N1 and N2 seeking the windmilling
  values ``qbar/10`` and ``qbar/15``). The blueprint's ``set-running = 0``
  is NOT the write: measured on the A320 at 1500 m / 250 kt, a bare
  ``propulsion/engine/set-running`` = 0 gives thrust 0 on the next step
  and 11943 lbf again on the step after -- ``Running`` false with
  ``Cutoff`` still false enters ``tpStart`` at L146-L147 (``qbar > 30``)
  and ``FGTurbine::Start`` L292-L309 relights the engine (``Running =
  true``) because N2 is above idle. The cutoff holds: thrust 0 on every
  one of 600 steps, ``set-running`` reading 0 (``FGEngine.cpp`` L226-L227
  ties it to ``GetRunning``), N1 83.7 -> 19.9 % over 5 s.
* ``engine_out`` on a PISTON writes ``propulsion/active_engine`` = i,
  ``propulsion/magneto_cmd`` = 0, ``propulsion/active_engine`` = -1
  (FGPropulsion.cpp L598-L614 ``SetMagnetos``; the tie at L819-L820 has
  no getter, so the property is write-only and cannot be read back).
  FGPiston.cpp L569-L573 turns the spark off, L592-L594 sets ``Running``
  false on the next step, L784-L796 leaves the indicated power at the
  friction term; the propeller then spins down on its own inertia.
  Measured on the c172p at 1500 m / 100 kt (120 Hz): power 89.1 ->
  -3.5 hp on the next step, thrust 226.7 lbf halved after 0.39 s, at
  10 % after 1.30 s, through zero at 1.68 s, windmilling drag about
  -40 lbf at 4 s; rpm 2300 -> 1450 at 1.7 s -> 823 at 5 s -> 697 at
  8 s -> 686 at 10 s. A bare ``set-running`` = 0 on a piston is
  undone on the next step: L595-L598 relatches ``Running`` while the
  propeller windmills above 0.8 x idle rpm (measured: reads 1.0 again).
  The c172p's own mixture cutoff (``fcs/mixture-cmd-norm`` = 0) gives
  the same die-off to 0.3 % (measured) through the ``fuel`` test at
  L588; the magneto is the write because it is the propulsion model's
  own switch and needs no FCS property.
* ``control_jam`` / ``hardover`` / ``float`` write 1 into JSBSim's own
  actuator malfunction switch on the failure chain P2 injects
  (``failure/<surface>/actuator/malfunction/fail_stuck`` |
  ``fail_hardover`` | ``fail_zero``; FGActuator.cpp L284-L301 ``bind``).
  L150 ``fail_zero -> Input = 0``; L151 ``fail_hardover -> Input = ClipMin
  or ClipMax by the sign of the input`` (the chain clips to -1..1);
  L160-L161 ``fail_stuck -> Output = PreviousOutput``, L171 keeping it.
  So a jam holds the actuator output of the step BEFORE the failing
  one, and the surface holds where the airframe's FCS put it for that
  command (measured: 0.0 rad of drift over 100 steps on the c172p).
* ``authority_loss`` writes ``failure/<surface>/authority`` = value, the
  gain of the injected ``<pure_gain>`` (P2, blueprint correction 1;
  measured: 0.5 holds 0.5 x the command on every following step).

Refusals by name (``FailureError.constraint``; the validator lists the
same problems through ``problems``): ``failures.kind`` (an unknown
kind, an event that is not a mapping of the four keys),
``failures.target`` (a surface outside elevator / aileron / rudder, an
engine index that is not a non-negative integer or that the airframe
lacks, an engine that is neither turbine nor piston),
``failures.time`` (a time that is not a number, negative, beyond the
run, or a list out of time order), ``failures.actuator_missing`` (a
surface failure on an airframe whose loaded model has no
``failure/<surface>/actuator`` -- a stock airframe, or one the failures
injection refuses), ``failures.value`` (an authority outside 0..1, a
non-number, or a value stated for a kind that takes none).

NOT claimed: no fire, no hydraulic topology, no asymmetric-thrust
compensation (TECS has no lateral loop: after an engine-out the energy
is held and the yaw is not compensated -- stated, not fixed), no sensor
failures, no partial engine failures, no restart. The semantics are the
installed JSBSim 1.2.4's, measured on the c172p and the A320 only.
Nothing engine-side applies the card block. No version is bumped: the
spec block, the channels, the manifest block and the records are
optional and absent-canonical.

THE CHANNELS. ``recorder_extras()`` gives the runner the schedule's own
recorder columns: ``failure_state_flag`` (0 until the first event is
applied, 1 from that step on) and, for every engine the loaded airframe
HAS (probed once at ``bind``, the first ``ENGINE_SLOTS`` engines),
``engine<i>_thrust_n`` (N, every engine type), ``engine<i>_n1_pct`` (a
turbine's N1) or ``engine<i>_rpm`` (a piston's rpm). An engine or a
spool the airframe lacks has NO column -- the same doctrine as the limits
monitor (a column for a quantity never measured would read as a number
about nothing). The blueprint's ``NaN where absent`` was measured and
refused: Python's json writes a bare ``NaN`` token, which the web app's
``response.json()`` on telemetry.json (webapp/static/index.html) and the
frames page's manifest fetch cannot parse, so every run would lose its
ground track and aero panel. The columns therefore vary by airframe and
are always finite; the record's ``telemetry_columns`` names the ones the
run recorded.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from ..record_null import NULL_FLOOR_ANGLE_DEG, NULL_FLOOR_FORCE_N

#: The five kinds, in the order the registry names them.
KINDS = ("engine_out", "control_jam", "hardover", "float", "authority_loss")
#: The kinds that need P2's failure chain on the loaded airframe.
SURFACE_KINDS = ("control_jam", "hardover", "float", "authority_loss")
#: The surfaces the failure chain covers (core/control/derive.py SURFACES).
SURFACES = ("elevator", "aileron", "rudder")
#: JSBSim's own actuator malfunction switch each kind throws
#: (FGActuator.cpp L284-L301).
MALFUNCTIONS = {"control_jam": "fail_stuck", "hardover": "fail_hardover", "float": "fail_zero"}
#: The surface position read back for a surface event (rad).
POSITION_PROPERTIES = {"elevator": "fcs/elevator-pos-rad",
                       "aileron": "fcs/left-aileron-pos-rad",
                       "rudder": "fcs/rudder-pos-rad"}
#: The recorder columns a surface event moves: the runner's surface
#: columns (core/scenario/runner.py SURFACES) and the attitude axis.
SURFACE_COLUMNS = {"elevator": "elevator_deg", "aileron": "aileron_deg", "rudder": "rudder_deg"}
ATTITUDE_COLUMNS = {"elevator": "pitch_deg", "aileron": "roll_deg", "rudder": "heading_deg"}
#: The spec event's keys, in order.
EVENT_KEYS = ("kind", "target", "at_s", "value")
#: The card block ``failure_schedule``: keys in this order and no other.
CARD_KEYS = ("events", "count")
CARD_EVENT_KEYS = ("kind", "target", "at_s", "property", "value")
#: One entry of ``failures_applied[]`` per event, keys in this order.
APPLIED_KEYS = ("kind", "target", "at_s", "t_applied_s", "property", "written", "readback",
                "agrees")
#: The recorder column the schedule supplies through ``Recorder(extra=...)``:
#: 0 until the first event is applied, 1 from that step on.
FLAG_COLUMN = "failure_state_flag"
#: A jammed surface holds within this of its position at the jam over
#: ``JAM_HOLD_STEPS`` steps (V15; the chain has no lag, measured 0.0).
JAM_HOLD_TOLERANCE_RAD = 1e-6
JAM_HOLD_STEPS = 100
#: An authority loss holds value x command within this over the same
#: steps (IEEE 754 product, measured 0.0).
AUTHORITY_HOLD_TOLERANCE = 1e-9
AUTHORITY_HOLD_STEPS = 100
#: The engine-out null test compares the thrust before the write with the
#: thrust once the engine has settled: the next step for a turbine (0 by
#: FGTurbine::Off), ``PISTON_SETTLE_S`` after the write for a piston (the
#: measured zero crossing is 1.68 s on the c172p; 2 s covers it).
PISTON_SETTLE_S = 2.0
#: The engine slots the schedule records (engine<i>_* columns through
#: ``recorder_extras``): the configured airframes have 1, 2 or 4 engines;
#: a B747's engines 2 and 3 are not recorded (stated).
ENGINE_SLOTS = 2
#: JSBSim's propulsion controls (FGPropulsion.cpp L814, L819, L823).
ACTIVE_ENGINE = "propulsion/active_engine"
CUTOFF_CMD = "propulsion/cutoff_cmd"
MAGNETO_CMD = "propulsion/magneto_cmd"

#: The threshold of a surface's position change for hardover / float:
#: the angle floor, in radians.
POSITION_THRESHOLD_RAD = math.radians(NULL_FLOOR_ANGLE_DEG)
#: The threshold of the actuator output change for an authority loss
#: (normalised command; a stated choice far above the product's noise).
AUTHORITY_THRESHOLD = 1e-4

MODEL_NAMES = {
    "engine_out": "JSBSim 1.2.4 engine cutoff (FGTurbine cutoff / FGPiston magnetos)",
    "control_jam": "JSBSim 1.2.4 FGActuator fail_stuck on the injected failure chain",
    "hardover": "JSBSim 1.2.4 FGActuator fail_hardover on the injected failure chain",
    "float": "JSBSim 1.2.4 FGActuator fail_zero on the injected failure chain",
    "authority_loss": "P2 failure chain authority gain (failure/<surface>/authority)",
}

REFERENCES = (
    "ADVANCEMENTS_BLUEPRINT section 1, 'The chosen way', correction 1 and 8; the Blueprint "
    "entry for core/telemetry/failures.py (work item P3)",
    "JSBSim 1.2.4 FGActuator.cpp L140-L200 (Run: fail_zero L150, fail_hardover L151, "
    "fail_stuck L160-L161, PreviousOutput L171), L284-L301 (bind: the malfunction ties) "
    "[source read here]",
    "JSBSim 1.2.4 FGTurbine.cpp L106-L166 (Calculate: the post-trim Cutoff reset L125-L138, "
    "the start condition L146-L147, the cutoff L150), L175-L196 (Off), L292-L309 (Start: the "
    "relight) [source read here; measured on the A320]",
    "JSBSim 1.2.4 FGPiston.cpp L493-L508 (Calculate), L555-L600 (doEngineStartup: the "
    "magneto spark L569-L573, Running false L592-L594, the windmilling relatch L595-L598), "
    "L782-L796 (doEnginePower) [source read here; measured on the c172p]",
    "JSBSim 1.2.4 FGPropulsion.cpp L598-L614 (SetMagnetos), L651-L680 (SetCutoff), "
    "L685-L703 (GetCutoff), L721 (SetActiveEngine), L799-L824 (bind: set-running, "
    "cutoff_cmd L814, magneto_cmd L819-L820 with no getter, active_engine L823); "
    "FGEngine.cpp L226-L227 (engine[i]/set-running tied to GetRunning / SetRunning) "
    "[source read here]",
    "core/control/derive.py and core/control/systems/failures.xml.tmpl (P2): the "
    "re-anchored failure chain the surface kinds act on",
)


class FailureError(ValueError):
    """A schedule the build cannot apply, refused by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit: Optional[str] = None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


def engine_property(index: int, leaf: str) -> str:
    """``propulsion/engine/<leaf>`` for engine 0, ``propulsion/engine[i]/<leaf>``
    otherwise (JSBSim's indexed property names; core/fdm/fdm.py)."""
    return (f"propulsion/engine/{leaf}" if index == 0
            else f"propulsion/engine[{index}]/{leaf}")


def engine_columns(index: int) -> Tuple[str, str, str]:
    """The recorded engine channels for a slot: thrust (N), N1 (%), rpm."""
    return (f"engine{index}_thrust_n", f"engine{index}_n1_pct", f"engine{index}_rpm")


def engine_channels(fdm) -> Dict[str, Tuple[str, Callable[[float], float]]]:
    """{column: (property, converter)} for the engines the loaded airframe
    has, the first ``ENGINE_SLOTS``: thrust for every engine, N1 for a
    turbine, rpm for a piston -- a property the catalog lacks gets no
    column (the module docstring says why)."""
    from ..fdm import units as u

    has = fdm.props.has
    out: Dict[str, Tuple[str, Callable[[float], float]]] = {}
    for index in range(ENGINE_SLOTS):
        thrust, n1, rpm = engine_columns(index)
        if has(engine_property(index, "thrust-lbs")):
            out[thrust] = (engine_property(index, "thrust-lbs"), u.lbf_to_n)
        if has(engine_property(index, "n1")):
            out[n1] = (engine_property(index, "n1"), float)
        if has(engine_property(index, "engine-rpm")):
            out[rpm] = (engine_property(index, "engine-rpm"), float)
    return out


# -- the events and their problems -------------------------------------------------

@dataclass(frozen=True)
class FailureEvent:
    """One scheduled failure: what, on which surface or engine, when, and
    (for an authority loss) how much."""

    kind: str
    target: Any            # a surface name, or an engine index (int)
    at_s: float
    value: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "target": self.target, "at_s": float(self.at_s),
                "value": self.value}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "FailureEvent":
        """An event out of a checked mapping (``problems`` ran first)."""
        value = data.get("value")
        return cls(kind=str(data["kind"]), target=_target(data["target"]),
                   at_s=float(data["at_s"]),
                   value=None if value is None else float(value))

    @property
    def is_surface(self) -> bool:
        return self.kind in SURFACE_KINDS

    @property
    def property(self) -> str:
        """The JSBSim property the event writes (the primary write; the
        engine kinds bracket it with ``propulsion/active_engine``, a
        selector the card states, not a physics write)."""
        if self.kind == "authority_loss":
            return f"failure/{self.target}/authority"
        if self.kind in MALFUNCTIONS:
            return f"failure/{self.target}/actuator/malfunction/{MALFUNCTIONS[self.kind]}"
        return CUTOFF_CMD      # the piston's write is decided at bind (magneto_cmd)


def _target(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    if isinstance(value, str):
        m = re.fullmatch(r"engine(?:\[(\d+)\])?", value.strip())
        if m is not None:
            return int(m.group(1) or 0)
    return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def event_problems(index: int, data: Any, duration_s: Optional[float]) -> List[FailureError]:
    """Every way one event is outside what the build applies, by name."""
    out: List[FailureError] = []
    where = f"failures.events[{index}]"
    if not isinstance(data, Mapping):
        return [FailureError("failures.kind", f"{where} is not a mapping of "
                             f"{list(EVENT_KEYS)}", actual=type(data).__name__)]
    unknown = sorted(set(data) - set(EVENT_KEYS))
    if unknown:
        out.append(FailureError("failures.kind", f"{where} carries unknown keys {unknown}; "
                                f"an event is {list(EVENT_KEYS)}", actual=unknown))
    kind = data.get("kind")
    if kind not in KINDS:
        out.append(FailureError("failures.kind", f"{where}.kind must be one of {list(KINDS)}, "
                                f"not {kind!r}", actual=kind))
        return out
    target = _target(data.get("target"))
    if kind in SURFACE_KINDS:
        if target not in SURFACES:
            out.append(FailureError("failures.target",
                                    f"{where}.target must be a surface of {list(SURFACES)} "
                                    f"for {kind}, not {data.get('target')!r}",
                                    actual=data.get("target")))
    elif not isinstance(target, int) or isinstance(target, bool) or target < 0:
        out.append(FailureError("failures.target",
                                f"{where}.target must be an engine index (0, 1, ...) for "
                                f"engine_out, not {data.get('target')!r}",
                                actual=data.get("target")))
    at_s = data.get("at_s")
    if not _is_number(at_s):
        out.append(FailureError("failures.time", f"{where}.at_s must be a number of seconds, "
                                f"not {at_s!r}", actual=at_s, unit="s"))
    elif at_s < 0.0:
        out.append(FailureError("failures.time", f"{where}.at_s cannot be negative",
                                actual=float(at_s), limit=0.0, unit="s"))
    elif duration_s is not None and at_s > float(duration_s):
        out.append(FailureError("failures.time", f"{where}.at_s lies beyond the run's "
                                f"duration; the failure would never be applied",
                                actual=float(at_s), limit=float(duration_s), unit="s"))
    value = data.get("value")
    if kind == "authority_loss":
        if not _is_number(value):
            out.append(FailureError("failures.value", f"{where}.value must be the remaining "
                                    f"authority, a number in 0..1, not {value!r}", actual=value))
        elif not 0.0 <= float(value) <= 1.0:
            out.append(FailureError("failures.value", f"{where}.value (the remaining "
                                    f"authority) must lie in 0..1", actual=float(value),
                                    limit="0..1", unit="1"))
    elif value is not None:
        out.append(FailureError("failures.value", f"{where}.value is not read for {kind}; "
                                f"state it only for authority_loss", actual=value))
    return out


def airframe_facts(aircraft: str) -> Dict[str, Any]:
    """What the STOCK airframe XML says the validator and the card need:
    its engine count, each engine's type from the engine file it names
    (``piston`` for a <piston_engine>, ``turbine`` for a <turbine_engine>
    or <turboprop_engine>, None when unknown) and whether P2's failures
    injection can anchor on it (the injection's own anchor test over the
    stock text, nothing written)."""
    from ..control.derive import INJECTIONS, DerivationError
    from ..fdm import aircraft as ac

    model = ac.resolve(aircraft)
    text = model.xml_path.read_text(encoding="utf-8")
    propulsion = re.search(r"<propulsion.*?</propulsion>", text, re.S)
    files = re.findall(r'<engine\s+file="([^"]+)"', propulsion.group(0)) if propulsion else []
    types: List[Optional[str]] = []
    for name in files:
        engine_xml = model.root_dir / "engine" / f"{name}.xml"
        kind: Optional[str] = None
        if engine_xml.is_file():
            engine_text = engine_xml.read_text(encoding="utf-8")
            if "<piston_engine" in engine_text:
                kind = "piston"
            elif "<turbine_engine" in engine_text or "<turboprop_engine" in engine_text:
                kind = "turbine"
        types.append(kind)
    try:
        INJECTIONS["failures"].anchor_test(text)
        anchor: Optional[str] = None
    except DerivationError as exc:
        anchor = str(exc)
    return {"aircraft": model.name, "engine_count": len(files), "engine_types": types,
            "failures_anchor_refused": anchor}


def problems(events: Any, duration_s: Optional[float] = None,
             aircraft: Optional[str] = None) -> List[FailureError]:
    """Every way a schedule is outside what the build applies, by name:
    each event's own problems, the list's time order (``failures.time``),
    and -- when the airframe is named -- an engine the airframe lacks
    (``failures.target``) or a surface failure the failures injection
    cannot anchor on it (``failures.actuator_missing``)."""
    if not isinstance(events, (list, tuple)):
        return [FailureError("failures.kind", "failures.events must be a list of events "
                             f"({list(EVENT_KEYS)}), not {type(events).__name__}",
                             actual=type(events).__name__)]
    out: List[FailureError] = []
    for i, data in enumerate(events):
        out.extend(event_problems(i, data, duration_s))
    if out:
        return out
    times = [float(e["at_s"]) for e in events]
    for i in range(1, len(times)):
        if times[i] < times[i - 1]:
            out.append(FailureError("failures.time",
                                    f"failures.events must be in time order: events[{i}] at "
                                    f"{times[i]:g} s follows events[{i - 1}] at {times[i - 1]:g} s",
                                    actual=times[i], limit=times[i - 1], unit="s"))
    if aircraft is not None and events:
        facts = airframe_facts(aircraft)
        for i, data in enumerate(events):
            kind = data["kind"]
            target = _target(data["target"])
            if kind == "engine_out" and target >= facts["engine_count"]:
                out.append(FailureError(
                    "failures.target",
                    f"failures.events[{i}] names engine {target}, which {facts['aircraft']} "
                    f"lacks (its XML declares {facts['engine_count']})",
                    actual=target, limit=facts["engine_count"] - 1))
            elif kind in SURFACE_KINDS and facts["failures_anchor_refused"] is not None:
                out.append(FailureError(
                    "failures.actuator_missing",
                    f"failures.events[{i}] ({kind} on the {target}) needs the failures "
                    f"injection, which {facts['aircraft']} cannot carry: "
                    f"{facts['failures_anchor_refused']}"))
    return out


def failure_injections_for(spec) -> Tuple[str, ...]:
    """The XML injections the runner must derive the airframe with for a
    spec's schedule: empty when no surface failure is scheduled (the
    default path, hashes unchanged), else ``failures`` behind ``tecs``
    when the spec holds its state. An engine-out alone needs none."""
    block = getattr(spec, "failures", None)
    events = [] if block is None else (block.events.value or [])
    if not any(isinstance(e, Mapping) and e.get("kind") in SURFACE_KINDS for e in events):
        return ()
    return (("tecs",) if bool(spec.hold_state.value) else ()) + ("failures",)


# -- the schedule -------------------------------------------------------------------

class _EventState:
    """The runtime bookkeeping of one event."""

    def __init__(self) -> None:
        self.writes: List[Tuple[str, float]] = []      # every property written, in order
        self.property: Optional[str] = None            # the read-back property
        self.written: Optional[float] = None           # the value the readback expects
        self.readback_basis: str = ""
        self.t_applied: Optional[float] = None         # run clock (s since the first step)
        self.sim_time_applied: Optional[float] = None  # JSBSim's clock at the write
        self.step_applied: Optional[int] = None
        self.readback: Optional[float] = None
        self.agrees: Optional[bool] = None
        self.engine_type: Optional[str] = None
        self.before: Dict[str, float] = {}
        self.after: Dict[str, float] = {}
        self.settled: Dict[str, float] = {}
        self.latest: Dict[str, float] = {}
        self.settle_t: Optional[float] = None
        self.hold_reference: Optional[float] = None
        self.hold_samples: List[float] = []
        self.hold_max_drift: Optional[float] = None
        self.notes: List[str] = []

    @property
    def applied(self) -> bool:
        return self.t_applied is not None


class FailureSchedule:
    """The events of one run, applied through the per-step hook.

    ``events`` are mappings or :class:`FailureEvent`; ``duration_s`` and
    ``aircraft`` let the constructor refuse what the validator refuses
    (the same ``problems``), so a schedule that exists can be applied.
    ``stated`` is the spec field's provenance (value, source, from).
    """

    def __init__(self, events: Sequence[Any], duration_s: Optional[float] = None,
                 aircraft: Optional[str] = None, source: str = "user",
                 frm: Optional[str] = None, std: Optional[str] = None) -> None:
        raw = [e.to_dict() if isinstance(e, FailureEvent) else e for e in events]
        found = problems(raw, duration_s, aircraft)
        if found:
            raise found[0]
        self.events: Tuple[FailureEvent, ...] = tuple(FailureEvent.from_mapping(e) for e in raw)
        self.duration_s = None if duration_s is None else float(duration_s)
        self.aircraft = aircraft
        self.source = source
        self.frm = frm
        self.std = std
        self._states: List[_EventState] = [_EventState() for _ in self.events]
        self._pending: List[int] = list(range(len(self.events)))
        self._readback_due: List[int] = []
        self._bound = False
        self._dt: Optional[float] = None
        #: column -> (property, converter) for the engines the bound
        #: airframe has (probed once in ``bind``; empty until then).
        self._engine_columns: Dict[str, Tuple[str, Callable[[float], float]]] = {}
        self.steps = 0
        #: JSBSim's sim time at the run's first step: the zero of the run
        #: clock every ``at_s`` is compared against.
        self.first_call_t: Optional[float] = None
        self.last_t: Optional[float] = None

    @classmethod
    def from_spec(cls, spec) -> "FailureSchedule":
        """The schedule a spec states (empty for the default block)."""
        block = getattr(spec, "failures", None)
        if block is None:
            return cls([])
        q = block.events
        return cls(list(q.value or []), duration_s=float(spec.duration.value),
                   aircraft=str(spec.aircraft.value), source=str(q.source), frm=q.frm,
                   std=q.std)

    def __len__(self) -> int:
        return len(self.events)

    @property
    def needs_injection(self) -> bool:
        """Whether any event needs P2's failure chain on the airframe."""
        return any(e.is_surface for e in self.events)

    @property
    def applied(self) -> List[Dict[str, Any]]:
        """``failures_applied[]``: one entry per event APPLIED so far, in
        the fixed key order ``APPLIED_KEYS``."""
        out = []
        for event, st in zip(self.events, self._states):
            if not st.applied:
                continue
            out.append({"kind": event.kind, "target": event.target, "at_s": event.at_s,
                        "t_applied_s": st.t_applied, "property": st.property,
                        "written": st.written, "readback": st.readback,
                        "agrees": st.agrees})
        return out

    @property
    def any_applied(self) -> bool:
        return any(st.applied for st in self._states)

    # -- binding ------------------------------------------------------------------

    def bind(self, fdm) -> None:
        """Resolve every property on the loaded airframe, refusing by name
        what it lacks: ``failures.actuator_missing`` for a surface kind
        without the injected chain, ``failures.target`` for an engine the
        model does not define or whose type states no cutoff."""
        has = fdm.props.has
        for i, event in enumerate(self.events):
            st = self._states[i]
            if event.is_surface:
                switch = f"failure/{event.target}/actuator/malfunction/fail_stuck"
                if not has(switch):
                    raise FailureError(
                        "failures.actuator_missing",
                        f"failures.events[{i}] ({event.kind} on the {event.target}) needs "
                        f"the failure chain of the failures injection, and the loaded "
                        f"airframe {fdm.aircraft_name!r} declares no {switch}; derive it "
                        f"with FlightDynamics.with_injections(..., ('failures',))")
                st.property = event.property
                st.written = 1.0 if event.kind in MALFUNCTIONS else float(event.value)
                st.writes = [(st.property, st.written)]
                st.readback_basis = (
                    "the malfunction switch (FGActuator.cpp L284-L301) or the injected "
                    "<property> (core/control/derive.py) reads back the value written to the "
                    "last bit on the following step; measured here on the c172p")
                continue
            index = int(event.target)
            running = engine_property(index, "set-running")
            if not has(running):
                raise FailureError(
                    "failures.target",
                    f"failures.events[{i}] names engine {index}, which the loaded airframe "
                    f"{fdm.aircraft_name!r} does not define ({running} is not a property)")
            if has(engine_property(index, "n1")) and has(CUTOFF_CMD):
                st.engine_type = "turbine"
                st.property = CUTOFF_CMD
                st.written = 1.0
                st.writes = [(ACTIVE_ENGINE, float(index)), (CUTOFF_CMD, 1.0),
                             (ACTIVE_ENGINE, -1.0)]
                st.readback_basis = (
                    "propulsion/cutoff_cmd read with propulsion/active_engine set to the "
                    "engine and restored (FGPropulsion.cpp L685-L710: GetCutoff answers for "
                    "the active engine); FGTurbine::Off then holds Running false, so "
                    "engine[i]/set-running reads 0 (recorded beside it); measured here on "
                    "the A320 -- a bare set-running 0 relights on the next step")
            elif has(MAGNETO_CMD):
                st.engine_type = "piston"
                st.property = running
                st.written = 0.0
                st.writes = [(ACTIVE_ENGINE, float(index)), (MAGNETO_CMD, 0.0),
                             (ACTIVE_ENGINE, -1.0)]
                st.readback_basis = (
                    "propulsion/magneto_cmd is write-only (FGPropulsion.cpp L819-L820 ties "
                    "it with no getter), so the read-back property is engine[i]/set-running, "
                    "which FGPiston::doEngineStartup L592-L594 sets false on the next step "
                    "without spark; 0.0 is the value the magneto write implies, measured "
                    "here on the c172p")
            else:
                raise FailureError(
                    "failures.target",
                    f"failures.events[{i}] names engine {index} of {fdm.aircraft_name!r}, "
                    f"which is neither a turbine (no n1 / cutoff_cmd) nor a piston (no "
                    f"magneto_cmd); no engine-out write is stated for it")
        self._dt = float(fdm.dt)
        self._engine_columns = engine_channels(fdm)
        self._bound = True

    # -- the per-step hook -----------------------------------------------------------

    def apply(self, fdm) -> None:
        """Call once per step, BEFORE the step (the runner registers it as
        the FDM's step hook). Reads back the previous call's writes, keeps
        the hold measurements, then writes every event whose time has
        come: the first call with ``t >= at_s`` on the run clock (seconds
        since the first call)."""
        if not self._bound:
            raise FailureError("failures.actuator_missing",
                               "FailureSchedule.bind(fdm) was never called; the properties "
                               "the events write are unresolved")
        sim_time = float(fdm.sim_time)
        if self.first_call_t is None:
            self.first_call_t = sim_time
        # The run clock: seconds since the run's first step. JSBSim's own
        # clock is not 0 there (a piston's engine start cranks for
        # seconds: 4.875 s on the c172p, measured), so ``at_s`` counts
        # from the first recorded sample, as a user reads it.
        t = sim_time - self.first_call_t
        self.last_t = t
        for i in self._readback_due:
            self._read_back(fdm, i, t)
        self._readback_due = []
        for i, st in enumerate(self._states):
            if st.applied and st.readback is not None:
                self._monitor(fdm, i, t)
        for i in list(self._pending):
            event = self.events[i]
            if t >= event.at_s:
                self._write(fdm, i, t, sim_time)
                self._pending.remove(i)
                self._readback_due.append(i)
        self.steps += 1

    def _observe(self, fdm, i: int) -> Dict[str, float]:
        event = self.events[i]
        st = self._states[i]
        g = fdm.props.get
        if event.is_surface:
            out = {"position_rad": g(POSITION_PROPERTIES[event.target]),
                   "cmd_in": g(f"failure/{event.target}/cmd-in"),
                   "command": g(f"fcs/{event.target}-cmd-norm")}
        else:
            index = int(event.target)
            out = {"thrust_lbf": g(engine_property(index, "thrust-lbs")),
                   "set_running": g(engine_property(index, "set-running"))}
            if st.engine_type == "turbine":
                out["n1_pct"] = g(engine_property(index, "n1"))
            else:
                out["rpm"] = g(engine_property(index, "engine-rpm"))
        return out

    def _write(self, fdm, i: int, t: float, sim_time: float) -> None:
        st = self._states[i]
        st.before = self._observe(fdm, i)
        for prop, value in st.writes:
            fdm.props.set(prop, value)
        st.t_applied = t
        st.sim_time_applied = sim_time
        st.step_applied = self.steps

    def _read_back(self, fdm, i: int, t: float) -> None:
        event = self.events[i]
        st = self._states[i]
        if st.engine_type == "turbine":
            fdm.props.set(ACTIVE_ENGINE, float(event.target))
            st.readback = float(fdm.props.get(CUTOFF_CMD))
            fdm.props.set(ACTIVE_ENGINE, -1.0)
        else:
            st.readback = float(fdm.props.get(st.property))
        st.agrees = (st.readback == st.written)
        st.after = self._observe(fdm, i)
        if event.is_surface:
            st.hold_reference = (st.after["position_rad"] if event.kind == "control_jam"
                                 else None)
        if event.kind == "engine_out":
            settle = 0.0 if st.engine_type == "turbine" else PISTON_SETTLE_S
            st.settle_t = st.t_applied + settle
            if settle == 0.0:
                st.settled = dict(st.after)

    def _monitor(self, fdm, i: int, t: float) -> None:
        event = self.events[i]
        st = self._states[i]
        if event.kind == "control_jam" and len(st.hold_samples) < JAM_HOLD_STEPS:
            position = fdm.props.get(POSITION_PROPERTIES[event.target])
            st.hold_samples.append(position)
            drift = abs(position - st.hold_reference)
            st.hold_max_drift = drift if st.hold_max_drift is None else max(st.hold_max_drift, drift)
        elif event.kind == "authority_loss" and len(st.hold_samples) < AUTHORITY_HOLD_STEPS:
            cmd_in = fdm.props.get(f"failure/{event.target}/cmd-in")
            command = fdm.props.get(f"fcs/{event.target}-cmd-norm")
            expected = max(-1.0, min(1.0, float(event.value) * command))
            st.hold_samples.append(cmd_in)
            drift = abs(cmd_in - expected)
            st.hold_max_drift = drift if st.hold_max_drift is None else max(st.hold_max_drift, drift)
        elif event.kind == "engine_out" and not st.settled:
            st.latest = self._observe(fdm, i)
            if t >= st.settle_t:
                st.settled = st.latest

    # -- reporting ---------------------------------------------------------------------

    def recorder_extras(self) -> Dict[str, Callable[[Any], float]]:
        """The schedule's own recorder columns: ``failure_state_flag`` and
        the engine channels of the bound airframe (see the module
        docstring); the flag alone before ``bind``."""
        out: Dict[str, Callable[[Any], float]] = {
            FLAG_COLUMN: lambda _fdm: 1.0 if self.any_applied else 0.0}
        for column, (prop, convert) in self._engine_columns.items():
            out[column] = (lambda fdm, p=prop, c=convert: float(c(fdm.props.get(p))))
        return out

    @property
    def engine_columns_recorded(self) -> Tuple[str, ...]:
        return tuple(self._engine_columns)

    def hold_result(self, i: int) -> Optional[Dict[str, Any]]:
        """The hold measurement of a jam or an authority loss: the
        reference, the steps measured, the worst drift, and whether it is
        within tolerance -- None for the other kinds."""
        event = self.events[i]
        st = self._states[i]
        if event.kind == "control_jam":
            tolerance = JAM_HOLD_TOLERANCE_RAD
            quantity = "surface position (rad) against its value at the jam"
        elif event.kind == "authority_loss":
            tolerance = AUTHORITY_HOLD_TOLERANCE
            quantity = "actuator output against value x command (normalised)"
        else:
            return None
        return hold_check(st.hold_samples, st.hold_reference, st.hold_max_drift, tolerance,
                          quantity)

    def report(self) -> Dict[str, Any]:
        """The run manifest's ``failures`` block."""
        return {
            "scheduled": [e.to_dict() for e in self.events],
            "count": len(self.events),
            "needs_injection": self.needs_injection,
            "applied": self.applied,
            "applied_count": len(self.applied),
            "steps": self.steps,
            "dt_s": self._dt,
            "run_clock_zero_sim_time_s": self.first_call_t,
            "hook": "FlightDynamics.register_step_hook(schedule.apply): before every step, "
                    "both runner loops",
            "flag_column": FLAG_COLUMN,
            "engine_columns": list(self._engine_columns),
            "hold": [self.hold_result(i) for i in range(len(self.events))],
            "engine_types": [st.engine_type for st in self._states],
        }

    def card_block(self) -> Dict[str, Any]:
        """The run card's ``failure_schedule`` block: the events with the
        property each writes, keys in ``CARD_EVENT_KEYS`` order, and the
        count. An engine-out's property is the bound airframe's (cutoff
        for a turbine, magneto for a piston) or, before binding, the one
        the stock airframe's engine file says (``airframe_facts``); the
        host brackets it with ``propulsion/active_engine`` (stated in the
        contract). Raises when the order ever differs from the fixed one."""
        events = []
        types: List[Optional[str]] = []
        if not self._bound and self.aircraft is not None and any(
                not e.is_surface for e in self.events):
            types = airframe_facts(self.aircraft)["engine_types"]
        for i, event in enumerate(self.events):
            st = self._states[i]
            prop = st.property if st.property is not None else event.property
            value = st.written if st.written is not None else (
                float(event.value) if event.kind == "authority_loss" else 1.0)
            if st.property is None and event.kind == "engine_out":
                index = int(event.target)
                if index < len(types) and types[index] == "piston":
                    prop, value = MAGNETO_CMD, 0.0
            entry = {"kind": event.kind, "target": event.target, "at_s": float(event.at_s),
                     "property": prop, "value": value}
            if tuple(entry) != CARD_EVENT_KEYS:
                raise RuntimeError(f"failure_schedule event keys {list(entry)} are not the "
                                   f"fixed order {list(CARD_EVENT_KEYS)}")
            events.append(entry)
        block = {"events": events, "count": len(events)}
        if tuple(block) != CARD_KEYS:
            raise RuntimeError(f"failure_schedule keys {list(block)} are not the fixed order "
                               f"{list(CARD_KEYS)}")
        return block

    # -- the records ---------------------------------------------------------------------

    def _null_test(self, i: int) -> Optional[NullTest]:
        """The event's in-run null test, or None for an event the run
        ended before (nothing written, nothing to measure -- said in the
        record's parameters, never a number about nothing)."""
        event = self.events[i]
        st = self._states[i]
        if not st.applied or st.readback is None:
            return None
        note_tail = (f"applied at t = {st.t_applied:.6f} s for at_s {event.at_s:g} s; "
                     f"read back on the following step")
        if event.kind == "engine_out":
            index = int(event.target)
            settled = st.settled or st.latest or st.after
            settled_note = ("the next step" if st.engine_type == "turbine" else
                            f"{PISTON_SETTLE_S:g} s after the write (the measured die-off)"
                            if st.settled else
                            f"the last step of the run ({PISTON_SETTLE_S:g} s of die-off "
                            f"not reached)")
            return NullTest(
                quantity=f"engine {index} thrust before the write vs {settled_note}",
                unit="N", with_value=_lbf_to_n(settled["thrust_lbf"]),
                without_value=_lbf_to_n(st.before["thrust_lbf"]),
                threshold=NULL_FLOOR_FORCE_N, kind="reached",
                note=f"{st.engine_type}: " + note_tail)
        if event.kind == "control_jam":
            hold = self.hold_result(i) or {}
            drift = hold.get("max_abs_drift")
            return NullTest(
                quantity=f"max |{event.target} position - position at the jam| over the "
                         f"{hold.get('steps', 0)} steps after it",
                unit="rad", with_value=0.0 if drift is None else float(drift),
                without_value=0.0, threshold=JAM_HOLD_TOLERANCE_RAD, kind="bounded",
                note="an invariance: the jammed surface holds (fail_stuck keeps the "
                     "previous actuator output, FGActuator.cpp L160-L161); the with/"
                     "without pair (jam vs none, the flight diverging) is the null pair "
                     "on failures.events; " + note_tail)
        if event.kind in ("hardover", "float"):
            return NullTest(
                quantity=f"{event.target} position on the step after the write vs the step "
                         f"before",
                unit="rad", with_value=st.after["position_rad"],
                without_value=st.before["position_rad"],
                threshold=POSITION_THRESHOLD_RAD, kind="reached",
                note=f"{MALFUNCTIONS[event.kind]}; threshold = the angle floor "
                     f"{NULL_FLOOR_ANGLE_DEG:g} deg in radians; " + note_tail)
        return NullTest(
            quantity=f"{event.target} actuator output (failure/{event.target}/cmd-in) on the "
                     f"step after the write vs the step before",
            unit="1", with_value=st.after["cmd_in"], without_value=st.before["cmd_in"],
            threshold=AUTHORITY_THRESHOLD, kind="reached",
            note=(f"authority {event.value:g} x command {st.before['command']:.6g}; "
                  f"a zero command leaves nothing to scale and is honestly not reached; "
                  + note_tail))

    def applied_variables(self, recorder=None) -> List[AppliedVariable]:
        """One record per event (``failures.<kind>[<i>]``) and one for the
        spec field (``failures.events``), from what ``apply`` measured.
        An event never applied (the run ended first) has no readback and
        no null test (``parameters.applied`` false); the schedule record's own
        null test is the recorder's flag column, last sample against
        first, with the schedule-level with/without pair being
        ``core.record_null.run_null_pair`` on ``failures.events``."""
        if not self.events:
            return []
        if not self._bound:
            raise ValueError("FailureSchedule.bind(fdm) was never called; there is no "
                             "readback to record")
        out: List[AppliedVariable] = []
        for i, event in enumerate(self.events):
            st = self._states[i]
            columns = self._columns(i)
            hold = self.hold_result(i)
            parameters: Dict[str, Any] = {
                "kind": event.kind, "target": event.target, "at_s": event.at_s,
                "t_applied_s": st.t_applied, "sim_time_applied_s": st.sim_time_applied,
                "step_applied": st.step_applied, "run_clock_zero_sim_time_s": self.first_call_t,
                "dt_s": self._dt,
                "within_one_step": (None if st.t_applied is None
                                    else 0.0 <= st.t_applied - event.at_s < self._dt),
                "property": st.property, "written": st.written,
                "writes": [{"property": p, "value": v} for p, v in st.writes],
                "readback_value": st.readback, "readback_agrees": st.agrees,
                "engine_type": st.engine_type,
                "before": dict(st.before), "after": dict(st.after),
                "settled": dict(st.settled), "hold": hold,
                "applied": st.applied,
            }
            readback = None
            if st.readback is not None:
                readback = Readback(property=st.property, value=st.readback,
                                    written=st.written, tolerance=0.0,
                                    tolerance_kind="absolute", basis=st.readback_basis)
            model_parameters = {
                "property": st.property, "writes": [p for p, _ in st.writes],
                "when": "the first step with t >= at_s, before that step's integration",
                "semantics": _semantics(event.kind, st.engine_type),
            }
            out.append(AppliedVariable(
                name=f"failures.{event.kind}[{i}]",
                value=(float(event.value) if event.kind == "authority_loss"
                       else (st.written if st.written is not None else 1.0)),
                unit="1", source=self.source,
                model=MODEL_NAMES[event.kind], parameters=parameters,
                references=REFERENCES + ((self.std,) if self.std else ()),
                properties_written=tuple(dict.fromkeys(p for p, _ in st.writes)),
                telemetry_columns=columns, frame_keys=columns,
                null_test=self._null_test(i),
                not_claimed=NOT_CLAIMED + (
                    ("the engine's own restart or a partial power loss",)
                    if event.kind == "engine_out" else
                    ("a rate limit, lag or hydraulic topology on the failed surface",)),
                frm=self.frm, std=self.std, readback=readback,
                jsbsim_writes=tuple(JsbsimWrite(p, f"once, at the first step with t >= {event.at_s:g} s")
                                    for p in dict.fromkeys(p for p, _ in st.writes)),
                model_block=Model(name=MODEL_NAMES[event.kind],
                                  standard="none: JSBSim 1.2.4's own controls, measured",
                                  version="JSBSim 1.2.4", parameters=model_parameters,
                                  references=REFERENCES),
            ))
        out.append(self._schedule_variable(recorder))
        return out

    def _columns(self, i: int) -> Tuple[str, ...]:
        event = self.events[i]
        if event.is_surface:
            return (FLAG_COLUMN, SURFACE_COLUMNS[event.target], ATTITUDE_COLUMNS[event.target],
                    "altitude_m")
        index = int(event.target)
        thrust, n1, rpm = engine_columns(index)
        engine = tuple(c for c in (thrust, n1, rpm) if c in self._engine_columns)
        return (FLAG_COLUMN,) + engine + ("altitude_m", "tas_kt", "heading_deg")

    def _schedule_variable(self, recorder) -> AppliedVariable:
        flag = None
        if recorder is not None and FLAG_COLUMN in recorder.columns:
            flag = list(recorder.columns[FLAG_COLUMN])
        first = float(flag[0]) if flag else 0.0
        last = float(flag[-1]) if flag else 0.0
        expected = 1.0 if self.any_applied else 0.0
        readback = None
        if flag:
            readback = Readback(
                property=f"telemetry.{FLAG_COLUMN}[{len(flag) - 1}]", value=last,
                written=expected, tolerance=0.0, tolerance_kind="absolute",
                basis="the recorder's extra column is the schedule's own any_applied flag "
                      "sampled after each step; read back from recorder.columns after the "
                      "run (this grades the recorder's store, not JSBSim's)")
        columns = (FLAG_COLUMN,) + tuple(self._engine_columns)
        return AppliedVariable(
            name="failures.events", value=[e.to_dict() for e in self.events], unit="events",
            source=self.source, model="failure schedule (core/telemetry/failures.py)",
            parameters={"count": len(self.events), "applied_count": len(self.applied),
                        "applied": self.applied, "needs_injection": self.needs_injection,
                        "steps": self.steps, "dt_s": self._dt,
                        "hold": [self.hold_result(i) for i in range(len(self.events))]},
            references=REFERENCES + ((self.std,) if self.std else ()),
            properties_written=tuple(dict.fromkeys(
                p for st in self._states for p, _ in st.writes)),
            telemetry_columns=columns, frame_keys=columns,
            null_test=None if not flag else NullTest(
                quantity=f"{FLAG_COLUMN} at the last recorded sample vs the first",
                unit="1", with_value=last, without_value=first, threshold=1.0, kind="reached",
                note="the schedule's with/without pair (this schedule against no schedule, "
                     "the flight diverging) is core.record_null.run_null_pair on "
                     "failures.events, measured in tests/test_failures_block.py; "
                     "attach_null_pair replaces this test with the pair's when it is run"),
            not_claimed=NOT_CLAIMED,
            frm=self.frm, std=self.std, readback=readback,
            model_block=Model(name="failure schedule", standard="none",
                              version="JSBSim 1.2.4",
                              parameters={"kinds": list(KINDS), "surfaces": list(SURFACES),
                                          "hook": "FlightDynamics step hook, before each step"},
                              references=REFERENCES),
        )


NOT_CLAIMED = (
    "no fire, no hydraulic topology, no sensor failure, no partial engine failure",
    "no asymmetric-thrust compensation: TECS has no lateral loop, so after an engine-out "
    "the energy is held and the yaw is not compensated (stated, not fixed)",
    "the semantics are the installed JSBSim 1.2.4's, measured on the c172p and the A320 "
    "only; nothing is said about an aeroplane",
    "the engine side: the card block is pinned here and no host applies it",
)


def hold_check(samples: Sequence[float], reference: Optional[float],
               max_abs_drift: Optional[float], tolerance: float,
               quantity: str) -> Dict[str, Any]:
    """The hold verdict: the worst drift over the measured steps against
    the tolerance. ``ok`` is None when nothing was measured (the run
    ended before the failure, or on the step of it)."""
    steps = len(samples)
    drift = None if steps == 0 else float(max_abs_drift if max_abs_drift is not None else 0.0)
    return {"quantity": quantity, "reference": reference, "steps": steps,
            "max_abs_drift": drift, "tolerance": float(tolerance),
            "ok": None if drift is None else drift <= float(tolerance)}


def _lbf_to_n(lbf: float) -> float:
    from ..fdm import units as u

    return u.lbf_to_n(float(lbf))


def _semantics(kind: str, engine_type: Optional[str]) -> str:
    if kind == "engine_out":
        if engine_type == "turbine":
            return ("cutoff_cmd = 1 for the active engine (FGPropulsion.cpp L651-L680): "
                    "FGTurbine::Calculate L150 puts the engine in tpOff and Off() L175-L196 "
                    "returns 0 thrust with Running false; N1/N2 spin down toward the "
                    "windmilling values; no relight while Cutoff is true (L146-L147)")
        return ("magneto_cmd = 0 for the active engine (FGPropulsion.cpp L598-L614): "
                "FGPiston::doEngineStartup L569-L573 removes the spark, L592-L594 sets "
                "Running false on the next step, power falls to the friction term "
                "(L782-L796) and the propeller spins down on its inertia over seconds")
    if kind == "control_jam":
        return ("fail_stuck: FGActuator::Run L160-L161 outputs PreviousOutput (the output "
                "of the step before the failure) on every step; the surface holds where "
                "the airframe's FCS put it for that command")
    if kind == "hardover":
        return ("fail_hardover: FGActuator::Run L151 replaces the input by ClipMin or "
                "ClipMax (the chain's -1 / +1) by the sign of the input")
    if kind == "float":
        return "fail_zero: FGActuator::Run L150 replaces the input by 0"
    return ("failure/<surface>/authority is the gain of the injected <pure_gain> on the "
            "host's command (core/control/systems/failures.xml.tmpl); the actuator writes "
            "authority x command into failure/<surface>/cmd-in, which the re-anchored FCS "
            "reads (P2, blueprint correction 1)")
