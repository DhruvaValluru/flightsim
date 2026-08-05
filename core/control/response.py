"""Step-response characterisation.

Gate 2 requires rise time, overshoot, settling time and steady-state error to be
*reported*, not asserted informally. This module computes them from a recorded
trace so the same numbers back the gate, the tuning loop and the V&V report.

One measurement subtlety that matters here. A large altitude command is rate
limited: the controller clips the demanded climb rate, so the aircraft spends
most of the manoeuvre travelling at a constant rate rather than responding to
the loop at all. Settling time measured across that includes the travel time and
says nothing about the controller. Every response therefore reports whether it
was rate limited, and the acceptance criteria in §6.5 are applied only to
responses that were not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence


@dataclass(frozen=True)
class StepResponse:
    """Classical step-response metrics for one channel."""

    channel: str
    unit: str
    initial: float
    commanded: float
    #: Settling band, as an absolute value in ``unit``.
    band: float
    rise_time_s: float          #: 10% -> 90% of the commanded change
    peak: float
    peak_time_s: float
    overshoot_pct: float
    settling_time_s: float      #: last exit from the settling band
    steady_state_error: float   #: mean over the final tenth of the trace
    rate_limited: bool
    duration_s: float

    @property
    def step(self) -> float:
        return self.commanded - self.initial

    @property
    def settled(self) -> bool:
        return math.isfinite(self.settling_time_s)

    def render(self) -> str:
        settle = (
            f"{self.settling_time_s:6.1f} s" if self.settled else "  never"
        )
        rise = f"{self.rise_time_s:5.1f} s" if math.isfinite(self.rise_time_s) else "   n/a"
        note = "  [rate limited]" if self.rate_limited else ""
        return (
            f"{self.channel:9s} step {self.step:+8.2f} {self.unit:6s} "
            f"rise {rise}  overshoot {self.overshoot_pct:5.1f}%  "
            f"settle(±{self.band:g}) {settle}  sse {self.steady_state_error:+7.3f}{note}"
        )


def characterise(
    times: Sequence[float],
    values: Sequence[float],
    commanded: float,
    channel: str,
    unit: str,
    band: Optional[float] = None,
    band_fraction: float = 0.02,
    rate_limited: bool = False,
) -> StepResponse:
    """Compute step-response metrics from a trace.

    ``band`` defaults to ``band_fraction`` of the step size, floored so that a
    tiny step does not demand an unmeasurably tight band.
    """
    if len(times) != len(values) or not times:
        raise ValueError("times and values must be non-empty and the same length")

    initial = values[0]
    step = commanded - initial
    if band is None:
        band = max(abs(step) * band_fraction, 1e-9)

    # -- rise time: 10% to 90% of the commanded change
    rise_time = math.inf
    if abs(step) > 0:
        lo_target = initial + 0.1 * step
        hi_target = initial + 0.9 * step
        crossed = (lambda v, t: v >= t) if step > 0 else (lambda v, t: v <= t)
        t_lo = t_hi = None
        for t, v in zip(times, values):
            if t_lo is None and crossed(v, lo_target):
                t_lo = t
            if t_hi is None and crossed(v, hi_target):
                t_hi = t
                break
        if t_lo is not None and t_hi is not None:
            rise_time = t_hi - t_lo

    # -- peak and overshoot, measured in the direction of the step
    if step >= 0:
        peak_index = max(range(len(values)), key=lambda i: values[i])
    else:
        peak_index = min(range(len(values)), key=lambda i: values[i])
    peak = values[peak_index]
    overshoot = 0.0
    if abs(step) > 0:
        overshoot = max(0.0, (peak - commanded) / step * 100.0)

    # -- settling time: the last moment the trace leaves the band
    settling = math.inf
    for i in range(len(values) - 1, -1, -1):
        if abs(values[i] - commanded) > band:
            if i + 1 < len(values):
                settling = times[i + 1]
            break
    else:
        settling = times[0]

    # -- steady-state error over the final tenth
    tail = values[max(0, len(values) - max(1, len(values) // 10)):]
    sse = sum(tail) / len(tail) - commanded

    return StepResponse(
        channel=channel,
        unit=unit,
        initial=initial,
        commanded=commanded,
        band=band,
        rise_time_s=rise_time,
        peak=peak,
        peak_time_s=times[peak_index],
        overshoot_pct=overshoot,
        settling_time_s=settling,
        steady_state_error=sse,
        rate_limited=rate_limited,
        duration_s=times[-1] - times[0],
    )


@dataclass(frozen=True)
class Acceptance:
    """§6.5 acceptance criteria, declared before the runs."""

    max_overshoot_pct: float
    max_settling_time_s: float
    max_abs_sse: float
    max_rise_time_s: float = math.inf

    def check(self, response: StepResponse) -> List[str]:
        failures = []
        if response.overshoot_pct > self.max_overshoot_pct:
            failures.append(
                f"overshoot {response.overshoot_pct:.1f}% > "
                f"{self.max_overshoot_pct:.0f}%"
            )
        if not response.settled or response.settling_time_s > self.max_settling_time_s:
            settle = (
                f"{response.settling_time_s:.1f} s" if response.settled else "never"
            )
            failures.append(
                f"settling {settle} > {self.max_settling_time_s:.0f} s "
                f"(band ±{response.band:g} {response.unit})"
            )
        if abs(response.steady_state_error) > self.max_abs_sse:
            failures.append(
                f"steady-state error {response.steady_state_error:+.3f} exceeds "
                f"±{self.max_abs_sse:g} {response.unit}"
            )
        if response.rise_time_s > self.max_rise_time_s:
            failures.append(
                f"rise time {response.rise_time_s:.1f} s > "
                f"{self.max_rise_time_s:.0f} s"
            )
        return failures
