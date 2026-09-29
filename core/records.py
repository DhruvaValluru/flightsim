"""The record every introduced variable returns -- one shape, used by all.

A government-grade record of a simulation input is not the value alone
(docs/PHASE3_GAP_ANALYSIS.md section 5.2). For every variable an addition
introduces, the run carries:

* the applied VALUE with its unit and its provenance source (the spec's
  own words: user, inferred, sampled, model, derived, default), the
  phrase it was read from (``from``) and the citation backing the
  mapping (``std``);
* the MODEL that consumed it, with its parameters and the references
  the model comes from (designation, section, author, year) -- as a
  string (``model_name``) and as a structured block (``model``: name,
  standard, version, parameters, references);
* WHERE it went: the JSBSim or engine properties written, and at
  record 2 WHEN each JSBSim property is written (``jsbsim_writes``)
  and the READBACK of the property against the value written, graded
  against a per-variable tolerance (``readback``);
* WHAT it returns: the telemetry columns recorded per step and the
  per-frame keys written into the capture manifest;
* a NULL TEST -- the same run with and without the variable, and the
  measured difference against a declared threshold (the Gate 3
  pattern: a feature that leaves no trace never reached the equations
  of motion). Record 2 gives the test a KIND: ``reached`` (the
  difference must be at least the threshold) or ``bounded`` (the
  difference must be at most the threshold -- an invariance test such
  as "the datum moves no pixel", which record 1 could not express);
* the UNCERTAINTY the variable carries into the run (record 2):
  ``u_input`` by GUM propagation and ``u_num`` from a dt/2 twin
  (core/uncertainty.py);
* what is NOT claimed for it.

The record is data, not behaviour: :func:`records_block` serialises a
sequence of them into the block the run manifest and the capture
manifest carry under ``applied_variables``. Readers key on
``record_version``.

Record 2 (``RECORD_VERSION`` 2, the integrator's one bump of the
advancement addition; ADVANCEMENTS_BLUEPRINT "Versions and keys"). The
structured model block is ``model`` and the model's one-line name is
``model_name``; at record 1 the string was ``model`` and the block (in
the builds that wrote record-2 fields under version 1) rode beside it
as ``model_block``. Every other record-2 field (``from``, ``std``,
``readback``, ``jsbsim_writes``, ``model``, ``uncertainty``) is
OPTIONAL and emitted only when set, so the canonical dict of a record
that sets none of them is the twelve record-1 keys with ``model``
spelled ``model_name``. ``kind`` is emitted on every null test because
the arithmetic that grades it is not recoverable without it; record-1
producers all mean ``reached``.

Reading. :func:`read_records` reads a block at record 1 or 2 and hands
back record-2 dicts: a record-1 dict is renamed (``model`` ->
``model_name``, ``model_block`` -> ``model``) and nothing else is
touched (:func:`upgrade_record`). :meth:`AppliedVariable.from_dict`
reads either shape. Any other version is refused by name.

NOT claimed: a record says what was applied, read back and measured;
it does not say the model is right. The null test is connectivity and
one-sided sensitivity, not correctness. The readback grades JSBSim's
property store, not the physics that consumed the value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

#: Bumped when a key is added or renamed; readers refuse by name.
#: 2 (2026-09-29, INT-final): readback, jsbsim_writes, uncertainty, the
#: structured ``model`` block (the string renamed ``model_name``) and
#: ``NullTest.kind`` are the canonical shape.
RECORD_VERSION = 2

#: The record versions :func:`read_records` reads (a record-1 block is
#: handed back renamed to record 2; see :func:`upgrade_record`).
READABLE_RECORD_VERSIONS = (1, 2)

#: The provenance words the spec uses, in precedence order (fields.py).
SOURCES = ("user", "inferred", "sampled", "model", "derived", "default")

#: The two arithmetics a null test can carry. ``reached``: the variable
#: must have moved the quantity by at least the threshold. ``bounded``:
#: the variable must have moved it by at most the threshold (an
#: invariance the addition promises).
NULL_KINDS = ("reached", "bounded")

#: How a readback tolerance is read: against the written value's
#: magnitude, or as an absolute difference in the property's unit.
TOLERANCE_KINDS = ("absolute", "relative")


@dataclass(frozen=True)
class NullTest:
    """With-versus-without, measured: the difference a variable makes.

    ``kind`` decides the arithmetic of ``ok``: ``reached`` is
    ``|difference| >= threshold``; ``bounded`` is ``|difference| <=
    threshold``. A test that measures nothing is not ok as ``reached``
    and IS ok as ``bounded`` -- which is the point of the second kind.
    """

    quantity: str            # what was compared, e.g. "peak altitude"
    unit: str
    with_value: float
    without_value: float
    threshold: float         # the smallest (reached) / largest (bounded) difference that counts
    note: str = ""
    kind: str = "reached"

    def __post_init__(self) -> None:
        if self.kind not in NULL_KINDS:
            raise ValueError(f"null test kind {self.kind!r} is not one of {NULL_KINDS}")

    @property
    def difference(self) -> float:
        return float(self.with_value) - float(self.without_value)

    @property
    def ok(self) -> bool:
        if self.kind == "bounded":
            return abs(self.difference) <= float(self.threshold)
        return abs(self.difference) >= float(self.threshold)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quantity": self.quantity, "unit": self.unit,
            "with": float(self.with_value), "without": float(self.without_value),
            "difference": self.difference, "threshold": float(self.threshold),
            "ok": self.ok, "note": self.note, "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NullTest":
        """A null test back out of its dict; a record-1 dict (no ``kind``)
        reads as ``reached``, which is what every record-1 producer meant."""
        return cls(quantity=data["quantity"], unit=data["unit"],
                   with_value=float(data["with"]), without_value=float(data["without"]),
                   threshold=float(data["threshold"]), note=data.get("note", ""),
                   kind=data.get("kind", "reached"))


@dataclass(frozen=True)
class Readback:
    """A JSBSim property read back after it was written, graded.

    ``value`` is what came back; ``written`` what went in; ``agrees`` is
    ``|value - written| <= tolerance`` (absolute) or ``<= tolerance *
    |written|`` (relative), the kind and the tolerance being the
    registry's per-variable declaration; ``basis`` says why that
    tolerance (the measured round trip). A readback grades the property
    store, not the physics.
    """

    property: str
    value: float
    written: float
    tolerance: float
    tolerance_kind: str = "absolute"
    basis: str = ""

    def __post_init__(self) -> None:
        if self.tolerance_kind not in TOLERANCE_KINDS:
            raise ValueError(f"readback tolerance kind {self.tolerance_kind!r} "
                             f"is not one of {TOLERANCE_KINDS}")
        if float(self.tolerance) < 0.0:
            raise ValueError(f"{self.property}: a negative readback tolerance")

    @property
    def difference(self) -> float:
        return float(self.value) - float(self.written)

    @property
    def agrees(self) -> bool:
        allowed = float(self.tolerance)
        if self.tolerance_kind == "relative":
            allowed = allowed * abs(float(self.written))
        return abs(self.difference) <= allowed

    def to_dict(self) -> Dict[str, Any]:
        return {"property": self.property, "value": float(self.value),
                "written": float(self.written), "agrees": self.agrees,
                "tolerance": float(self.tolerance),
                "tolerance_kind": self.tolerance_kind, "basis": self.basis}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Readback":
        return cls(property=data["property"], value=float(data["value"]),
                   written=float(data["written"]), tolerance=float(data["tolerance"]),
                   tolerance_kind=data.get("tolerance_kind", "absolute"),
                   basis=data.get("basis", ""))


@dataclass(frozen=True)
class JsbsimWrite:
    """One JSBSim property a variable writes, and when: ``setup``,
    ``before trim``, ``every step`` -- the delivery discipline the
    physics blueprint names per variable."""

    property: str
    when: str

    def __post_init__(self) -> None:
        if not self.property or not self.when:
            raise ValueError("a JSBSim write names its property and when it is written")

    def to_dict(self) -> Dict[str, str]:
        return {"property": self.property, "when": self.when}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "JsbsimWrite":
        return cls(property=data["property"], when=data["when"])


@dataclass(frozen=True)
class Model:
    """The structured model block: the model's name, the standard it
    implements, its version, its parameters and its references."""

    name: str
    standard: str = ""
    version: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("a model block without a name says nothing")

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "standard": self.standard, "version": self.version,
                "parameters": dict(self.parameters), "references": list(self.references)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Model":
        return cls(name=data["name"], standard=data.get("standard", ""),
                   version=data.get("version", ""),
                   parameters=dict(data.get("parameters") or {}),
                   references=tuple(data.get("references") or ()))


#: The keys an ``uncertainty`` block on a record may carry, and the keys
#: inside each (core/uncertainty.py builds them; this module only checks
#: the shape so a record never carries an uncertainty it cannot name).
UNCERTAINTY_KEYS = ("u_input", "u_num")
U_INPUT_KEYS = ("value", "unit", "rule", "sensitivity")
U_NUM_KEYS = ("srq", "value", "basis")


def check_uncertainty(block: Mapping[str, Any]) -> Dict[str, Any]:
    """The record's uncertainty block, shape-checked: ``u_input`` {value,
    unit, rule, sensitivity} and ``u_num`` {srq, value, basis}, either
    absent (None) when it was not measured. Raises ValueError on a key
    this module does not know -- a record never carries an uncertainty
    it cannot name."""
    unknown = set(block) - set(UNCERTAINTY_KEYS)
    if unknown:
        raise ValueError(f"uncertainty block carries unknown keys {sorted(unknown)}")
    out: Dict[str, Any] = {}
    for key, required in (("u_input", U_INPUT_KEYS), ("u_num", U_NUM_KEYS)):
        part = block.get(key)
        if part is None:
            out[key] = None
            continue
        missing = [k for k in required if k not in part]
        if missing:
            raise ValueError(f"uncertainty {key} is missing {missing}")
        out[key] = dict(part)
    return out


@dataclass(frozen=True)
class AppliedVariable:
    """One introduced variable, as applied to one run (record 2)."""

    name: str                                   # dotted: "atmosphere.temperature_deviation_c"
    value: Any
    unit: str
    source: str                                 # one of SOURCES
    model_name: str                             # "ISA deviation (US Standard Atmosphere 1976 graded)"
    parameters: Dict[str, Any] = field(default_factory=dict)
    references: Tuple[str, ...] = ()
    properties_written: Tuple[str, ...] = ()    # JSBSim / engine properties
    telemetry_columns: Tuple[str, ...] = ()
    frame_keys: Tuple[str, ...] = ()            # keys under the frame record's "state"
    null_test: Optional[NullTest] = None
    not_claimed: Tuple[str, ...] = ()
    # -- record 2 (each optional; emitted only when set) ---------------
    frm: Optional[str] = None                   # the provenance 'from' text
    std: Optional[str] = None                   # the citation backing the mapping
    readback: Optional[Readback] = None
    jsbsim_writes: Tuple[JsbsimWrite, ...] = ()
    model: Optional[Model] = None               # the structured model block
    uncertainty: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"{self.name}: source {self.source!r} is not one of {SOURCES}")
        if not self.model_name or not isinstance(self.model_name, str):
            raise ValueError(f"{self.name}: a record without a model name says nothing")
        if self.model is not None and not isinstance(self.model, Model):
            raise ValueError(f"{self.name}: the model block is a Model, not "
                             f"{type(self.model).__name__} (the one-line name is model_name)")
        if self.uncertainty is not None:
            object.__setattr__(self, "uncertainty", check_uncertainty(self.uncertainty))
        for write in self.jsbsim_writes:
            if write.property not in self.properties_written:
                raise ValueError(f"{self.name}: jsbsim_writes names {write.property!r}, "
                                 f"which properties_written does not")

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "name": self.name, "value": self.value, "unit": self.unit,
            "source": self.source, "model_name": self.model_name,
            "parameters": dict(self.parameters),
            "references": list(self.references),
            "properties_written": list(self.properties_written),
            "telemetry_columns": list(self.telemetry_columns),
            "frame_keys": list(self.frame_keys),
            "null_test": None if self.null_test is None else self.null_test.to_dict(),
            "not_claimed": list(self.not_claimed),
        }
        # Record 2, absent-canonical: a key rides only when its field is set.
        if self.frm is not None:
            out["from"] = self.frm
        if self.std is not None:
            out["std"] = self.std
        if self.readback is not None:
            out["readback"] = self.readback.to_dict()
        if self.jsbsim_writes:
            out["jsbsim_writes"] = [w.to_dict() for w in self.jsbsim_writes]
        if self.model is not None:
            out["model"] = self.model.to_dict()
        if self.uncertainty is not None:
            out["uncertainty"] = dict(self.uncertainty)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AppliedVariable":
        """A record back out of its dict, record 1 or record 2 (a dict
        without ``model_name`` is a record-1 dict and is renamed first,
        :func:`upgrade_record`): every record-2 key is read when present
        and left at its default when not. Nothing is recomputed."""
        data = upgrade_record(data)
        null = data.get("null_test")
        readback = data.get("readback")
        model = data.get("model")
        return cls(
            name=data["name"], value=data["value"], unit=data["unit"],
            source=data["source"], model_name=data["model_name"],
            parameters=dict(data.get("parameters") or {}),
            references=tuple(data.get("references") or ()),
            properties_written=tuple(data.get("properties_written") or ()),
            telemetry_columns=tuple(data.get("telemetry_columns") or ()),
            frame_keys=tuple(data.get("frame_keys") or ()),
            null_test=None if null is None else NullTest.from_dict(null),
            not_claimed=tuple(data.get("not_claimed") or ()),
            frm=data.get("from"), std=data.get("std"),
            readback=None if readback is None else Readback.from_dict(readback),
            jsbsim_writes=tuple(JsbsimWrite.from_dict(w)
                                for w in (data.get("jsbsim_writes") or ())),
            model=None if model is None else Model.from_dict(model),
            uncertainty=data.get("uncertainty"),
        )


def upgrade_record(data: Mapping[str, Any]) -> Dict[str, Any]:
    """One record dict in the record-2 spelling. A record-1 dict (the
    model's name under ``model``, a string, and -- from the builds that
    wrote record-2 fields under version 1 -- the block under
    ``model_block``) is renamed: ``model`` -> ``model_name``,
    ``model_block`` -> ``model``; every other key and value is handed
    back as it was, in its order. A record-2 dict comes back as a copy."""
    if "model_name" in data or not isinstance(data.get("model"), str):
        return dict(data)
    out: Dict[str, Any] = {}
    for key, value in data.items():
        if key == "model":
            out["model_name"] = value
        elif key == "model_block":
            out["model"] = value
        else:
            out[key] = value
    return out


def records_block(variables: Sequence[AppliedVariable]) -> Dict[str, Any]:
    """The manifest block: every applied variable, plus the version."""
    names = [v.name for v in variables]
    if len(set(names)) != len(names):
        raise ValueError(f"applied variables repeat a name: {names}")
    return {"record_version": RECORD_VERSION,
            "applied_variables": [v.to_dict() for v in variables]}


def read_records(block: Dict[str, Any]) -> Tuple[Dict[str, Any], ...]:
    """The records back out of a block, as record-2 dicts: a record-2
    block's dicts as written, a record-1 block's renamed by
    :func:`upgrade_record`. Refuses any other version by name."""
    version = block.get("record_version")
    if version not in READABLE_RECORD_VERSIONS:
        raise ValueError(f"applied_variables record_version {version!r} "
                         f"(this build reads {READABLE_RECORD_VERSIONS}, "
                         f"writes {RECORD_VERSION})")
    records = tuple(block.get("applied_variables", ()))
    if version == RECORD_VERSION:
        return records
    return tuple(upgrade_record(r) if isinstance(r, Mapping) else r for r in records)
