"""Provenanced values: the atom of a scenario spec.

§2.6 requires that every field record where its value came from. The point is
not bookkeeping. A scenario assembled from a sentence contains three very
different kinds of number -- what the user actually said, what was inferred from
a vague phrase, and what was defaulted because nobody mentioned it -- and a
reviewer cannot judge a result without being able to tell them apart.

    wind:
      speed:     {value: 25, unit: kt, source: inferred, from: "strong crosswind"}
      direction: {value: 270, unit: deg, source: inferred, from: "crosswind"}
    turbulence:
      intensity: {value: moderate, W20_kt: 30, source: default,
                  std: "MIL-F-8785C Fig.7"}

The ``std`` field is what §2.5 demands of a plugin: a turbulence model must be
able to answer "what does moderate mean" with a citation rather than a magic
number.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Any, Dict, Optional


class Source(str, Enum):
    """Where a value came from. Ordered by how much it can be trusted."""

    USER = "user"          #: stated explicitly in the prompt
    INFERRED = "inferred"  #: derived from a vague phrase ("strong crosswind")
    DEFAULT = "default"    #: nobody mentioned it
    DERIVED = "derived"    #: computed from the flight model itself

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Quantity:
    """A value, its unit, and its provenance.

    Frozen. A spec is the reproducible unit of this system (§2.6), so nothing
    may quietly rewrite a field after validation has passed on it.
    """

    value: Any
    unit: Optional[str] = None
    source: Source = Source.DEFAULT
    #: The phrase this was read from, or the origin of the default.
    frm: Optional[str] = None
    #: Citation backing the mapping, e.g. "MIL-F-8785C Fig.7".
    std: Optional[str] = None
    #: Anything model-specific the mapping needs to be reproducible, such as
    #: ``{"W20_kt": 30}`` for a turbulence intensity word.
    detail: Dict[str, Any] = dc_field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.source, str) and not isinstance(self.source, Source):
            object.__setattr__(self, "source", Source(self.source))

    # -- construction helpers, so call sites read as documentation ------

    @classmethod
    def user(cls, value, unit=None, frm=None, **detail) -> "Quantity":
        return cls(value, unit, Source.USER, frm, None, detail)

    @classmethod
    def inferred(cls, value, unit=None, frm=None, std=None, **detail) -> "Quantity":
        return cls(value, unit, Source.INFERRED, frm, std, detail)

    @classmethod
    def default(cls, value, unit=None, frm=None, std=None, **detail) -> "Quantity":
        return cls(value, unit, Source.DEFAULT, frm, std, detail)

    @classmethod
    def derived(cls, value, unit=None, frm=None, std=None, **detail) -> "Quantity":
        """Measured from the flight model rather than asserted.

        Used for stall and reference speeds, which §5 Phase 1 requires be
        derived from measured lift coefficients rather than taken from a table.
        """
        return cls(value, unit, Source.DERIVED, frm, std, detail)

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Canonical mapping. Keys are emitted in a fixed order so that two
        specs with the same content serialise identically."""
        out: Dict[str, Any] = {"value": self.value}
        if self.unit is not None:
            out["unit"] = self.unit
        out["source"] = str(self.source)
        if self.frm is not None:
            out["from"] = self.frm
        if self.std is not None:
            out["std"] = self.std
        for key in sorted(self.detail):
            out[key] = self.detail[key]
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Quantity":
        known = {"value", "unit", "source", "from", "std"}
        return cls(
            value=data["value"],
            unit=data.get("unit"),
            source=Source(data.get("source", "default")),
            frm=data.get("from"),
            std=data.get("std"),
            detail={k: v for k, v in data.items() if k not in known},
        )

    def render(self) -> str:
        """One-line human rendering for the spec table."""
        if isinstance(self.value, float):
            shown = f"{self.value:g}"
        else:
            shown = str(self.value)
        return f"{shown} {self.unit}" if self.unit else shown

    def note(self) -> str:
        """The provenance, rendered for the right-hand column of the table."""
        bits = []
        if self.frm:
            bits.append(f'"{self.frm}"' if self.source is Source.INFERRED else self.frm)
        if self.std:
            bits.append(self.std)
        for key in sorted(self.detail):
            bits.append(f"{key}={self.detail[key]}")
        return "; ".join(bits)
