"""The record every introduced variable returns -- one shape, used by all.

A government-grade record of a simulation input is not the value alone
(docs/PHASE3_GAP_ANALYSIS.md §5.2). For every variable an addition
introduces, the run carries:

* the applied VALUE with its unit and its provenance source (the spec's
  own words: user, inferred, sampled, model, derived, default);
* the MODEL that consumed it, with its parameters and the references
  the model comes from (designation, section, author, year);
* WHERE it went: the JSBSim or engine properties written;
* WHAT it returns: the telemetry columns recorded per step and the
  per-frame keys written into the capture manifest;
* a NULL TEST -- the same run with and without the variable, and the
  measured difference against a declared threshold (the Gate 3
  pattern: a feature that leaves no trace never reached the equations
  of motion);
* what is NOT claimed for it.

The record is data, not behaviour: :func:`records_block` serialises a
sequence of them into the block the run manifest and the capture
manifest carry under ``applied_variables``. Readers key on
``record_version``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

#: Bumped when a key is added or renamed; readers refuse by name.
RECORD_VERSION = 1

#: The provenance words the spec uses, in precedence order (fields.py).
SOURCES = ("user", "inferred", "sampled", "model", "derived", "default")


@dataclass(frozen=True)
class NullTest:
    """With-versus-without, measured: the difference a variable makes."""

    quantity: str            # what was compared, e.g. "peak altitude"
    unit: str
    with_value: float
    without_value: float
    threshold: float         # the smallest difference that counts as "reached"
    note: str = ""

    @property
    def difference(self) -> float:
        return float(self.with_value) - float(self.without_value)

    @property
    def ok(self) -> bool:
        return abs(self.difference) >= float(self.threshold)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quantity": self.quantity, "unit": self.unit,
            "with": float(self.with_value), "without": float(self.without_value),
            "difference": self.difference, "threshold": float(self.threshold),
            "ok": self.ok, "note": self.note,
        }


@dataclass(frozen=True)
class AppliedVariable:
    """One introduced variable, as applied to one run."""

    name: str                                   # dotted: "atmosphere.temperature_deviation_c"
    value: Any
    unit: str
    source: str                                 # one of SOURCES
    model: str                                  # "ISA deviation (US Standard Atmosphere 1976 graded)"
    parameters: Dict[str, Any] = field(default_factory=dict)
    references: Tuple[str, ...] = ()
    properties_written: Tuple[str, ...] = ()    # JSBSim / engine properties
    telemetry_columns: Tuple[str, ...] = ()
    frame_keys: Tuple[str, ...] = ()            # keys under the frame record's "state"
    null_test: Optional[NullTest] = None
    not_claimed: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"{self.name}: source {self.source!r} is not one of {SOURCES}")
        if not self.model:
            raise ValueError(f"{self.name}: a record without a model says nothing")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "value": self.value, "unit": self.unit,
            "source": self.source, "model": self.model,
            "parameters": dict(self.parameters),
            "references": list(self.references),
            "properties_written": list(self.properties_written),
            "telemetry_columns": list(self.telemetry_columns),
            "frame_keys": list(self.frame_keys),
            "null_test": None if self.null_test is None else self.null_test.to_dict(),
            "not_claimed": list(self.not_claimed),
        }


def records_block(variables: Sequence[AppliedVariable]) -> Dict[str, Any]:
    """The manifest block: every applied variable, plus the version."""
    names = [v.name for v in variables]
    if len(set(names)) != len(names):
        raise ValueError(f"applied variables repeat a name: {names}")
    return {"record_version": RECORD_VERSION,
            "applied_variables": [v.to_dict() for v in variables]}


def read_records(block: Dict[str, Any]) -> Tuple[Dict[str, Any], ...]:
    """The records back out of a block; refuses an unknown version by name."""
    version = block.get("record_version")
    if version != RECORD_VERSION:
        raise ValueError(f"applied_variables record_version {version!r} "
                         f"(this build reads {RECORD_VERSION})")
    return tuple(block.get("applied_variables", ()))
