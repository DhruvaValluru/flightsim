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


def _suffix_unit(name: str) -> str:
    """The recorder's suffix convention for a channel name, or ``?``.
    Imported lazily: the manifest consults this registry first, so the
    two modules meet only inside function bodies."""
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
))
