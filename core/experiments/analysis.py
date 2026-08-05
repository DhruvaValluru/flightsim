"""Turn a sweep dataset into findings, with the dispersion shown.

Ported in design from the previous build's ``analyze.py``. Three things it does
that a mean-of-each-level table does not.

**Dispersion travels with every response curve.** A level mean without its
spread invites a reader to see a trend in noise. Every point carries its
standard deviation and its n.

**Variance is attributed, not eyeballed.** eta-squared is the fraction of a
metric's total variance explained by each factor -- the categorical analogue of
R-squared, and what §7.5 asks for where factors are levels rather than
continuous. A factor that looks influential on a plot and explains 2% of
variance is noise with a slope.

**Degenerate replication is reported.** See :func:`core.experiments.sweep.degenerate_replicates`.

What this module deliberately does not do is fit a curve and report its
coefficient as a finding. §7.5's pipeline is screening, then sampling, then
attribution; a fit over a handful of levels is a description of those levels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


def _numeric(values: Sequence[Any]) -> List[float]:
    return [float(v) for v in values if isinstance(v, (int, float))
            and not isinstance(v, bool) and math.isfinite(float(v))]


def mean(values: Sequence[float]) -> float:
    values = _numeric(values)
    return sum(values) / len(values) if values else math.nan


def stdev(values: Sequence[float]) -> float:
    """Sample standard deviation. NaN below two samples, rather than zero.

    Zero would read as "no spread measured"; NaN reads as "spread not
    measurable", which is what one sample actually tells you.
    """
    values = _numeric(values)
    if len(values) < 2:
        return math.nan
    m = sum(values) / len(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


@dataclass(frozen=True)
class LevelResponse:
    """One level of one factor, for one metric."""

    level: Any
    n: int
    mean: float
    stdev: float

    @property
    def standard_error(self) -> float:
        return self.stdev / math.sqrt(self.n) if self.n > 1 else math.nan

    def render(self) -> str:
        spread = ("     n/a" if math.isnan(self.stdev)
                  else f"{self.stdev:8.4f}")
        return (f"    {str(self.level):>12}  n={self.n:<3d} "
                f"mean {self.mean:12.4f}  sd {spread}")


@dataclass
class ResponseCurve:
    factor: str
    metric: str
    levels: List[LevelResponse] = field(default_factory=list)
    eta_squared: float = math.nan

    @property
    def spread_of_means(self) -> float:
        return stdev([l.mean for l in self.levels])

    def render(self) -> str:
        lines = [f"  {self.metric} vs {self.factor}   "
                 f"eta^2 = {self.eta_squared:.4f}"]
        lines += [l.render() for l in self.levels]
        return "\n".join(lines)


def eta_squared(groups: Sequence[Sequence[float]]) -> float:
    """Fraction of total variance explained by group membership.

    SS_between / SS_total. Returns NaN when the metric does not vary at all,
    rather than 0 or 1: with no variance to explain, the question has no answer,
    and either number would be an assertion.
    """
    flat = [v for group in groups for v in _numeric(group)]
    if len(flat) < 2:
        return math.nan
    grand = sum(flat) / len(flat)
    ss_total = sum((v - grand) ** 2 for v in flat)
    if ss_total <= 0:
        return math.nan
    ss_between = 0.0
    for group in groups:
        values = _numeric(group)
        if not values:
            continue
        group_mean = sum(values) / len(values)
        ss_between += len(values) * (group_mean - grand) ** 2
    return ss_between / ss_total


def response_curve(rows: Sequence[Dict[str, Any]], factor: str, metric: str
                   ) -> ResponseCurve:
    good = [r for r in rows if r.get("ok")]
    column = factor if factor.startswith("factor.") else f"factor.{factor}"

    buckets: Dict[str, List[float]] = {}
    order: List[Any] = []
    for row in good:
        if column not in row or not isinstance(row.get(metric), (int, float)):
            continue
        key = repr(row[column])
        if key not in buckets:
            buckets[key] = []
            order.append(row[column])
        buckets[key].append(float(row[metric]))

    curve = ResponseCurve(factor=column.replace("factor.", ""), metric=metric)
    try:
        order = sorted(order, key=lambda v: (0, float(v))
                       if isinstance(v, (int, float)) else (1, str(v)))
    except (TypeError, ValueError):
        pass
    for level in order:
        values = buckets[repr(level)]
        curve.levels.append(LevelResponse(level, len(values), mean(values),
                                          stdev(values)))
    curve.eta_squared = eta_squared([buckets[repr(l)] for l in order])
    return curve


def analyse(rows: Sequence[Dict[str, Any]], metrics: Sequence[str],
            factors: Optional[Sequence[str]] = None) -> List[ResponseCurve]:
    """Every metric against every swept factor, ranked by variance explained."""
    good = [r for r in rows if r.get("ok")]
    if factors is None:
        found = set()
        for row in good:
            found.update(k for k in row if k.startswith("factor."))
        factors = sorted(found)

    curves = []
    for factor in factors:
        for metric in metrics:
            curve = response_curve(good, factor, metric)
            if curve.levels:
                curves.append(curve)
    # Largest effect first: a report ordered by variance explained puts the
    # finding at the top instead of wherever the factor happened to be declared.
    return sorted(curves, key=lambda c: (-(c.eta_squared if not math.isnan(c.eta_squared) else -1)))


def replicate_precision(rows: Sequence[Dict[str, Any]], metric: str,
                        confidence: float = 0.95) -> Dict[str, Any]:
    """Achieved confidence-interval half-width, and the N that produced it.

    §7.5 is explicit that replicate count must not be asserted as a round
    number: run a pilot, estimate the variance, then solve for the N that meets
    a target half-width, and **report both the achieved N and the achieved
    half-width**. This reports the achieved side.
    """
    values = _numeric([r.get(metric) for r in rows if r.get("ok")])
    n = len(values)
    if n < 2:
        return {"metric": metric, "n": n, "mean": mean(values),
                "half_width": math.nan,
                "note": "fewer than two usable samples; precision unmeasurable"}
    s = stdev(values)
    # Normal approximation. With the small N a sweep typically affords, a t
    # quantile is the defensible choice; 1.96 understates the interval, so the
    # multiplier used is recorded rather than hidden.
    t = 1.96 if n > 30 else 2.26            # t(0.975, ~9 df)
    return {
        "metric": metric,
        "n": n,
        "mean": mean(values),
        "stdev": s,
        "half_width": t * s / math.sqrt(n),
        "confidence": confidence,
        "multiplier": t,
        "note": "normal/t approximation; N was not chosen to hit a target",
    }
