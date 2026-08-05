"""NASA-STD-7009 credibility assessment.

§7.1: grade each subsystem 0-4 on each factor, publish the scorecard every
release, and **state the acceptance threshold in advance**. The last clause is
the one that does the work. A scorecard scored after the fact, against no
threshold, is a way of describing whatever was built as adequate.

The eight factors below follow NASA-STD-7009A, split into the two groups the
standard uses: factors describing the *model* (how it was built and checked) and
factors describing a *result* (how it was used and how well its uncertainty is
understood).

Levels, as the standard defines them:

    0  insufficient evidence to score
    1  informal / self-assessed
    2  some formal process, partially documented
    3  formal process, documented, independently reviewed in part
    4  formal, documented, independently reviewed, and recommended practice

A score of 0 is a real score, not a failure to fill in the form. Most of this
table is 0-2 and it should stay that way until the work that would raise it has
actually been done.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: Factors describing how the model was built and checked.
CAPABILITY_FACTORS = (
    "verification",
    "validation",
    "input_pedigree",
    "results_uncertainty",
)
#: Factors describing how a result was produced and reviewed.
PROCESS_FACTORS = (
    "results_robustness",
    "use_history",
    "m_and_s_management",
    "people_qualification",
)
ALL_FACTORS = CAPABILITY_FACTORS + PROCESS_FACTORS

LEVEL_MEANING = {
    0: "insufficient evidence",
    1: "informal, self-assessed",
    2: "some formal process, partly documented",
    3: "formal, documented, partly independently reviewed",
    4: "formal, documented, independently reviewed, recommended practice",
}

STANDARD = "NASA-STD-7009A credibility assessment scale"


@dataclass
class SubsystemScore:
    """One subsystem, scored on every factor, with the evidence for each."""

    subsystem: str
    scores: Dict[str, int] = field(default_factory=dict)
    evidence: Dict[str, str] = field(default_factory=dict)

    def set(self, factor: str, level: int, evidence: str) -> "SubsystemScore":
        if factor not in ALL_FACTORS:
            raise KeyError(f"unknown factor {factor!r}; known: {ALL_FACTORS}")
        if not 0 <= level <= 4:
            raise ValueError(f"level must be 0-4, got {level}")
        if not evidence.strip():
            raise ValueError(
                f"{self.subsystem}.{factor}: a score without evidence is an "
                f"opinion. Cite what supports it."
            )
        self.scores[factor] = level
        self.evidence[factor] = evidence.strip()
        return self

    @property
    def minimum(self) -> int:
        """The lowest factor score.

        Reported alongside the mean because credibility does not average: a
        subsystem with excellent verification and no validation is not
        "moderately credible", it is unvalidated.
        """
        return min(self.scores.values()) if self.scores else 0

    @property
    def mean(self) -> float:
        return (sum(self.scores.values()) / len(self.scores)
                if self.scores else 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "scores": dict(self.scores),
            "evidence": dict(self.evidence),
            "minimum": self.minimum,
            "mean": round(self.mean, 2),
        }


@dataclass
class Scorecard:
    """The published credibility assessment, with its threshold."""

    title: str
    #: Declared BEFORE scoring. §7.1: "state the acceptance threshold in
    #: advance".
    threshold: int
    threshold_rationale: str
    subsystems: List[SubsystemScore] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def add(self, score: SubsystemScore) -> "Scorecard":
        self.subsystems.append(score)
        return self

    def below_threshold(self) -> List[Dict[str, Any]]:
        out = []
        for subsystem in self.subsystems:
            for factor, level in sorted(subsystem.scores.items()):
                if level < self.threshold:
                    out.append({"subsystem": subsystem.subsystem,
                                "factor": factor, "level": level})
        return out

    @property
    def meets_threshold(self) -> bool:
        return not self.below_threshold()

    def render(self) -> str:
        lines = [self.title, "=" * len(self.title), "",
                 f"standard: {STANDARD}",
                 f"acceptance threshold: {self.threshold} "
                 f"({LEVEL_MEANING[self.threshold]})",
                 f"rationale: {self.threshold_rationale}", ""]

        width = max((len(s.subsystem) for s in self.subsystems), default=10) + 1
        header = "  " + "subsystem".ljust(width)
        header += "".join(f"{f[:11]:>13}" for f in ALL_FACTORS)
        lines.append(header)
        lines.append("  " + "-" * (width + 13 * len(ALL_FACTORS)))
        for subsystem in self.subsystems:
            row = "  " + subsystem.subsystem.ljust(width)
            for factor in ALL_FACTORS:
                level = subsystem.scores.get(factor)
                row += f"{('-' if level is None else str(level)):>13}"
            lines.append(row)

        lines.append("")
        lines.append("  evidence:")
        for subsystem in self.subsystems:
            for factor in ALL_FACTORS:
                if factor in subsystem.evidence:
                    lines.append(f"    {subsystem.subsystem}.{factor} = "
                                 f"{subsystem.scores[factor]}: "
                                 f"{subsystem.evidence[factor]}")

        below = self.below_threshold()
        lines.append("")
        if below:
            lines.append(f"  {len(below)} factor(s) below the declared "
                         f"threshold of {self.threshold}:")
            for item in below:
                lines.append(f"    {item['subsystem']}.{item['factor']} = "
                             f"{item['level']}")
            lines.append("")
            lines.append("  This is the expected state for a system at this "
                         "stage. It is published rather than withheld because "
                         "a scorecard exists to say where the model is weak.")
        else:
            lines.append(f"  every factor meets the threshold of {self.threshold}")

        for note in self.notes:
            lines.append(f"\n  note: {note}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "standard": STANDARD,
            "threshold": self.threshold,
            "threshold_rationale": self.threshold_rationale,
            "level_meaning": LEVEL_MEANING,
            "subsystems": [s.to_dict() for s in self.subsystems],
            "below_threshold": self.below_threshold(),
            "meets_threshold": self.meets_threshold,
            "notes": list(self.notes),
        }

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=1))
        return path
