"""Validation against published tolerances, reported the way V&V asks for.

§7.3 adopts FAA 14 CFR Part 60 Appendix A as the acceptance bar, and §7.2 asks
that comparisons be reported in ASME V&V 20 form -- comparison error together
with validation uncertainty -- rather than as a bare percentage difference.

The distinction matters more than it sounds. "Within 2.1%" says nothing about
whether 2.1% is small compared to what is known about the referent. V&V 20 keeps
three quantities separate:

    E   = S - D        comparison error: simulation minus experimental data
    u_D                uncertainty in the reference datum
    u_num              numerical uncertainty in the simulation
    u_input            uncertainty from inputs
    u_val = sqrt(u_D^2 + u_num^2 + u_input^2)

and the model is validated at the level of u_val if |E| <= u_val. If |E| is much
larger, the model error is resolved; if |E| is smaller than u_val, the comparison
is **inconclusive** -- the data are not sharp enough to detect a discrepancy of
that size. Inconclusive is a real and common outcome and is reported as itself,
not as a pass.

What this build can honestly compare against
--------------------------------------------
Very little, and that is the finding rather than an obstacle to work around.
Stock JSBSim aircraft carry no validated flight-test data (§3.3), so there is no
trustworthy D for most quantities. Where a reference figure is used here it is a
published nominal quoted from open literature, with a deliberately wide u_D to
reflect that it is a specification number rather than a measurement with a
stated uncertainty.

The result is a validation suite that mostly returns INCONCLUSIVE. That is the
correct answer, and it is worth more than a suite that returns PASS by comparing
the model to itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class Verdict(str, Enum):
    #: |E| <= u_val: agreement within the uncertainty available.
    VALIDATED = "validated at u_val"
    #: |E| > u_val: a resolved discrepancy. The model is wrong by more than
    #: the comparison's own uncertainty can explain.
    DISCREPANT = "discrepant"
    #: There is no referent worth comparing to, so no comparison was made.
    INCONCLUSIVE = "inconclusive"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Tolerance:
    """One row of FAA 14 CFR Part 60 Appendix A."""

    parameter: str
    absolute: Optional[float] = None
    percent: Optional[float] = None
    unit: str = ""
    note: str = ""

    def allowed(self, reference: float) -> float:
        """The tolerance band about a reference value.

        Part 60 rows are frequently "±3 kt or ±5%, whichever is greater"; where
        both are given the wider is used, which is what the standard means.
        """
        candidates = []
        if self.absolute is not None:
            candidates.append(abs(self.absolute))
        if self.percent is not None:
            candidates.append(abs(reference) * self.percent / 100.0)
        return max(candidates) if candidates else math.inf

    def render(self) -> str:
        parts = []
        if self.absolute is not None:
            parts.append(f"±{self.absolute:g} {self.unit}".strip())
        if self.percent is not None:
            parts.append(f"±{self.percent:g}%")
        return f"{self.parameter}: {' or '.join(parts)}"


#: §7.3's table. Quoted for the rows this system can in principle exercise.
PART60 = {
    "rotation_speed": Tolerance("Rotation speed", absolute=3.0, unit="kt"),
    "rotation_pitch": Tolerance("Rotation pitch attitude", absolute=1.5, unit="deg"),
    "approach_airspeed": Tolerance("Approach airspeed", absolute=3.0, unit="kt"),
    "approach_pitch": Tolerance("Approach pitch attitude", absolute=1.5, unit="deg"),
    "approach_altitude": Tolerance("Approach altitude", absolute=3.048,
                                   percent=10.0, unit="m",
                                   note="±10 ft or ±10%"),
    "takeoff_ground_roll": Tolerance("Takeoff ground roll", absolute=61.0,
                                     percent=5.0, unit="m",
                                     note="±200 ft or ±5% of time"),
    "climb_rate": Tolerance("Climb rate", absolute=0.508, percent=5.0,
                            unit="m/s", note="±100 fpm or ±5%"),
    "engine_spool": Tolerance("Engine spool time", percent=10.0, unit="s"),
    "elevator_deflection": Tolerance("Elevator deflection", absolute=2.0, unit="deg"),
    "rudder_deflection": Tolerance("Rudder deflection", absolute=2.0, unit="deg"),
    "aileron_deflection": Tolerance("Aileron deflection", absolute=10.0, unit="deg"),
    "dynamic_period": Tolerance("Underdamped response period", percent=10.0, unit="s"),
    "dynamic_overshoot": Tolerance("Underdamped overshoot", percent=20.0, unit=""),
    "transport_delay": Tolerance("Transport delay", absolute=0.150, unit="s",
                                 note="Level C/D; ≤300 ms for Level A/B"),
}


@dataclass(frozen=True)
class Reference:
    """A published value to compare against, with its uncertainty.

    ``uncertainty`` is ``u_D``. Where a figure is a manufacturer specification
    or a number quoted in open literature rather than a measurement with stated
    error, that is said in ``pedigree`` and ``u_D`` is set wide accordingly --
    a specification quoted to three significant figures is not a measurement to
    three significant figures.
    """

    quantity: str
    value: float
    unit: str
    uncertainty: float
    source: str
    pedigree: str


@dataclass
class Comparison:
    """One validation comparison, in ASME V&V 20 terms."""

    quantity: str
    simulation: float
    reference: Optional[Reference]
    unit: str
    numerical_uncertainty: float = 0.0
    input_uncertainty: float = 0.0
    tolerance: Optional[Tolerance] = None
    note: str = ""

    @property
    def comparison_error(self) -> float:
        """E = S - D."""
        if self.reference is None:
            return math.nan
        return self.simulation - self.reference.value

    @property
    def validation_uncertainty(self) -> float:
        """u_val = sqrt(u_D^2 + u_num^2 + u_input^2)."""
        if self.reference is None:
            return math.nan
        return math.sqrt(self.reference.uncertainty ** 2
                         + self.numerical_uncertainty ** 2
                         + self.input_uncertainty ** 2)

    @property
    def verdict(self) -> Verdict:
        if self.reference is None:
            return Verdict.INCONCLUSIVE
        error = abs(self.comparison_error)
        u_val = self.validation_uncertainty
        if error > u_val:
            return Verdict.DISCREPANT
        return Verdict.VALIDATED

    @property
    def within_part60(self) -> Optional[bool]:
        """Whether the comparison error sits inside the Part 60 band.

        Separate from the verdict on purpose. Part 60 is a *certification*
        tolerance for a device being qualified against flight-test data; it is
        not a statement about uncertainty, and passing it does not validate a
        model whose referent is a specification sheet.
        """
        if self.reference is None or self.tolerance is None:
            return None
        return abs(self.comparison_error) <= self.tolerance.allowed(
            self.reference.value)

    def render(self) -> str:
        if self.reference is None:
            return (f"  [{Verdict.INCONCLUSIVE}] {self.quantity}: "
                    f"simulation {self.simulation:.3f} {self.unit}, "
                    f"no reference datum -- {self.note}")
        part60 = ""
        if self.within_part60 is not None:
            part60 = (f", Part 60 {'within' if self.within_part60 else 'OUTSIDE'} "
                      f"{self.tolerance.render()}")
        return (
            f"  [{self.verdict}] {self.quantity}\n"
            f"      S = {self.simulation:.3f} {self.unit}, "
            f"D = {self.reference.value:.3f} +/- {self.reference.uncertainty:.3f}\n"
            f"      E = {self.comparison_error:+.3f}, "
            f"u_val = {self.validation_uncertainty:.3f}{part60}\n"
            f"      D pedigree: {self.reference.pedigree}"
        )


@dataclass
class ValidationReport:
    title: str
    comparisons: List[Comparison] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, comparison: Comparison) -> "ValidationReport":
        self.comparisons.append(comparison)
        return self

    def counts(self) -> Dict[str, int]:
        out = {v.value: 0 for v in Verdict}
        for comparison in self.comparisons:
            out[comparison.verdict.value] += 1
        return out

    @property
    def discrepant(self) -> List[Comparison]:
        return [c for c in self.comparisons if c.verdict is Verdict.DISCREPANT]

    def render(self) -> str:
        lines = [self.title, "=" * len(self.title), ""]
        for comparison in self.comparisons:
            lines.append(comparison.render())
            lines.append("")
        counts = self.counts()
        lines.append("summary: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
        if counts[Verdict.INCONCLUSIVE.value]:
            lines.append(
                "\nInconclusive results are the expected outcome for most rows "
                "here. Stock JSBSim aircraft carry no validated flight-test "
                "data (§3.3), so for most quantities there is no referent worth "
                "comparing against. Reporting that is the honest result; a "
                "suite that returned PASS would be comparing the model to "
                "itself."
            )
        for note in self.notes:
            lines.append(f"\nnote: {note}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "counts": self.counts(),
            "comparisons": [
                {
                    "quantity": c.quantity,
                    "simulation": c.simulation,
                    "unit": c.unit,
                    "reference": None if c.reference is None else {
                        "value": c.reference.value,
                        "uncertainty": c.reference.uncertainty,
                        "source": c.reference.source,
                        "pedigree": c.reference.pedigree,
                    },
                    "comparison_error": c.comparison_error,
                    "validation_uncertainty": c.validation_uncertainty,
                    "verdict": c.verdict.value,
                    "within_part60": c.within_part60,
                    "note": c.note,
                }
                for c in self.comparisons
            ],
            "notes": list(self.notes),
        }
