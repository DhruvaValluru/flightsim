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
        effect_channels=(EffectChannel("exceed_nz_pos", "1"), EffectChannel("exceed_nz_neg", "1"),
                         EffectChannel("exceed_vne_or_vmo", "1"), EffectChannel("exceed_mmo", "1"),
                         EffectChannel("exceed_alpha_stall", "1"),
                         EffectChannel("any_exceedance", "1")),
        null_basis="no spec field: an observer; the producer's null test offsets the run's "
                   "own samples across the probe limit",
        host_channels=("exceed_nz_pos", "exceed_nz_neg", "exceed_vne_or_vmo", "exceed_mmo",
                       "exceed_alpha_stall", "any_exceedance")),
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
    _injected("icing.lift_factor", "icing/lift-factor", "1",
              "1.0 scales the LIFT axis by one: bit-identical to the stock airframe (0.8 read 1872.5287 -> 1498.0230 lbf)",
              (("lift_n", "N"), ("altitude_m", "m")), ("lift_n",)),
    _injected("icing.drag_factor", "icing/drag-factor", "1",
              "1.0 scales the DRAG axis by one: bit-identical to the stock airframe",
              (("tas_kt", "kt"),), ("tas_kt",)),
    _injected("icing.side_factor", "icing/side-factor", "1",
              "1.0 scales the SIDE axis by one: bit-identical to the stock airframe",
              (("side_force_n", "N"),), ("side_force_n",)),
    _injected("icing.roll_factor", "icing/roll-factor", "1",
              "1.0 scales the ROLL axis by one: bit-identical to the stock airframe",
              (("roll_deg", "deg"),), ("roll_deg",)),
    _injected("icing.pitch_factor", "icing/pitch-factor", "1",
              "1.0 scales the PITCH axis by one: bit-identical to the stock airframe",
              (("pitch_deg", "deg"),), ("pitch_deg",)),
    _injected("icing.yaw_factor", "icing/yaw-factor", "1",
              "1.0 scales the YAW axis by one: bit-identical to the stock airframe",
              (("beta_deg", "deg"),), ("beta_deg",)),
    _injected("icing.eta", "icing/eta", "1",
              "0 is no ice; declared for the icing provider (P5), read by nothing until it lands, "
              "so no effect channel is named", (), ()),
    _injected("icing.alpha_shift_rad", "icing/alpha-shift-rad", "rad",
              "0 leaves the LIFT table's alpha as aero/alpha-rad: bit-identical (2 deg moved the lift peak -2.0 deg)",
              (("alpha_deg", "deg"), ("lift_n", "N")), ("alpha_deg",)),
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
    VariableRecord(
        name="environment.weather_event", spec_path="environment.weather_event", unit="word",
        effect_channels=(EffectChannel("wind_down_mps", "m/s"),
                         EffectChannel("wind_north_mps", "m/s"),
                         EffectChannel("wind_east_mps", "m/s")),
        null_value="none",
        null_basis="'none': no severe-weather feature placed, the spec default",
        u_input_rule=UInputRule(note="a word: no bin, no spread"),
        host_channels=("wind_down_mps",)),
))
