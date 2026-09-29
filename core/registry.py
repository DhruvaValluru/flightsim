"""The registry of introduced variables: "every introduced variable returns
the record" made a test (ADVANCEMENTS_BLUEPRINT section 2, work item R1).

One :class:`VariableRecord` per variable the additions introduce: its
dotted name, the spec field it is read from (``spec_path``, None for an
observer or a derived quantity that no spec field states), its unit,
the JSBSim properties it writes and when, the telemetry channels it
moves with their units, its NULL value (what the same run looks like
without it), the readback tolerance the property store is held to, the
u_input rule parameters, and the channels the UE host recorder must
carry for it.

What the registry refuses, by name:

* ``record.unregistered`` -- a spec field under a section the registry
  claims (today: ``atmosphere``) that no entry claims. Checked by
  :func:`unregistered_fields` over the spec's dict; the integrator calls
  it from core/scenario/validate.py (the patch is returned with R1).
* ``record.null_value`` -- a spec-field variable registered without a
  null value, or a null pair asked for a variable that has no spec field
  to null, or whose stated value IS the null value (core/record_null.py).
* ``record.effect_channel`` -- a null pair asked for a variable that
  names no effect channel, or whose registered channel the run did not
  record (core/record_null.py).
* ``record.effect_channel_unit`` -- an effect channel registered with no
  unit, or with a unit that contradicts the recorder's suffix convention
  (``core.capture.manifest.suffix_unit``): the manifest consults this
  registry BEFORE the suffix table, so a wrong unit here would be a
  silent wrong unit in every frame.

A duplicate name is a programming error (ValueError), not a refusal.

The batch-1 entries (scene.geoid_undulation_m, limits.monitor,
instruments.profile, scene.landcover) are observers or derived
quantities: no spec field, no JSBSim write, their null tests measured
by their producers. The physics-wave entries (atmosphere.*) carry the
JSBSim properties and the readback tolerances measured here (see each
``reason``); their spec fields do not exist until P1 lands, so today
``unregistered_fields`` sees no ``atmosphere`` section and reports
nothing -- measured in tests/test_registry.py.

NOT claimed: the registry says what a variable writes and moves; it does
not say the physics is right. A declared spread for a default is the
addition's declaration, not a measured distribution. The host channel
list is a contract for the C++ recorder, unverified here (no engine).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from .records import JsbsimWrite, TOLERANCE_KINDS


class RecordError(Exception):
    """A registry or record-2 refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


class _NoNull:
    """Sentinel: the variable has no null value the spec can state (an
    observer or a derived quantity; the producer measures its own null
    test). Distinct from ``None``, which means "the field absent"."""

    def __repr__(self) -> str:
        return "NO_NULL"


NO_NULL = _NoNull()


@dataclass(frozen=True)
class EffectChannel:
    """A telemetry channel the variable moves, with its unit stated."""

    name: str
    unit: str

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "unit": self.unit}


@dataclass(frozen=True)
class ReadbackTolerance:
    """How far a property read back may sit from the value written,
    ``absolute`` in the property's unit or ``relative`` to the written
    value, with the measured reason."""

    value: float
    kind: str = "absolute"
    reason: str = ""

    def __post_init__(self) -> None:
        if self.kind not in TOLERANCE_KINDS:
            raise ValueError(f"readback tolerance kind {self.kind!r} is not one of {TOLERANCE_KINDS}")
        if float(self.value) < 0.0:
            raise ValueError("a negative readback tolerance")
        if not self.reason:
            raise ValueError("a readback tolerance states its measured reason")

    def to_dict(self) -> Dict[str, Any]:
        return {"value": float(self.value), "kind": self.kind, "reason": self.reason}


@dataclass(frozen=True)
class UInputRule:
    """The per-variable parameters of the one u_input rule (GUM JCGM
    100:2008 eq. 10, core/uncertainty.py): u_x by source rank -- user 0
    unless a tolerance is stated, inferred (b/2)/sqrt(3) for a vocabulary
    bin of width ``bin_width`` = b, sampled 0 (the draw is the value),
    model/default the ``declared_spread``."""

    bin_width: Optional[float] = None       # b, in the variable's unit; None = no vocabulary
    declared_spread: float = 0.0            # u_x for a model/default value
    note: str = ""

    def __post_init__(self) -> None:
        if self.bin_width is not None and float(self.bin_width) <= 0.0:
            raise ValueError("a vocabulary bin width is positive")
        if float(self.declared_spread) < 0.0:
            raise ValueError("a declared spread is not negative")

    def to_dict(self) -> Dict[str, Any]:
        return {"rule": "GUM eq. 10; u_x by source rank",
                "bin_width": self.bin_width, "declared_spread": float(self.declared_spread),
                "note": self.note}


@dataclass(frozen=True)
class VariableRecord:
    """One registered variable."""

    name: str
    spec_path: Optional[str]                     # "atmosphere.temperature_deviation_c" | None
    unit: str
    jsbsim_writes: Tuple[JsbsimWrite, ...] = ()
    effect_channels: Tuple[EffectChannel, ...] = ()
    null_value: Any = NO_NULL                    # None = the field absent; NO_NULL = no spec null
    null_basis: str = ""
    readback_tolerance: Optional[ReadbackTolerance] = None
    u_input_rule: UInputRule = field(default_factory=UInputRule)
    host_channels: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or "." not in self.name:
            raise ValueError(f"a variable name is dotted: {self.name!r}")
        if not self.unit:
            raise ValueError(f"{self.name}: a variable states its unit")
        if self.spec_path is not None and self.spec_path.count(".") != 1:
            raise ValueError(f"{self.name}: spec_path is section.leaf, not {self.spec_path!r}")
        if self.jsbsim_writes and self.readback_tolerance is None:
            raise ValueError(f"{self.name}: a variable that writes a JSBSim property "
                             f"declares its readback tolerance")
        if self.spec_path is not None and self.null_value is NO_NULL:
            raise RecordError("record.null_value",
                              f"{self.name} is read from spec field {self.spec_path} but "
                              f"registers no null value, so no null pair can be run for it")
        if not self.null_basis:
            raise ValueError(f"{self.name}: the null value (or its absence) states its basis")
        for channel in self.effect_channels:
            if not channel.unit or channel.unit == "?":
                raise RecordError("record.effect_channel_unit",
                                  f"{self.name} registers effect channel {channel.name!r} "
                                  f"with no unit")
            suffix = _suffix_unit(channel.name)
            if suffix != "?" and suffix != channel.unit:
                raise RecordError("record.effect_channel_unit",
                                  f"{self.name} registers effect channel {channel.name!r} as "
                                  f"{channel.unit!r}, but its name says {suffix!r}")

    @property
    def spec_section(self) -> Optional[str]:
        return None if self.spec_path is None else self.spec_path.split(".")[0]

    @property
    def spec_leaf(self) -> Optional[str]:
        return None if self.spec_path is None else self.spec_path.split(".")[1]

    def channel_units(self) -> Dict[str, str]:
        return {c.name: c.unit for c in self.effect_channels}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "spec_path": self.spec_path, "unit": self.unit,
            "jsbsim_writes": [w.to_dict() for w in self.jsbsim_writes],
            "effect_channels": [c.to_dict() for c in self.effect_channels],
            "null_value": None if self.null_value is NO_NULL else self.null_value,
            "has_null_value": self.null_value is not NO_NULL,
            "null_basis": self.null_basis,
            "readback_tolerance": (None if self.readback_tolerance is None
                                   else self.readback_tolerance.to_dict()),
            "u_input_rule": self.u_input_rule.to_dict(),
            "host_channels": list(self.host_channels),
        }


#: P6: two channel names end in ``_s`` for a PER-SECOND unit, which the
#: manifest's suffix table would read as seconds (``_s``): the equivalent
#: roll rate (rad/s) and the shear gradient (1/s). Resolved here first, so
#: the registry's declared unit is what the manifest reports for them and
#: the name never contradicts the unit. (An integration patch adds the two
#: suffixes to the manifest's own table before ``_s``.)
def _suffix_unit(name: str) -> str:
    """The recorder's suffix convention for a channel name, or ``?`` --
    ONE table (core/capture/manifest.py, longest suffix first, so a
    per-second name such as ``_rad_s`` or ``_per_s`` is never read as
    seconds). Imported lazily: the manifest consults this registry first,
    so the two modules meet only inside function bodies."""
    from .capture.manifest import suffix_unit

    return suffix_unit(name)


class Registry:
    """The variable records, keyed by name; refuses a duplicate."""

    def __init__(self, entries: Tuple[VariableRecord, ...] = ()) -> None:
        self._entries: Dict[str, VariableRecord] = {}
        for entry in entries:
            self.register(entry)

    def register(self, entry: VariableRecord) -> VariableRecord:
        if entry.name in self._entries:
            raise ValueError(f"variable {entry.name!r} is already registered")
        for other in self._entries.values():
            if entry.spec_path is not None and other.spec_path == entry.spec_path:
                raise ValueError(f"spec field {entry.spec_path} is claimed by both "
                                 f"{other.name!r} and {entry.name!r}")
        self._entries[entry.name] = entry
        return entry

    def get(self, name: str) -> VariableRecord:
        """The entry, or ``record.unregistered`` by name."""
        try:
            return self._entries[name]
        except KeyError:
            raise RecordError("record.unregistered",
                              f"{name!r} is not a registered variable (registered: "
                              f"{', '.join(self.names())})") from None

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    def __iter__(self) -> Iterator[VariableRecord]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def names(self) -> Tuple[str, ...]:
        return tuple(self._entries)

    def channel_units(self) -> Dict[str, str]:
        """Every registered effect channel's unit, for the manifest's
        ``state_units`` (consulted before the suffix table)."""
        out: Dict[str, str] = {}
        for entry in self._entries.values():
            out.update(entry.channel_units())
        return out

    def host_channels(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for entry in self._entries.values():
            for channel in entry.host_channels:
                if channel not in seen:
                    seen.append(channel)
        return tuple(seen)

    def spec_fields(self) -> Dict[str, str]:
        """{spec_path: variable name} over the entries a spec field states."""
        return {e.spec_path: e.name for e in self._entries.values() if e.spec_path}

    def sections(self) -> Tuple[str, ...]:
        """The spec sections the registry claims; every leaf under one of
        them must be a registered variable."""
        return tuple(sorted({e.spec_section for e in self._entries.values()
                             if e.spec_section}))

    def unregistered_fields(self, data: Mapping[str, Any]) -> List[str]:
        """The ``section.leaf`` paths under a claimed section of a spec's
        dict that no entry claims -- empty when every one is registered
        or the spec states no claimed section."""
        claimed = self.spec_fields()
        out: List[str] = []
        for section in self.sections():
            block = data.get(section)
            if not isinstance(block, Mapping):
                continue
            for leaf in block:
                if f"{section}.{leaf}" not in claimed:
                    out.append(f"{section}.{leaf}")
        return out

    def require_registered(self, data: Mapping[str, Any]) -> None:
        """Refuse ``record.unregistered`` when the spec states a field no
        entry claims."""
        missing = self.unregistered_fields(data)
        if missing:
            raise RecordError("record.unregistered",
                              f"spec field(s) {missing} are under a section the registry "
                              f"claims but no registered variable returns the record for "
                              f"them; register each or drop it")

    def stated_variables(self, data: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
        """{variable name: the spec's provenanced mapping} for every
        registered spec field the dict states."""
        out: Dict[str, Dict[str, Any]] = {}
        for path, name in self.spec_fields().items():
            section, leaf = path.split(".")
            block = data.get(section)
            if isinstance(block, Mapping) and isinstance(block.get(leaf), Mapping):
                out[name] = dict(block[leaf])
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {name: entry.to_dict() for name, entry in self._entries.items()}


def unregistered_fields(data: Mapping[str, Any]) -> List[str]:
    """Module-level form of :meth:`Registry.unregistered_fields` over
    :data:`REGISTRY`, for core/scenario/validate.py."""
    return REGISTRY.unregistered_fields(data)


# -- the physics-wave readbacks, measured here ------------------------------

#: hPa -> lbf/ft^2 (JSBSim's P-sl-psf); 1 hPa = 100 Pa, 1 lbf/ft^2 = 47.880258980336 Pa.
HPA_TO_PSF = 100.0 / 47.880258980336

_EXACT = "measured here on the c172p (JSBSim 1.2.4): the value read back equals the value written to the last bit, before and after stepping"
_RH_REASON = ("measured here on the c172p (JSBSim 1.2.4): atmosphere/RH 0.5 reads back 0.5 before "
              "a step and 0.5000000000505 after three steps (1.0e-10 relative), and the research "
              "session read 0.49999996684 (6.6e-8 relative): a round trip through the Magnus "
              "saturation vapour pressure via dew-point-R; 1e-6 relative covers both readings "
              "with margin and is far below any effect the value has")

_INJECTED = ("measured here on the c172p (JSBSim 1.2.4): a <property> declared by an injected "
             "system reads back the value written to the last bit, before and after stepping "
             "(tests/test_derive_injections.py)")


_GUST_EXACT = ("measured here on the c172p (JSBSim 1.2.4): atmosphere/gust-*-fps holds the value "
               "written to the last bit until written again (7 fps read 7.0 after 11 steps; "
               "0.0 read-back error on every step of a 3 s von Karman run, "
               "tests/test_gust_provider.py); the stack reads each property back before "
               "the next step's write")
_WIND_EXACT = ("measured here on the c172p (JSBSim 1.2.4): atmosphere/wind-*-fps reads back the "
               "value written to the last bit before the next write (0.0 error on every "
               "step of a 3 s layered run, tests/test_shear.py); a uniform wind set once "
               "persists (tests/test_environment.py)")


_ICING_EXACT = ("measured here on the c172p (JSBSim 1.2.4): a <property> declared by an injected "
                "system reads back the value written to the last bit, before and after stepping "
                "(P2); the icing provider reads each of its eight properties back at the top of "
                "the following step, before that step's write, and the largest error over a 3 s "
                "run is 0.0 (tests/test_icing.py)")
_ICING_WRITES = (
    JsbsimWrite("icing/eta", "0 before the trim (the trim is of the un-iced aircraft); eta(t) at "
                             "the top of every step from the run's first step"),
    JsbsimWrite("icing/lift-factor", "1.0 before the trim; 1 + eta(t) k_lift at the top of every step"),
    JsbsimWrite("icing/drag-factor", "1.0 before the trim; 1 + eta(t) k_drag at the top of every step"),
    JsbsimWrite("icing/pitch-factor", "1.0 before the trim; 1 + eta(t) k_pitch at the top of every step"),
    JsbsimWrite("icing/roll-factor", "1.0 before the trim; 1 + eta(t) k_roll at the top of every step"),
    JsbsimWrite("icing/yaw-factor", "1.0 before the trim; 1 + eta(t) k_yaw at the top of every step"),
    JsbsimWrite("icing/side-factor", "1.0 before the trim; 1 + eta(t) k_side at the top of every step"),
    JsbsimWrite("icing/alpha-shift-rad", "0 before the trim; radians(alpha_shift_deg) eta(t) / eta_max "
                                         "at the top of every step"),
)
_ICING_ETA_CHANNELS = (
    EffectChannel("icing_eta", "1"), EffectChannel("icing_lift_factor", "1"),
    EffectChannel("icing_drag_factor", "1"), EffectChannel("lift_n", "N"),
    EffectChannel("drag_n", "N"), EffectChannel("altitude_m", "m"),
    EffectChannel("pitch_deg", "deg"), EffectChannel("tas_kt", "kt"),
)


def _icing_factor(axis: str, channels: Tuple[Tuple[str, str], ...], null_basis: str) -> VariableRecord:
    """One of P2's six icing factors (P5 writes it every step): no spec
    field of its own -- the airframe's k-table and the eta the spec states
    decide it -- so the producer's pre-trim measurement is its null test."""
    return VariableRecord(
        name=f"icing.{axis}_factor", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite(f"icing/{axis}-factor",
                                   f"1.0 before the trim; 1 + eta(t) k_{axis} at the top of every step"),),
        effect_channels=(EffectChannel(f"icing_{axis}_factor", "1"),)
                        + tuple(EffectChannel(c, u) for c, u in channels),
        null_basis=null_basis,
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(note="derived from eta and the airframe's k (a transcription "
                                     "[unverified here] or a named proxy): no spread is declared "
                                     "for k; eta's bin rides on icing.eta"),
        host_channels=(f"icing_{axis}_factor",))


def _injected(name: str, prop: str, unit: str, null_basis: str,
              channels: Tuple[Tuple[str, str], ...], host: Tuple[str, ...]) -> VariableRecord:
    """A P2 injection property (core/control/derive.py): written after load
    and held by the property store; no spec field until its physics item
    lands (P3 failures, P5 icing, P6/P7 gust), so no section is claimed and
    the producer measures the null test."""
    return VariableRecord(
        name=name, spec_path=None, unit=unit,
        jsbsim_writes=(JsbsimWrite(prop, "after load; held by the property store every step"),),
        effect_channels=tuple(EffectChannel(c, u) for c, u in channels),
        null_basis=null_basis,
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _INJECTED),
        u_input_rule=UInputRule(note="no vocabulary until the block lands; the neutral default "
                                     "has no spread"),
        host_channels=host)


_WAKE_EXACT = ("measured here on the c172p derived with the gust_rotation injection (JSBSim "
               "1.2.4): atmosphere/gust-*-fps and gust/p-equivalent-rad_sec read back the value "
               "written to the last bit before the next step's write on every step of a 4 s "
               "wake encounter (max |error| 0.0 on all four properties, tests/test_wake.py); "
               "the stack reads each back before it writes")
_WAKE_WRITES = (
    JsbsimWrite("atmosphere/gust-north-fps", "every step, zero included (the stack's summed gust)"),
    JsbsimWrite("atmosphere/gust-east-fps", "every step, zero included (the stack's summed gust)"),
    JsbsimWrite("atmosphere/gust-down-fps", "every step, zero included (the stack's summed gust)"),
    JsbsimWrite("gust/p-equivalent-rad_sec", "every step (the airframe is derived with the "
                                             "gust_rotation injection when a generator is stated)"),
)


def _wake(leaf: str, spec_path: str, unit: str, null_value: Any, null_basis: str,
          channels: Tuple[Tuple[str, str], ...], note: str) -> VariableRecord:
    """One P7 wake field: every field drives the same four writes (the
    pair's field is one function of them all), read back exact; the
    effect channels are recorded columns of every run."""
    return VariableRecord(
        name=f"wake.{leaf}", spec_path=spec_path, unit=unit,
        jsbsim_writes=_WAKE_WRITES,
        effect_channels=tuple(EffectChannel(c, u) for c, u in channels),
        null_value=null_value, null_basis=null_basis,
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _WAKE_EXACT),
        u_input_rule=UInputRule(note=note),
        host_channels=tuple(c for c, _ in channels if c.startswith("wake_")))


REGISTRY = Registry((
    # -- batch 1: observers and derived quantities (no spec field) ----------
    VariableRecord(
        name="scene.geoid_undulation_m", spec_path=None, unit="m",
        null_basis="no spec field: the producer's null test compares N at the origin "
                   "against 0 (the branch before the datum block)",
        u_input_rule=UInputRule(note="derived from the committed grid; u_x is the "
                                     "grid's bilinear bound 1.152 m, stated in the record")),
    VariableRecord(
        name="limits.monitor", spec_path=None, unit="g | kt CAS | Mach | deg (per key)",
        # INT-final: the flag columns carry the _flag suffix (exceed_* and
        # any_exceedance before; core/telemetry/limits.py FLAG_RENAMES).
        effect_channels=(EffectChannel("nz_pos_flag", "1"), EffectChannel("nz_neg_flag", "1"),
                         EffectChannel("vne_or_vmo_flag", "1"), EffectChannel("mmo_flag", "1"),
                         EffectChannel("alpha_stall_flag", "1"),
                         EffectChannel("any_exceedance_flag", "1")),
        null_basis="no spec field: an observer; the producer's null test offsets the run's "
                   "own samples across the probe limit",
        host_channels=("nz_pos_flag", "nz_neg_flag", "vne_or_vmo_flag", "mmo_flag",
                       "alpha_stall_flag", "any_exceedance_flag")),
    VariableRecord(
        name="instruments.profile", spec_path=None, unit="profile",
        null_basis="no spec field (a CLI option until the instruments block lands): the "
                   "producer's null test is the normalised residual against the ideal profile"),
    VariableRecord(
        name="scene.landcover", spec_path=None, unit="WorldCover legend class",
        null_basis="no spec field: derived from the bake; the producer's null test compares "
                   "the dominant fraction against the uniform prior"),
    # -- the physics wave: the atmosphere block (spec fields land with P1) ----
    VariableRecord(
        name="atmosphere.temperature_deviation_c",
        spec_path="atmosphere.temperature_deviation_c", unit="degC",
        jsbsim_writes=(JsbsimWrite("atmosphere/delta-T", "before trim and every step"),),
        effect_channels=(EffectChannel("density_altitude_m", "m"),
                         EffectChannel("temperature_k", "K"), EffectChannel("tas_kt", "kt")),
        null_value=0.0,
        null_basis="ISA: delta-T 0 is the standard atmosphere JSBSim starts from",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _EXACT),
        u_input_rule=UInputRule(bin_width=10.0, declared_spread=0.0,
                                note="the vocabulary words sit ISA / +15 / +20 / +30 / -40 degC "
                                     "apart; b = 10 degC is twice the half-gap between the two "
                                     "closest words (a stated choice); the default ISA has no spread"),
        host_channels=("density_altitude_m", "temperature_k")),
    VariableRecord(
        name="atmosphere.sea_level_pressure_hpa",
        spec_path="atmosphere.sea_level_pressure_hpa", unit="hPa",
        jsbsim_writes=(JsbsimWrite("atmosphere/P-sl-psf", "before trim and every step"),),
        effect_channels=(EffectChannel("pressure_altitude_m", "m"),
                         EffectChannel("density_altitude_m", "m"),
                         EffectChannel("pressure_hpa", "hPa")),
        null_value=1013.25,
        null_basis="ISA sea-level pressure 1013.25 hPa (2116.22 psf), JSBSim's default",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _EXACT + " (the value is written in psf: hPa x HPA_TO_PSF)"),
        u_input_rule=UInputRule(bin_width=None, declared_spread=0.0,
                                note="no pressure vocabulary: an inferred value has no bin and "
                                     "u_input refuses to guess; the default ISA has no spread"),
        host_channels=("pressure_altitude_m",)),
    VariableRecord(
        name="atmosphere.dew_point_c", spec_path="atmosphere.dew_point_c", unit="degC",
        jsbsim_writes=(JsbsimWrite("atmosphere/dew-point-R", "before trim and every step"),),
        effect_channels=(EffectChannel("rh_pct", "%"), EffectChannel("vapour_pressure_pa", "Pa"),
                         EffectChannel("density_altitude_m", "m")),
        null_value=None,
        null_basis="the field absent: dry air (JSBSim's default, RH 0 measured in "
                   "phase3_facts)",
        readback_tolerance=ReadbackTolerance(1e-6, "relative",
                                             "dew-point-R is JSBSim's own input property; the "
                                             "RH round trip measured 1.0e-10 here, and the "
                                             "same 1e-6 bound is applied until measured "
                                             "separately (stated, not measured)"),
        u_input_rule=UInputRule(bin_width=None, declared_spread=0.0,
                                note="'humid' is the one vocabulary word and maps to relative "
                                     "humidity, not a dew point; no bin here"),
        host_channels=("rh_pct", "vapour_pressure_pa")),
    VariableRecord(
        name="atmosphere.relative_humidity_pct",
        spec_path="atmosphere.relative_humidity_pct", unit="%",
        jsbsim_writes=(JsbsimWrite("atmosphere/RH", "before trim and every step"),),
        effect_channels=(EffectChannel("rh_pct", "%"), EffectChannel("vapour_pressure_pa", "Pa"),
                         EffectChannel("density_altitude_m", "m")),
        null_value=0.0,
        null_basis="dry air: RH 0 is JSBSim's default (measured in phase3_facts)",
        readback_tolerance=ReadbackTolerance(1e-6, "relative", _RH_REASON),
        u_input_rule=UInputRule(bin_width=20.0, declared_spread=0.0,
                                note="'humid' is one word covering the upper range; b = 20 % "
                                     "is a stated choice for the bin it names; default dry has "
                                     "no spread"),
        host_channels=("rh_pct", "vapour_pressure_pa")),
    # The day WORD is the fifth field of the block: a stated choice that the
    # provider expands into the numeric fields above (the spec dict keeps
    # those at their defaults, so the word is the variable that moved).
    # Its writes and read-backs are the expanded fields' own records.
    VariableRecord(
        name="atmosphere.day", spec_path="atmosphere.day", unit="word",
        effect_channels=(EffectChannel("density_altitude_m", "m"),
                         EffectChannel("temperature_k", "K"), EffectChannel("rh_pct", "%")),
        null_value="isa",
        null_basis="the standard day: 'isa' expands to no deviation, JSBSim's own atmosphere",
        u_input_rule=UInputRule(bin_width=None, declared_spread=0.0,
                                note="a word carries no bin of its own: the prompt route infers "
                                     "the numeric field a word names (with that field's bin), "
                                     "never the word; a user's word has u_x 0 and the default "
                                     "is the standard day"),
        host_channels=("density_altitude_m",)),
    # -- P2: the XML injections. Each writes one property an injected system
    #    declares; the spec fields land with P3 (failures), P5 (icing) and
    #    P6/P7 (gust), so no section is claimed yet and the null tests are the
    #    producer's (tests/test_derive_injections.py, measured on the c172p).
    _injected("failures.elevator_authority", "failure/elevator/authority", "1",
              "1.0 is full authority: the chain is x * 1.0, bit-identical to the stock airframe",
              (("pitch_deg", "deg"),), ("pitch_deg",)),
    _injected("failures.aileron_authority", "failure/aileron/authority", "1",
              "1.0 is full authority: the chain is x * 1.0, bit-identical to the stock airframe",
              (("roll_deg", "deg"),), ("roll_deg",)),
    _injected("failures.rudder_authority", "failure/rudder/authority", "1",
              "1.0 is full authority: the chain is x * 1.0, bit-identical to the stock airframe",
              (("beta_deg", "deg"),), ("beta_deg",)),
    # -- P5: the icing block gives P2's icing.* injected properties their
    #    spec fields. eta_max (the number, or the severity WORD's stated
    #    value) drives every write: icing/eta and the six factors 1 + eta k
    #    (Bragg et al. 2000, the airframe's k-table from its config) at the
    #    top of every step, neutral before the trim; the six factors have
    #    no spec field of their own (the k-table is the airframe's, the
    #    variable that moves is eta) and keep the producer's measured null
    #    tests. Effect channels are recorded columns: the provider's own
    #    icing_* columns (unit 1, the shift in degrees) beside the axis's
    #    force / moment / attitude columns (core/telemetry/recorder.py).
    _icing_factor("lift", (("lift_n", "N"), ("altitude_m", "m"), ("tas_kt", "kt")),
                  "1.0 scales the LIFT axis by one: bit-identical to the stock airframe (0.8 read "
                  "1872.5287 -> 1498.0230 lbf, P2); the provider writes 1 + eta k_lift"),
    _icing_factor("drag", (("drag_n", "N"), ("tas_kt", "kt"), ("altitude_m", "m")),
                  "1.0 scales the DRAG axis by one: bit-identical to the stock airframe; the "
                  "provider writes 1 + eta k_drag"),
    _icing_factor("side", (("side_force_n", "N"), ("beta_deg", "deg")),
                  "1.0 scales the SIDE axis by one: bit-identical to the stock airframe; the "
                  "provider writes 1 + eta k_side (the axis is near zero at symmetric initial "
                  "conditions, so the pre-trim measurement is honestly not reached there)"),
    _icing_factor("roll", (("roll_deg", "deg"), ("roll_rate_dps", "deg/s")),
                  "1.0 scales the ROLL axis by one: bit-identical to the stock airframe; the "
                  "provider writes 1 + eta k_roll"),
    _icing_factor("pitch", (("pitch_deg", "deg"), ("pitch_rate_dps", "deg/s"),
                            ("altitude_m", "m")),
                  "1.0 scales the PITCH axis by one: bit-identical to the stock airframe; the "
                  "provider writes 1 + eta k_pitch"),
    _icing_factor("yaw", (("beta_deg", "deg"), ("heading_deg", "deg")),
                  "1.0 scales the YAW axis by one: bit-identical to the stock airframe; the "
                  "provider writes 1 + eta k_yaw"),
    VariableRecord(
        name="icing.eta", spec_path="icing.eta_max", unit="1",
        jsbsim_writes=_ICING_WRITES,
        effect_channels=_ICING_ETA_CHANNELS,
        null_value=0.0,
        null_basis="no ice: eta 0 writes every factor 1.0 and the shift 0, and the derived "
                   "airframe is then bit-identical to the stock one (P2, measured over 8 s); "
                   "the pair 0.2 against 0 on the c172p (proxy row) moves lift_n on the first "
                   "step by the factor and diverges the trimmed flight (tests/test_icing.py)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(bin_width=0.1, declared_spread=0.0,
                                note="the severity words sit 0.05 / 0.10 / 0.20 / 0.30 apart; "
                                     "b = 0.1 is the gap between the two upper words (a stated "
                                     "choice) for a word-inferred eta; a stated number has u_x 0; "
                                     "the default (no ice) has no spread"),
        host_channels=("icing_eta", "icing_lift_factor", "icing_drag_factor",
                       "icing_pitch_factor", "icing_roll_factor", "icing_yaw_factor",
                       "icing_side_factor")),
    VariableRecord(
        name="icing.severity", spec_path="icing.severity", unit="word",
        jsbsim_writes=_ICING_WRITES,
        effect_channels=_ICING_ETA_CHANNELS,
        null_value=None,
        null_basis="unstated: no severity word; eta_max is then the stated number or 0 (no ice). "
                   "The word is a stated mapping to eta (trace 0.05, light 0.10, moderate 0.20, "
                   "severe 0.30); a stated number beside it wins, so the word's pair is then "
                   "silent by construction (said in the record)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(note="a word carries no bin of its own: the eta it maps to "
                                     "carries the 0.1 bin; the AIM pilot-report words are not "
                                     "values of eta"),
        host_channels=("icing_eta",)),
    VariableRecord(
        name="icing.onset_s", spec_path="icing.onset_s", unit="s",
        jsbsim_writes=(JsbsimWrite("icing/eta", "eta(t) at the top of every step, 0 while t < onset_s "
                                                "on the run clock"),),
        effect_channels=(EffectChannel("icing_eta", "1"), EffectChannel("lift_n", "N"),
                         EffectChannel("altitude_m", "m"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("tas_kt", "kt")),
        null_value=0.0,
        null_basis="the run's first step: eta rises from t = 0 (the spec default); a later onset "
                   "keeps the flight clean until then, so the pair against 0 moves the channels "
                   "over the steps before the onset",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(note="a stated time: u_x 0; a sampled one is the draw"),
        host_channels=("icing_eta",)),
    VariableRecord(
        name="icing.ramp_s", spec_path="icing.ramp_s", unit="s",
        jsbsim_writes=(JsbsimWrite("icing/eta", "eta(t) at the top of every step, rising linearly "
                                                "over ramp_s from the onset"),),
        effect_channels=(EffectChannel("icing_eta", "1"), EffectChannel("lift_n", "N"),
                         EffectChannel("altitude_m", "m"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("tas_kt", "kt")),
        null_value=0.0,
        null_basis="a step: ramp 0 puts eta at eta_max on the first step at or past the onset "
                   "(the spec default); a ramp spreads the rise over its seconds",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(note="a stated duration: u_x 0"),
        host_channels=("icing_eta",)),
    VariableRecord(
        name="icing.alpha_shift_rad", spec_path="icing.alpha_shift_deg", unit="rad",
        jsbsim_writes=(JsbsimWrite("icing/alpha-shift-rad",
                                   "0 before the trim; radians(alpha_shift_deg) eta(t) / eta_max at "
                                   "the top of every step"),),
        effect_channels=(EffectChannel("icing_alpha_shift_deg", "deg"),
                         EffectChannel("alpha_deg", "deg"), EffectChannel("lift_n", "N"),
                         EffectChannel("altitude_m", "m"), EffectChannel("pitch_deg", "deg")),
        null_value=0.0,
        null_basis="0 leaves the LIFT table's alpha as aero/alpha-rad: bit-identical (P2: 2 deg "
                   "moved the lift peak -2.0 deg in a static sweep); the spec states degrees, the "
                   "property is radians, and the cue is linear in eta (the full shift at eta_max)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _ICING_EXACT),
        u_input_rule=UInputRule(note="a stated cue: u_x 0; no vocabulary"),
        host_channels=("icing_alpha_shift_deg",)),
    VariableRecord(
        name="icing.envelope", spec_path="icing.envelope", unit="word",
        effect_channels=(EffectChannel("icing_eta", "1"), EffectChannel("lift_n", "N")),
        null_value=None,
        null_basis="unstated: no envelope named. The word (Part 25 Appendix C or O) is recorded "
                   "as metadata and applied nowhere, so its pair is silent by construction and "
                   "the record says so (a bounded invariance, like the datum words)",
        u_input_rule=UInputRule(note="a word: no bin, no spread; it enters no equation"),
        host_channels=()),
    _injected("gust.p_equivalent_rad_s", "gust/p-equivalent-rad_sec", "rad/s",
              "0 adds nothing to the roll-damping term: bit-identical (0.3 rad/s for 2 s rolled -30.21 vs -3.67 deg)",
              (("roll_deg", "deg"), ("roll_rate_dps", "deg/s")), ("roll_deg", "roll_rate_dps")),
    # -- P6: the turbulence model and the wind profile blocks. The model and
    #    kind WORDS are the variables that moved (dryden / uniform are the
    #    branch as built); the von Karman field writes the gust channel
    #    every step (read back exact: the channel persists to the bit,
    #    measured), the profiles write the wind channel every step (read
    #    back exact). Effect channels are recorded columns (lesson b):
    #    the gust channel as JSBSim holds it, the aircraft's altitude and
    #    roll; the profile's delivered speed (JSBSim's wind-*-fps), its
    #    gradient and layer index (the stack's own columns; the index has
    #    no floor and is reported, not graded).
    VariableRecord(
        name="turbulence_model.model", spec_path="turbulence_model.model", unit="word",
        jsbsim_writes=(JsbsimWrite("atmosphere/gust-north-fps", "every step, zero included (the channel persists)"),
                       JsbsimWrite("atmosphere/gust-east-fps", "every step, zero included (the channel persists)"),
                       JsbsimWrite("atmosphere/gust-down-fps", "every step, zero included (the channel persists)"),
                       JsbsimWrite("gust/p-equivalent-rad_sec", "every step where the derived airframe declares it")),
        effect_channels=(EffectChannel("gust_north_mps", "m/s"), EffectChannel("gust_east_mps", "m/s"),
                         EffectChannel("gust_down_mps", "m/s"),
                         EffectChannel("gust_p_equivalent_rad_s", "rad/s"),
                         EffectChannel("altitude_m", "m"), EffectChannel("roll_deg", "deg")),
        null_value="dryden",
        null_basis="today's path: JSBSim's own Dryden filters at the environment's turbulence "
                   "word; the gust channel then reads 0 every step (measured)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _GUST_EXACT),
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("gust_north_mps", "gust_east_mps", "gust_down_mps", "gust_p_equivalent_rad_s")),
    VariableRecord(
        name="turbulence_model.intensity", spec_path="turbulence_model.intensity",
        unit="W20 kt | word",
        effect_channels=(EffectChannel("gust_north_mps", "m/s"), EffectChannel("gust_east_mps", "m/s"),
                         EffectChannel("gust_down_mps", "m/s"), EffectChannel("altitude_m", "m"),
                         EffectChannel("roll_deg", "deg")),
        null_value=None,
        null_basis="unstated: the environment's turbulence word applies to the named model "
                   "(the field only replaces that word)",
        u_input_rule=UInputRule(bin_width=15.0, declared_spread=0.0,
                                note="the words sit 15 kt of W20 apart (light 15, moderate 30, "
                                     "severe 45): b = 15 kt is the gap (a stated choice); a "
                                     "numeric W20 has u_x 0"),
        host_channels=("gust_north_mps", "gust_east_mps", "gust_down_mps")),
    VariableRecord(
        name="turbulence_model.seed", spec_path="turbulence_model.seed", unit="1",
        effect_channels=(EffectChannel("gust_north_mps", "m/s"), EffectChannel("gust_east_mps", "m/s"),
                         EffectChannel("gust_down_mps", "m/s"), EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: the run's seed applies (the von Karman phases through the "
                   "'von_karman' stream, the Dryden process through JSBSim's randomseed)",
        u_input_rule=UInputRule(note="a seed has no spread: another seed is another realisation, "
                                     "not an uncertainty"),
        host_channels=()),
    VariableRecord(
        name="wind_profile.kind", spec_path="wind_profile.kind", unit="word",
        jsbsim_writes=(JsbsimWrite("atmosphere/wind-north-fps", "before trim (at the initial altitude) and every step"),
                       JsbsimWrite("atmosphere/wind-east-fps", "before trim (at the initial altitude) and every step"),
                       JsbsimWrite("atmosphere/wind-down-fps", "before trim (at the initial altitude) and every step")),
        effect_channels=(EffectChannel("wind_profile_speed_mps", "m/s"),
                         EffectChannel("shear_dv_dz_per_s", "1/s"),
                         EffectChannel("wind_layer_index", "1"),
                         EffectChannel("altitude_m", "m")),
        null_value="uniform",
        null_basis="today's path: the spec's wind everywhere (or the surface class's log "
                   "profile); the layer index and the gradient then read 0",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _WIND_EXACT),
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("wind_profile_speed_mps", "wind_layer_index", "shear_dv_dz_per_s")),
    VariableRecord(
        name="wind_profile.layers", spec_path="wind_profile.layers", unit="[m, kt, deg]",
        effect_channels=(EffectChannel("wind_profile_speed_mps", "m/s"),
                         EffectChannel("shear_dv_dz_per_s", "1/s"),
                         EffectChannel("wind_layer_index", "1")),
        null_value=None,
        null_basis="unstated: no layers (the kind is then not layered; a layered kind without "
                   "layers refuses wind_profile.layers)",
        u_input_rule=UInputRule(note="a stated list: u_x 0 unless a tolerance is stated"),
        host_channels=("wind_profile_speed_mps",)),
    VariableRecord(
        name="wind_profile.roughness_ft", spec_path="wind_profile.roughness_ft", unit="ft",
        effect_channels=(EffectChannel("wind_profile_speed_mps", "m/s"),
                         EffectChannel("shear_dv_dz_per_s", "1/s")),
        null_value=None,
        null_basis="unstated: the milspec z0 of 0.15 ft (the specification's Category C "
                   "value) is used when the kind is milspec",
        u_input_rule=UInputRule(note="the specification states two discrete values (0.15 or "
                                     "2.0 ft), not a distribution: no bin, no spread"),
        host_channels=("wind_profile_speed_mps",)),
    VariableRecord(
        name="wind_profile.fixture", spec_path="wind_profile.fixture", unit="name",
        effect_channels=(EffectChannel("wind_profile_speed_mps", "m/s"),
                         EffectChannel("wind_layer_index", "1")),
        null_value=None,
        null_basis="unstated: no cached profile (the kind is then not nwp; an nwp kind "
                   "without a fixture refuses weather.fixture_missing)",
        u_input_rule=UInputRule(note="a file name: no bin, no spread; the profile's own "
                                     "uncertainty is the model's, not carried"),
        host_channels=("wind_profile_speed_mps",)),
    # -- D1: the datum block (spec fields land with D1). The three words
    # declare and check; the applied variable is scene.geoid_undulation_m
    # (its record carries the channels' readback), so a pair on any of them
    # is the bounded invariance experiments/datum_null_test.py measures:
    # the recorded columns are identical, the channels are recorded either
    # way (0 where no geoid applies, by the frame's definition).
    VariableRecord(
        name="datum.vertical", spec_path="datum.vertical", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value="orthometric",
        null_basis="the heights as built: orthometric numbers in JSBSim's ellipsoidal slot; "
                   "'ellipsoidal' is refused by name (datum.physics_frame_unsupported), so no "
                   "pair can fly it",
        u_input_rule=UInputRule(note="a word: no bin, no spread; the datum's uncertainty is "
                                     "the geoid model's declared u_model_m on the applied record"),
        host_channels=("undulation_m", "hae_m")),
    VariableRecord(
        name="datum.physics_frame", spec_path="datum.physics_frame", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value="orthometric",
        null_basis="the frame as built (C2); 'ellipsoid' (C3) is refused by name until the "
                   "physics frame handles it",
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("undulation_m", "hae_m")),
    VariableRecord(
        name="datum.geoid_model", spec_path="datum.geoid_model", unit="word",
        effect_channels=(EffectChannel("undulation_m", "m"), EffectChannel("hae_m", "m")),
        null_value=None,
        null_basis="unstated: the bake's own model is accepted; a stated model is checked "
                   "against the bake's (datum.model_mismatch) and moves no channel -- the "
                   "pair is the bounded invariance (digests identical, measured)",
        u_input_rule=UInputRule(note="a word: no bin, no spread; the model's declared "
                                     "u_model_m rides on the applied record"),
        host_channels=("undulation_m", "hae_m")),
    # -- W1: the environment section. Registering environment.surface (the
    #    roughness inference's spec field) claims the whole section, so every
    #    spec-8 field of it is registered here with its default as the null.
    #    The five others are pre-existing fields whose providers' writes are
    #    recorded in the environment provenance, not here; they are
    #    registered so the validator's record.unregistered check passes for
    #    every spec and so a null pair can be run for each. Every effect
    #    channel is a recorded column (measured on a real run's
    #    telemetry.columns, tests/test_surface_inference.py).
    VariableRecord(
        name="environment.wind_speed", spec_path="environment.wind_speed", unit="kt",
        effect_channels=(EffectChannel("wind_speed_mps", "m/s"), EffectChannel("lat_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value=0.0,
        null_basis="still air: the spec default (0 kt attaches no wind provider); the pair "
                   "of 10 kt against still air moves wind_speed_mps by 5.14 m/s and altitude "
                   "by 0.80 m on the c172p (tests/test_record_null.py)",
        u_input_rule=UInputRule(bin_width=10.0, declared_spread=0.0,
                                note="the strength words sit 0 / 8 / 15 / 25 / 40 kt apart; "
                                     "b = 10 kt is the median step (a stated choice); the "
                                     "default still air has no spread"),
        host_channels=("wind_speed_mps",)),
    VariableRecord(
        name="environment.wind_direction", spec_path="environment.wind_direction", unit="deg",
        effect_channels=(EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s")),
        null_value=0.0,
        null_basis="the spec default 0 deg (from the north); with a stated speed the "
                   "components move, in still air nothing does and no pair is run",
        u_input_rule=UInputRule(note="no direction bin: a compass word is not a bin this "
                                     "registry states"),
        host_channels=("wind_north_mps", "wind_east_mps")),
    VariableRecord(
        name="environment.turbulence", spec_path="environment.turbulence", unit="word",
        effect_channels=(EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s"),
                         EffectChannel("wind_down_mps", "m/s")),
        null_value="none",
        null_basis="'none': JSBSim turb-type 0, the spec default (the Gate 3 null ladder "
                   "measured the intensity words against it)",
        u_input_rule=UInputRule(note="a word: no bin, no spread; the intensity word maps to "
                                     "a MIL-F-8785C W20 the provider records"),
        host_channels=("wind_north_mps", "wind_east_mps", "wind_down_mps")),
    VariableRecord(
        name="environment.surface", spec_path="environment.surface", unit="word",
        jsbsim_writes=(JsbsimWrite("atmosphere/wind-north-fps",
                                   "every step (the stack's summed wind)"),
                       JsbsimWrite("atmosphere/wind-east-fps",
                                   "every step (the stack's summed wind)"),
                       JsbsimWrite("atmosphere/wind-down-fps",
                                   "every step (the stack's summed wind)")),
        effect_channels=(EffectChannel("wind_speed_mps", "m/s"),
                         EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s")),
        null_value="unspecified",
        null_basis="the unstated default word: no surface coupling, the steady wind; the "
                   "pair measured on the c172p at 50 m AGL in 15 kt (inferred 'forest' "
                   "against 'unspecified') moves wind_speed_mps by 2.424 m/s = 4.71 kt "
                   "(tests/test_surface_inference.py)",
        readback_tolerance=ReadbackTolerance(
            0.0, "absolute",
            "measured here on the trimmed c172p (JSBSim 1.2.4): atmosphere/wind-north-fps, "
            "-east-fps and -down-fps written 12.5 read back 12.5 before and after three "
            "steps, total-wind 12.5 with no turbulence (tests/test_surface_inference.py)"),
        u_input_rule=UInputRule(note="a word: no bin, no spread; the class's z0 is a table "
                                     "row (Stull 1988 Table 9-6), its own uncertainty not "
                                     "stated"),
        host_channels=("wind_speed_mps",)),
    VariableRecord(
        name="environment.weather_date", spec_path="environment.weather_date", unit="word",
        effect_channels=(EffectChannel("wind_speed_mps", "m/s"),
                         EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s")),
        null_value="none",
        null_basis="'none': no historical weather, the spec's own wind (the default word; "
                   "an ERA5 date needs the network, blocked here, so no pair is measured "
                   "in this container)",
        u_input_rule=UInputRule(note="an ISO date or 'none': no bin, no spread")),
    # -- P4: the loading block. payload is a mapping {station: kg} (one
    #    field, one entry: the record's value is the mapping and its
    #    parameters carry each station's write and read-back); the fuel is
    #    a mass or a fraction of capacity. Every write is made ONCE before
    #    the trim; the read-back that grades the payload is JSBSim's cg-x-in
    #    against the hand CG (V13, 0.1 in; measured 1e-12 in on five
    #    airframes), the tank contents read back exact. Effect channels are
    #    recorded columns (lesson b): cg_x_m, iyy_kgm2 and weight_kg (P4's
    #    two new channels and the existing gross mass), the trimmed elevator
    #    (the runner's SURFACES column), pitch and altitude.
    VariableRecord(
        name="loading.payload_kg", spec_path="loading.payload", unit="kg per station",
        jsbsim_writes=(JsbsimWrite("inertia/pointmass-weight-lbs[i]",
                                   "once, before the trim (after the atmosphere writes)"),),
        effect_channels=(EffectChannel("cg_x_m", "m"), EffectChannel("iyy_kgm2", "kg m^2"),
                         EffectChannel("weight_kg", "kg"), EffectChannel("elevator_deg", "deg"),
                         EffectChannel("pitch_deg", "deg"), EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: the XML's own point-mass weights stand (the c172p's 180 lb "
                   "pilot, its four empty seats and baggage); the pair of 136 kg at the "
                   "aft-most seat (70 in) against the XML loading moves cg_x_m by 0.0974 m, "
                   "the trimmed elevator by 0.223 deg, pitch by 0.548 deg and weight_kg by "
                   "136 kg on the c172p at 1500 m / 100 kt (tests/test_loading.py)",
        readback_tolerance=ReadbackTolerance(
            0.1, "absolute",
            "V13: inertia/cg-x-in read back after the station writes and a re-latch of the "
            "initial conditions against the hand CG over the XML's own arms, in inches; "
            "measured 1e-12 in on the c172p, A320, B747, DHC6 and p51d (the property store "
            "itself returns each pointmass-weight-lbs[i] to the bit: 300 -> 300.0); the "
            "tolerance is the blueprint's"),
        u_input_rule=UInputRule(note="a stated mass per station: u_x 0 unless a tolerance "
                                     "is stated; no vocabulary"),
        host_channels=("cg_x_m", "iyy_kgm2")),
    VariableRecord(
        name="loading.fuel_kg", spec_path="loading.fuel_kg", unit="kg",
        jsbsim_writes=(JsbsimWrite("propulsion/tank[i]/contents-lbs",
                                   "once, before the trim (after the atmosphere writes)"),),
        effect_channels=(EffectChannel("weight_kg", "kg"), EffectChannel("cg_x_m", "m"),
                         EffectChannel("iyy_kgm2", "kg m^2"), EffectChannel("elevator_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: the XML's own tank contents stand (the c172p's 2 x 100 lb); "
                   "the mass is shared between the tanks in proportion to capacity",
        readback_tolerance=ReadbackTolerance(
            0.0, "absolute",
            "measured here on the c172p and A320 (JSBSim 1.2.4): propulsion/tank[i]/contents-lbs "
            "reads back the value written to the last bit before the engine start (130.0 -> "
            "130.0, 19500.0 -> 19500.0); the crank then burns 0.0055 lb on the c172p before "
            "the trim, recorded separately and not graded"),
        u_input_rule=UInputRule(note="a stated mass: u_x 0 unless a tolerance is stated"),
        host_channels=("weight_kg", "cg_x_m")),
    VariableRecord(
        name="loading.fuel_fraction", spec_path="loading.fuel_fraction", unit="1",
        jsbsim_writes=(JsbsimWrite("propulsion/tank[i]/contents-lbs",
                                   "once, before the trim (after the atmosphere writes)"),),
        effect_channels=(EffectChannel("weight_kg", "kg"), EffectChannel("cg_x_m", "m"),
                         EffectChannel("iyy_kgm2", "kg m^2"), EffectChannel("elevator_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: the XML's own tank contents stand (the c172p's 200 of 370 lb, "
                   "0.54 of capacity); full against that moves weight_kg by 77.1 kg, cg_x_m "
                   "by 0.0292 m and the trimmed elevator by 0.183 deg on the c172p "
                   "(tests/test_loading.py)",
        readback_tolerance=ReadbackTolerance(
            0.0, "absolute",
            "measured here on the c172p and A320 (JSBSim 1.2.4): propulsion/tank[i]/contents-lbs "
            "reads back the value written to the last bit before the engine start; the "
            "fraction is written as fraction x capacity per tank"),
        u_input_rule=UInputRule(note="a stated fraction: u_x 0 unless a tolerance is stated; "
                                     "a sampled one is the draw"),
        host_channels=("weight_kg", "cg_x_m")),
    VariableRecord(
        name="environment.weather_event", spec_path="environment.weather_event", unit="word",
        effect_channels=(EffectChannel("wind_down_mps", "m/s"),
                         EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s")),
        null_value="none",
        null_basis="'none': no severe-weather feature placed, the spec default",
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("wind_down_mps",)),
    # -- P3: the failure schedule. The block has ONE field, the event list,
    #    so failures.events claims the section (null = no events, the
    #    default) and each kind has its own entry with no spec field (the
    #    events are list entries, not leaves), its writes, the read-back
    #    tolerance measured here and the recorded channels it moves
    #    (tests/test_failures.py, tests/test_failures_block.py). Every
    #    channel is a recorded column of every run: failure_state_flag and
    #    engine0_thrust_n through the schedule's recorder extras (every
    #    configured airframe has an engine 0; a turbine's engine<i>_n1_pct
    #    and a piston's engine<i>_rpm are recorded where the airframe has
    #    them and named by the event's record, never invented), the
    #    surfaces through the runner's SURFACES extras.
    VariableRecord(
        name="failures.events", spec_path="failures.events", unit="events",
        effect_channels=(EffectChannel("failure_state_flag", "1"),
                         EffectChannel("altitude_m", "m"), EffectChannel("heading_deg", "deg"),
                         EffectChannel("pitch_deg", "deg"), EffectChannel("tas_kt", "kt")),
        null_value=[],
        null_basis="no events: every engine and surface as the model ships it (the spec "
                   "default); the pair of a schedule against none moves the flag column "
                   "and the flight (hardover on the c172p, engine-out and a jam under "
                   "TECS on the A320: tests/test_failures_block.py)",
        u_input_rule=UInputRule(note="a stated list of events: u_x 0; the times are stated, "
                                     "not sampled"),
        host_channels=("failure_state_flag",)),
    VariableRecord(
        name="failures.engine_out", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite("propulsion/active_engine", "once, at the first step with t >= at_s (set to the engine, then restored to -1)"),
                       JsbsimWrite("propulsion/cutoff_cmd", "once, at the first step with t >= at_s (turbine)"),
                       JsbsimWrite("propulsion/magneto_cmd", "once, at the first step with t >= at_s (piston)")),
        effect_channels=(EffectChannel("altitude_m", "m"), EffectChannel("tas_kt", "kt"),
                         EffectChannel("heading_deg", "deg"),
                         EffectChannel("engine0_thrust_n", "N"),
                         EffectChannel("failure_state_flag", "1")),
        null_basis="no spec field of its own (an event of failures.events): the producer "
                   "measures thrust before the write against thrust once the engine has "
                   "settled (A320 53125 N -> 0 on the next step; c172p 1008 N -> -52 N at 2 s)",
        readback_tolerance=ReadbackTolerance(
            0.0, "absolute",
            "measured here (JSBSim 1.2.4): propulsion/cutoff_cmd read with active_engine set "
            "to the engine reads 1.0 exactly on the next step (A320); magneto_cmd is write-only "
            "(FGPropulsion.cpp L819-L820), so the piston's read-back property is "
            "engine[i]/set-running, which reads 0.0 exactly on the next step (c172p); a bare "
            "set-running 0 relights both engine types on the next step and is not the write"),
        u_input_rule=UInputRule(note="a switch: no bin, no spread"),
        host_channels=("failure_state_flag", "engine0_thrust_n", "engine1_thrust_n",
                       "engine0_n1_pct", "engine1_n1_pct", "engine0_rpm", "engine1_rpm")),
    VariableRecord(
        name="failures.control_jam", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite("failure/<surface>/actuator/malfunction/fail_stuck",
                                   "once, at the first step with t >= at_s"),),
        effect_channels=(EffectChannel("elevator_deg", "deg"), EffectChannel("aileron_deg", "deg"),
                         EffectChannel("rudder_deg", "deg"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("roll_deg", "deg"), EffectChannel("heading_deg", "deg"),
                         EffectChannel("altitude_m", "m"), EffectChannel("failure_state_flag", "1")),
        null_basis="no spec field of its own: the producer measures the hold (max drift 0.0 "
                   "rad over 100 steps on the c172p and the A320) as a bounded test; the "
                   "with/without pair is the schedule's",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _INJECTED),
        u_input_rule=UInputRule(note="a switch: no bin, no spread"),
        host_channels=("elevator_deg", "aileron_deg", "rudder_deg")),
    VariableRecord(
        name="failures.hardover", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite("failure/<surface>/actuator/malfunction/fail_hardover",
                                   "once, at the first step with t >= at_s"),),
        effect_channels=(EffectChannel("elevator_deg", "deg"), EffectChannel("aileron_deg", "deg"),
                         EffectChannel("rudder_deg", "deg"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("roll_deg", "deg"), EffectChannel("heading_deg", "deg"),
                         EffectChannel("altitude_m", "m"), EffectChannel("failure_state_flag", "1")),
        null_basis="no spec field of its own: the producer measures the surface position on "
                   "the step after the write against the step before (c172p elevator 0.0752 "
                   "-> 0.4014 rad)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _INJECTED),
        u_input_rule=UInputRule(note="a switch: no bin, no spread"),
        host_channels=("elevator_deg", "aileron_deg", "rudder_deg")),
    VariableRecord(
        name="failures.float", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite("failure/<surface>/actuator/malfunction/fail_zero",
                                   "once, at the first step with t >= at_s"),),
        effect_channels=(EffectChannel("elevator_deg", "deg"), EffectChannel("aileron_deg", "deg"),
                         EffectChannel("rudder_deg", "deg"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("roll_deg", "deg"), EffectChannel("heading_deg", "deg"),
                         EffectChannel("altitude_m", "m"), EffectChannel("failure_state_flag", "1")),
        null_basis="no spec field of its own: the producer measures the surface position on "
                   "the step after the write against the step before (a zero command floats "
                   "to where it already was and is honestly not reached)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _INJECTED),
        u_input_rule=UInputRule(note="a switch: no bin, no spread"),
        host_channels=("elevator_deg", "aileron_deg", "rudder_deg")),
    VariableRecord(
        name="failures.authority_loss", spec_path=None, unit="1",
        jsbsim_writes=(JsbsimWrite("failure/<surface>/authority",
                                   "once, at the first step with t >= at_s"),),
        effect_channels=(EffectChannel("elevator_deg", "deg"), EffectChannel("aileron_deg", "deg"),
                         EffectChannel("rudder_deg", "deg"), EffectChannel("pitch_deg", "deg"),
                         EffectChannel("roll_deg", "deg"), EffectChannel("heading_deg", "deg"),
                         EffectChannel("altitude_m", "m"), EffectChannel("failure_state_flag", "1")),
        null_basis="no spec field of its own: the producer measures the actuator output on "
                   "the step after the write against the step before (c172p: -0.3 -> -0.15 "
                   "at authority 0.5, held on 100 steps)",
        readback_tolerance=ReadbackTolerance(0.0, "absolute", _INJECTED),
        u_input_rule=UInputRule(note="the remaining authority, stated: u_x 0; no vocabulary"),
        host_channels=("elevator_deg", "aileron_deg", "rudder_deg")),
    # -- D2: the dis block. Six fields that label the Entity State PDU log
    #    the capture writes with --dis; none reaches the flight (measured:
    #    the output digest is the same with and without the block), so the
    #    effect channels are the recorded columns the export READS -- the
    #    pair on any field is a bounded invariance that measures 0 on each
    #    of them, verdict silent, and the record's own null test (the
    #    decoded location with the geoid against without) is the producer's.
    #    Nulls are the block's defaults; the words carry no bin.
    VariableRecord(
        name="dis.site", spec_path="dis.site", unit="1",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value=1,
        null_basis="the documented default entity identifier 1:1:1; the export reads the "
                   "channels and moves none (measured: peak 0 on each, digests equal)",
        u_input_rule=UInputRule(note="an identifier: no bin, no spread")),
    VariableRecord(
        name="dis.application", spec_path="dis.application", unit="1",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value=1,
        null_basis="the documented default entity identifier 1:1:1; moves no recorded column",
        u_input_rule=UInputRule(note="an identifier: no bin, no spread")),
    VariableRecord(
        name="dis.entity", spec_path="dis.entity", unit="1",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value=1,
        null_basis="the documented default entity identifier 1:1:1; moves no recorded column",
        u_input_rule=UInputRule(note="an identifier: no bin, no spread")),
    VariableRecord(
        name="dis.force_id", spec_path="dis.force_id", unit="1",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value=0,
        null_basis="force id 0 (Other), the documented default; moves no recorded column",
        u_input_rule=UInputRule(note="an enumeration: no bin, no spread")),
    VariableRecord(
        name="dis.marking", spec_path="dis.marking", unit="text",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value="",
        null_basis="no marking stated: the airframe key is derived at export (source "
                   "derived); moves no recorded column",
        u_input_rule=UInputRule(note="a text: no bin, no spread")),
    # -- P7: the wake block. The generator WORD is the variable that moved
    #    (null None = no wake, nothing applied); the pair's field goes into
    #    the three gust properties every step through the stack's sum and
    #    its equivalent roll rate into gust/p-equivalent-rad_sec (the own
    #    airframe is derived with the gust_rotation injection when a
    #    generator is stated), each read back exact (measured). Effect
    #    channels are recorded columns of every run (lesson b): the wake's
    #    own columns (the runner's Recorder extras from the provider, 0
    #    without one) beside the gust channel, roll and altitude.
    #    wake_gamma_m2_s (m^2/s, the circulation at the age) is an effect
    #    channel of the six entries whose variable enters it (the speed
    #    through Gamma_0, the model / eps* / N* through the decay, the ages
    #    through the decayed circulation) and of NO other: the generator's
    #    pair moves the column from Gamma_0 to 0 by construction (grading
    #    it would call every generator pair reached, the far-offset control
    #    included), and the offsets do not enter it. Its floor is
    #    record_null.NULL_FLOOR_CIRCULATION_M2_S; the manifest's _m2_s suffix
    #    reads it as a circulation, never seconds.
    _wake("generator", "wake.generator", "word", None,
          "no wake: no generating aircraft, the spec default (nothing derived, nothing "
          "written); the pair of a B747 generator against none on the c172p rolls it past "
          "5 deg and diverges the flight (tests/test_wake.py)",
          (("wake_v_mps", "m/s"), ("wake_w_mps", "m/s"), ("wake_p_eq_rad_s", "rad/s"),
           ("gust_down_mps", "m/s"), ("gust_p_equivalent_rad_s", "rad/s"),
           ("roll_deg", "deg"), ("roll_rate_dps", "deg/s"), ("altitude_m", "m"),
           ("wake_rcr", "1")),
          note="a word: no bin, no spread"),
    _wake("generator_speed_kt", "wake.generator_speed_kt", "kt", None,
          "unstated: the own ship's true airspeed at the initial conditions stands in for the "
          "generator's (a stated choice); Gamma_0 is inversely proportional to it",
          (("wake_gamma_m2_s", "m^2/s"), ("wake_v_mps", "m/s"), ("wake_w_mps", "m/s"),
           ("wake_p_eq_rad_s", "rad/s"), ("roll_deg", "deg")),
          note="a stated speed: u_x 0; no vocabulary"),
    _wake("lateral_offset_m", "wake.lateral_offset_m", "m", 0.0,
          "centred on the pair's centreline (the spec default, 0 m); 300 m against 0 is the "
          "far-offset control that barely moves the aircraft (tests/test_wake.py)",
          (("wake_lateral_m", "m"), ("wake_v_mps", "m/s"), ("wake_w_mps", "m/s"),
           ("wake_p_eq_rad_s", "rad/s"), ("roll_deg", "deg")),
          note="a stated offset: u_x 0; no vocabulary"),
    _wake("vertical_offset_m", "wake.vertical_offset_m", "m", 0.0,
          "at the pair's height (the spec default, 0 m)",
          (("wake_vertical_m", "m"), ("wake_v_mps", "m/s"), ("wake_w_mps", "m/s"),
           ("wake_p_eq_rad_s", "rad/s"), ("roll_deg", "deg")),
          note="a stated offset: u_x 0; no vocabulary"),
    _wake("separation_s", "wake.separation_s", "s", None,
          "unstated: the age is then age_s, which an encounter needs (neither refuses "
          "wake.geometry, so the pair is refused by name -- the variable that moves the age "
          "is the one stated)",
          (("wake_age_s", "s"), ("wake_gamma_m2_s", "m^2/s"), ("wake_p_eq_rad_s", "rad/s"),
           ("roll_deg", "deg")),
          note="a stated time: u_x 0"),
    _wake("age_s", "wake.age_s", "s", None,
          "unstated: the age is then separation_s (the pair is refused by name when neither "
          "is stated: wake.geometry)",
          (("wake_age_s", "s"), ("wake_gamma_m2_s", "m^2/s"), ("wake_p_eq_rad_s", "rad/s"),
           ("roll_deg", "deg")),
          note="a stated time: u_x 0"),
    _wake("model", "wake.model", "word", "none",
          "'none': Gamma_0 held over the run (the spec default); sarpkaya against it decays "
          "the circulation with the age (a declared-input model, unverified here)",
          (("wake_gamma_m2_s", "m^2/s"), ("wake_p_eq_rad_s", "rad/s"), ("wake_v_mps", "m/s"),
           ("wake_w_mps", "m/s"), ("roll_deg", "deg")),
          note="a word: no bin, no spread"),
    _wake("eps_star", "wake.eps_star", "1", None,
          "unstated: no sarpkaya decay (the model none); beside the none model a stated "
          "eps* is carried, not applied, and the record says so",
          (("wake_gamma_m2_s", "m^2/s"), ("wake_p_eq_rad_s", "rad/s"), ("wake_v_mps", "m/s"),
           ("wake_w_mps", "m/s"), ("roll_deg", "deg")),
          note="a declared dimensionless input: u_x 0 unless a tolerance is stated"),
    _wake("n_star", "wake.n_star", "1", None,
          "unstated: no stratification bound on the demise (the sarpkaya demise time from "
          "eps* alone); beside the none model carried, not applied",
          (("wake_gamma_m2_s", "m^2/s"), ("wake_p_eq_rad_s", "rad/s"), ("wake_v_mps", "m/s"),
           ("wake_w_mps", "m/s"), ("roll_deg", "deg")),
          note="a declared dimensionless input: u_x 0 unless a tolerance is stated"),
    VariableRecord(
        name="dis.timestamp_mode", spec_path="dis.timestamp_mode", unit="word",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("hae_m", "m")),
        null_value="relative",
        null_basis="relative timestamps (simulation time past the hour, LSB 0), the in-tree "
                   "default; absolute needs the exporter's epoch; moves no recorded column",
        u_input_rule=UInputRule(note="a word: no bin, no spread")),
    # -- S1: the scene section, claimed whole. terrain_source and terrain
    #    were spec-8 fields the registry did not claim (no scene section
    #    was registered); sun_lux joins them, so the three ride together.
    #    None reaches an equation of motion: the effect channels are the
    #    recorded columns the scene's consumers read (the terrain-impact
    #    check and the labels read the position; the sun model reads the
    #    origin's latitude and longitude), and a pair is a bounded
    #    invariance measured silent (tests/test_sensing_block.py).
    VariableRecord(
        name="scene.terrain_source", spec_path="scene.terrain_source", unit="word",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value="auto",
        null_basis="'auto': today's scene selection (the web app's pick_scene, the CLI's "
                   "--terrain / --synth-terrain), the spec default; moves no recorded column",
        u_input_rule=UInputRule(note="a word: no bin, no spread")),
    VariableRecord(
        name="scene.terrain", spec_path="scene.terrain", unit="text",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: no bake stem (required only when terrain_source is baked); "
                   "moves no recorded column",
        u_input_rule=UInputRule(note="a text: no bin, no spread")),
    VariableRecord(
        name="scene.sun_lux", spec_path="scene.sun_lux", unit="lx",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg")),
        null_value=None,
        null_basis="unstated: the engine's own sun stands (8.0, unitless -- the defect "
                   "sensing.exposure_units names) and the capture manifest carries the "
                   "clear-sky model's lux with source model; a stated sun is a render "
                   "input and moves no recorded column (measured: equal output digests, "
                   "peak 0 on lat_deg and lon_deg, verdict silent)",
        u_input_rule=UInputRule(declared_spread=0.0,
                                note="a stated lux: u_x 0 unless a tolerance is stated; the "
                                     "model value's spread is not declared (a broadband "
                                     "clear-sky model with a constant efficacy)")),
    # -- W2: the cached footprint set (scene.buildings) and the runway block,
    #    one entry per field; nulls are the absent block's (no set, no
    #    runway). None writes a JSBSim property. The buildings are a render
    #    input and the building:all object (bounded invariance on the
    #    position columns, as the other scene fields); the runway's fields
    #    shape the flatten pad, the new bake whose heights the ground
    #    callback reads, so agl_m is the column they move (the record's
    #    null test: h_agl at the threshold with vs without the pad >= 1 m,
    #    core/scene/runway.py measure_pad_null).
    VariableRecord(
        name="scene.buildings", spec_path="scene.buildings", unit="text",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg"),
                         EffectChannel("altitude_m", "m")),
        null_value=None,
        null_basis="unstated: no footprint set, no buildings composed and no building:all "
                   "object; a stated set is a render input and moves no recorded column",
        u_input_rule=UInputRule(note="a cache key: no bin, no spread")),
    *(VariableRecord(
        name=f"runway.{leaf}", spec_path=f"runway.{leaf}", unit=unit,
        effect_channels=(EffectChannel("agl_m", "m"),),
        null_value=null,
        null_basis=basis,
        u_input_rule=UInputRule(note=note))
      for leaf, unit, null, basis, note in (
          ("designator", "word", None,
           "unstated: no runway, no pad bake, the parent bake's heights under the aircraft",
           "a word: no bin, no spread"),
          ("threshold_lat_deg", "deg", None,
           "unstated: no runway (the pad's plane is placed from the threshold)",
           "a stated coordinate: u_x 0 unless a tolerance is stated"),
          ("threshold_lon_deg", "deg", None,
           "unstated: no runway (the pad's plane is placed from the threshold)",
           "a stated coordinate: u_x 0 unless a tolerance is stated"),
          ("heading_deg", "deg", None,
           "unstated: no runway (the pad's footprint is oriented by the heading)",
           "a stated heading: u_x 0 unless a tolerance is stated"),
          ("length_m", "m", None,
           "unstated: no runway (the pad's footprint length)",
           "a stated length: u_x 0 unless a tolerance is stated"),
          ("width_m", "m", None,
           "unstated: no runway (the pad's footprint width)",
           "a stated width: u_x 0 unless a tolerance is stated"),
          ("surface", "word", "asphalt",
           "'asphalt', the block's default word; a scene-dressing word with no friction "
           "model, so no surface word moves agl_m (bounded)",
           "a word: no bin, no spread"),
          ("markings", "word", "standard",
           "'standard', the five Annex 14 elements; the raster is draped by the engine and "
           "moves no recorded column (bounded)",
           "a word or list: no bin, no spread"),
      )),
    # -- W3: the night sky, the rain rate and the world record. A look
    #    variable's effects are on the RENDER: neither spec field reaches an
    #    equation of motion, so its effect channels are the recorded columns
    #    its producer reads (the origin; the flight's speed and height, which
    #    no rain drag moves) and its registry pair is a bounded invariance,
    #    measured silent; the render-side effects are scene.world's reached
    #    predictions (core/scene/world_record.py), each a number computed
    #    here and measured by a named Windows clause, stated so.
    VariableRecord(
        name="scene.night", spec_path="scene.night", unit="mapping {moon, stars, utc}",
        effect_channels=(EffectChannel("lat_deg", "deg"), EffectChannel("lon_deg", "deg")),
        null_value=None,
        null_basis="unstated: no moon light and no starfield, the engine's sky as before; a "
                   "stated night reads the origin and moves no recorded column (a bounded "
                   "invariance on lat_deg and lon_deg); its render-side effect is "
                   "scene.world's moon and stars predictions with their Windows clauses",
        u_input_rule=UInputRule(note="words and a moment: no bin, no spread")),
    VariableRecord(
        name="environment.precipitation_rate_mmh",
        spec_path="environment.precipitation_rate_mmh", unit="mm/h",
        effect_channels=(EffectChannel("altitude_m", "m"), EffectChannel("tas_kt", "kt")),
        null_value=None,
        null_basis="unstated: no rain rate (the precipitation word, if drawn, keeps its "
                   "visibility floor); no rain drag, water ingestion or wet-runway friction is "
                   "modelled, so a stated rate moves no recorded column (a bounded "
                   "invariance); its render-side effect is scene.world's streak prediction "
                   "and the reconciled fog row",
        u_input_rule=UInputRule(bin_width=5.1, declared_spread=0.0,
                                note="the rain intensity words' moderate band 2.5-7.6 mm/h "
                                     "(AMS glossary [unverified here]) is the bin a word "
                                     "maps into, b = 5.1 mm/h, a stated choice")),
    VariableRecord(
        name="scene.world", spec_path=None, unit="look",
        null_basis="no section.leaf spec field of its own: assembled from scene.night, "
                   "environment.precipitation_rate_mmh and the wind at cloud base "
                   "(core/scene/world_record.py); the record carries both null kinds -- "
                   "reached render-side predictions, each a number here and a named Windows "
                   "clause, and the bounded label invariance",
        u_input_rule=UInputRule(note="a derived look: no spread declared")),
    # -- S1: the four sensing variables, observers. Their spec fields are
    #    cameras[i].exposure_compensation_ev / cameras[i].bands (list
    #    elements the section.leaf address cannot claim) and the profile's
    #    optional blocks; each returns its record through the capture
    #    manifest's per-camera sensing block with a null test measured on a
    #    synthetic frame by core/capture/radiometry.py sensing_records.
    VariableRecord(
        name="sensing.radiometry", spec_path=None, unit="cd/m^2 per unit",
        null_basis="no section.leaf spec field (cameras[i].exposure_compensation_ev is a list "
                   "element): the producer measures EC +1 halving the luminance per unit on "
                   "a synthetic frame (reached, threshold half the value)",
        u_input_rule=UInputRule(note="the lens attenuation is the console default until read "
                                     "back; no spread is declared for a predicted constant")),
    VariableRecord(
        name="sensing.bands", spec_path=None, unit="band",
        null_basis="no section.leaf spec field (cameras[i].bands is a list element): the "
                   "producer measures identity weights reproducing the frame (bounded, 0)",
        u_input_rule=UInputRule(note="a declared proxy: no spread")),
    VariableRecord(
        name="sensing.optics", spec_path=None, unit="cycles/px",
        null_basis="a profile block, no spec field: the producer measures an absent block "
                   "leaving the frame bit-identical (bounded, 0) and the e-SFR MTF50 beside "
                   "the prediction",
        u_input_rule=UInputRule(note="stated wavelength, f-number and sigma: no spread")),
    VariableRecord(
        name="sensing.motion_blur", spec_path=None, unit="px",
        null_basis="a profile block, no spec field: the producer measures exposure 0 leaving "
                   "the frame identical (bounded, 0)",
        u_input_rule=UInputRule(note="a stated shutter and flow interval: no spread")),
    # -- S2: the four derived passes, observers. Their spec fields are
    #    cameras[i].passes (the words) and cameras[i].stereo ({baseline_m,
    #    side}), list elements the section.leaf address cannot claim; each
    #    returns its record through the capture manifest's applied_variables
    #    after a render, its null test measured on a synthetic scene by
    #    core/capture/passes.py (pass_records, amodal_record).
    VariableRecord(
        name="passes.flow", spec_path=None, unit="px",
        null_basis="no section.leaf spec field (cameras[i].passes is a list element): the "
                   "producer measures a static scene giving zero flow (bounded, 0) and the "
                   "hidden-aircraft control giving terrain flow",
        u_input_rule=UInputRule(note="geometric from the recorded states: no spread declared")),
    VariableRecord(
        name="passes.disparity", spec_path=None, unit="m",
        null_basis="no section.leaf spec field (cameras[i].stereo is a list element): the "
                   "producer measures a zero baseline giving zero disparity (bounded, 0)",
        u_input_rule=UInputRule(declared_spread=0.0,
                                note="a stated baseline, rectified by construction: u_x 0")),
    VariableRecord(
        name="passes.points", spec_path=None, unit="point",
        null_basis="no section.leaf spec field (cameras[i].passes is a list element): the "
                   "producer measures the sky contributing no point (bounded, 0)",
        u_input_rule=UInputRule(note="depth back-projection, no beam model: no spread")),
    VariableRecord(
        name="passes.amodal", spec_path=None, unit="1",
        null_basis="no section.leaf spec field (cameras[i].passes is a list element): the "
                   "producer measures the amodal / visible ratio equal to 1 / visible_fraction "
                   "on a synthetic pair (bounded, 1e-12)",
        u_input_rule=UInputRule(note="pixel counts of the alone pass: no spread")),
    # -- S3: the IR proxy's two observers. The spec field is cameras[i].ir
    #    ({band, thermal_table}), a list element the section.leaf address
    #    cannot claim, so -- as S1's -- each returns its record through the
    #    capture manifest's per-camera sensing.ir block, null tests measured
    #    on a synthetic bundle by core/capture/thermal.py ir_records.
    VariableRecord(
        name="sensing.ir", spec_path=None, unit="K",
        null_basis="no section.leaf spec field (cameras[i].ir is a list element): the producer "
                   "measures eps = 1 on a unit-transmittance path returning the Planck map of "
                   "the class temperatures (bounded, 0)",
        u_input_rule=UInputRule(note="a declared proxy; T_skin from the recorded Mach and air "
                                     "temperature: no spread")),
    VariableRecord(
        name="sensing.ir_transmittance", spec_path=None, unit="1",
        null_basis="no section.leaf spec field: the producer measures tau = 1 against tau(R), "
                   "the radiance difference growing with range (reached, half the analytic "
                   "difference at the table's last range)",
        u_input_rule=UInputRule(note="a user-provided table (the shipped one synthetic): no "
                                     "spread is declared")),
    # -- R2: the instruments block, one entry per field (each a {profile,
    #    lever_arm_m} mapping; null = the ideal profile at the CG, the
    #    recorded channel being the measurement). No JSBSim write: the
    #    observer reads the FDM and writes nothing, so no readback tolerance
    #    (the record's readback grades the recorder's latest-value sampling
    #    from its own store). The effect channels are the meas_* columns the
    #    instrument owns (core/telemetry/instruments.py INSTRUMENT_COLUMNS),
    #    every one a recorder column (core/telemetry/recorder.py).
    VariableRecord(
        name="instruments.imu", spec_path="instruments.imu", unit="profile + m",
        effect_channels=(EffectChannel("meas_n_z", "g"), EffectChannel("meas_p_dps", "deg/s"),
                         EffectChannel("meas_q_dps", "deg/s"), EffectChannel("meas_r_dps", "deg/s")),
        null_value=None,
        null_basis="unstated: the ideal IMU at the CG (every error term 0, no lever arm): "
                   "meas_n_z and the rates equal JSBSim's own channels to the bit",
        u_input_rule=UInputRule(note="a profile name and a lever arm: no bin, no spread")),
    VariableRecord(
        name="instruments.gps", spec_path="instruments.gps", unit="profile + m",
        effect_channels=(EffectChannel("meas_lat_deg", "deg"), EffectChannel("meas_lon_deg", "deg"),
                         EffectChannel("meas_alt_m", "m")),
        null_value=None,
        null_basis="unstated: the ideal receiver at the CG, a fix every step, no noise: the "
                   "position equals the truth",
        u_input_rule=UInputRule(note="a profile name and an antenna arm: no bin, no spread")),
    VariableRecord(
        name="instruments.pitot_static", spec_path="instruments.pitot_static", unit="profile + m",
        effect_channels=(EffectChannel("meas_cas_kt", "kt"),),
        null_value=None,
        null_basis="unstated: the ideal system, no lag, no position error, no noise: the CAS "
                   "equals JSBSim's vc-kts",
        u_input_rule=UInputRule(note="a profile name and an arm (carried): no bin, no spread")),
    VariableRecord(
        name="instruments.magnetometer", spec_path="instruments.magnetometer", unit="profile + m",
        effect_channels=(EffectChannel("meas_heading_deg", "deg"),),
        null_value=None,
        null_basis="unstated: the ideal magnetometer, no hard iron, no noise: the reading is "
                   "the dipole's magnetic heading (true heading minus the declination)",
        u_input_rule=UInputRule(note="a profile name and an arm (carried): no bin, no spread")),
    # -- R2: the record block, one entry per field. None writes a property
    #    or moves a recorded column (each asks for extra flights beside the
    #    recorded one); the effect channels are the SRQs the uncertainty
    #    block reports, and a pair is measured silent (the same flight).
    VariableRecord(
        name="record.null_tests", spec_path="record.null_tests", unit="flag",
        effect_channels=(EffectChannel("altitude_m", "m"), EffectChannel("tas_kt", "kt"),
                         EffectChannel("heading_deg", "deg")),
        null_value=False,
        null_basis="false: no null pair flown (the --null-tests option still asks); moves "
                   "no recorded column",
        u_input_rule=UInputRule(note="a flag: no bin, no spread")),
    VariableRecord(
        name="record.convergence", spec_path="record.convergence", unit="Hz",
        effect_channels=(EffectChannel("altitude_m", "m"), EffectChannel("tas_kt", "kt"),
                         EffectChannel("heading_deg", "deg")),
        null_value=None,
        null_basis="unstated: no three-rate study; u_num assumes order 1 with Fs = 3; moves "
                   "no recorded column",
        u_input_rule=UInputRule(note="a list of rates: no bin, no spread")),
    VariableRecord(
        name="record.sensitivity_pairs", spec_path="record.sensitivity_pairs", unit="flag",
        effect_channels=(EffectChannel("altitude_m", "m"), EffectChannel("tas_kt", "kt"),
                         EffectChannel("heading_deg", "deg")),
        null_value=False,
        null_basis="false: no central pair flown (the --uncertainty option still asks); moves "
                   "no recorded column",
        u_input_rule=UInputRule(note="a flag: no bin, no spread")),
))
