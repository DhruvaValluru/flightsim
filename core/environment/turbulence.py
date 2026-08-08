"""Dryden turbulence, driven through JSBSim's own MIL-F-8785C implementation.

Why not reimplement it
----------------------
JSBSim already integrates the Dryden filters at FDM rate and exposes the result
through ``atmosphere/turb-*``. Reimplementing them in Python would run at the
harness rate rather than the integrator's, would not exist in the embedded host,
and would be a second implementation of a standard that is already there.

What the intensity words mean (§2.5)
------------------------------------
MIL-F-8785C defines turbulence intensity differently in two regimes, and this
was measured rather than assumed:

* **Low altitude** (below roughly 1000 ft AGL) the vertical RMS gust velocity is
  set by the wind speed at 20 ft, sigma_w = 0.1 * W20. Measured on the pinned
  build at 60-300 m AGL, sigma_w / W20 came out at 0.107, 0.107 and 0.108 --
  the standard's relation, reproduced.
* **Medium and high altitude** W20 has no effect at all: measured sigma_w was
  identical to three decimal places for W20 of 15, 30, 45 and 75 fps at 1000 m.
  There, intensity is set by the probability-of-exceedence index.

Both facts follow from the standard, and neither is described in the brief's
§6.2, which gives only the W20 route. A vocabulary built on W20 alone would
therefore have produced turbulence that silently ignored its own intensity
setting above 1000 ft -- the §1.6 failure again.

Measured POE ladder (ttMilspec, 1000 m, sigma_w in ft/s):

    index   0      1      2      3      4       5       6       7
    sigma   0.000  1.785  3.603  7.729  10.953  15.905  22.240  27.168
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..fdm import units as u
from .base import Term, TurbulenceProvider

#: JSBSim turbulence models. Confirmed by measurement on the pinned build:
#: 0 and 5 produce nothing, 2 is the Culp model, 3 and 4 are the Dryden pair.
TURB_NONE = 0
TURB_STANDARD = 1
TURB_CULP = 2
TURB_MILSPEC = 3
TURB_TUSTIN = 4

#: Measured vertical RMS gust velocity for each probability-of-exceedence index,
#: at medium altitude, in ft/s. Recorded so the vocabulary below maps to a
#: number that was observed rather than assumed.
POE_SIGMA_W_FPS = (0.000, 1.785, 3.603, 7.729, 10.953, 15.905, 22.240, 27.168)

#: Target vertical RMS gust velocity for each intensity word, ft/s.
#: The conventional aviation bands; the POE index is then chosen as whichever
#: measured value above is closest, and both numbers are published.
TARGET_SIGMA_W_FPS = {
    "none": 0.0,
    "light": 3.0,
    "moderate": 6.0,
    "severe": 12.0,
}
INTENSITY_STANDARD = "MIL-F-8785C Dryden spectrum; low altitude sigma_w = 0.1*W20"

#: Wind speed at 20 ft AGL for each intensity word, in knots. This is the
#: low-altitude route, and matches the example in ASSUMPTIONS §2.6
#: ("moderate ... W20_kt: 30").
W20_KT = {"none": 0.0, "light": 15.0, "moderate": 30.0, "severe": 45.0}

#: Above this height the POE index governs and W20 is ignored (measured).
LOW_ALTITUDE_CEILING_M = 300.0

#: JSBSim stores atmosphere/randomseed as a double and casts to a C int, so
#: values at or above INT_MAX saturate rather than wrap.
MAX_JSBSIM_SEED = 2 ** 31 - 1


def poe_index_for(intensity: str) -> int:
    """The POE index whose measured sigma_w is closest to the intensity band."""
    target = TARGET_SIGMA_W_FPS[intensity]
    if target == 0.0:
        return 0
    return min(range(len(POE_SIGMA_W_FPS)),
               key=lambda i: abs(POE_SIGMA_W_FPS[i] - target))


class DrydenTurbulence(TurbulenceProvider):
    """Continuous turbulence per MIL-F-8785C, via JSBSim's Dryden filters.

    ``model`` selects between the two Dryden implementations. ttTustin uses a
    bilinear-transform discretisation and is the better choice at a fixed
    timestep; ttMilspec is the reference. The Culp model is deliberately not
    offered: it diverged during characterisation, reaching a load factor of
    1.5e9 before the run was killed.
    """

    name = "dryden_turbulence"

    def __init__(
        self,
        intensity: str = "none",
        seed: int = 0,
        model: int = TURB_TUSTIN,
    ) -> None:
        if intensity not in TARGET_SIGMA_W_FPS:
            raise ValueError(
                f"unknown turbulence intensity {intensity!r}; "
                f"known: {sorted(TARGET_SIGMA_W_FPS)}"
            )
        if model not in (TURB_NONE, TURB_MILSPEC, TURB_TUSTIN):
            raise ValueError(
                f"turbulence model {model} is not offered. ttCulp (2) diverges "
                f"and ttStandard (1) produces nothing from milspec parameters."
            )
        # A seed JSBSim cannot represent does not fail, it saturates: anything
        # at or above INT_MAX reads back as 2147483647, so two "different"
        # seeds silently produce identical turbulence. Refusing is the only way
        # this stays visible.
        if not 0 <= int(seed) < MAX_JSBSIM_SEED:
            raise ValueError(
                f"turbulence seed {seed} is outside the range JSBSim can "
                f"represent (0 to {MAX_JSBSIM_SEED - 1}). Larger values "
                f"saturate to INT_MAX and every seed above the limit yields "
                f"the same realisation."
            )
        self.intensity = intensity
        self.seed = int(seed)
        self.model = TURB_NONE if intensity == "none" else model
        self.poe_index = poe_index_for(intensity)
        self.w20_kt = W20_KT[intensity]

    def configure(self) -> Dict[str, float]:
        """Written once at setup. Never inside the step loop."""
        return {
            "atmosphere/turb-type": float(self.model),
            "atmosphere/randomseed": float(self.seed),
            "atmosphere/turbulence/milspec/severity": float(self.poe_index),
            "atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps":
                u.kt_to_fps(self.w20_kt),
        }

    def expected_sigma_w_mps(self, agl_m: float) -> float:
        """Predicted vertical RMS gust velocity, in m/s.

        Uses the low-altitude relation below the measured ceiling and the POE
        ladder above it. The null test checks a measured run against this.
        """
        if self.intensity == "none":
            return 0.0
        if agl_m <= LOW_ALTITUDE_CEILING_M:
            # sigma_w = 0.1 * W20, the standard's low-altitude relation.
            return u.fps_to_mps(0.1 * u.kt_to_fps(self.w20_kt))
        return u.fps_to_mps(POE_SIGMA_W_FPS[self.poe_index])

    def vocabulary(self) -> List[Term]:
        terms = []
        for phrase, target in TARGET_SIGMA_W_FPS.items():
            index = poe_index_for(phrase)
            terms.append(
                Term(
                    phrase=phrase,
                    value=round(u.fps_to_mps(POE_SIGMA_W_FPS[index]), 3),
                    unit="m/s sigma_w",
                    standard=INTENSITY_STANDARD,
                    valid_range=(0.0, 10.0),
                    note=(f"target {target:g} ft/s -> POE index {index} "
                          f"(measured {POE_SIGMA_W_FPS[index]:g} ft/s); "
                          f"W20 {W20_KT[phrase]:g} kt below "
                          f"{LOW_ALTITUDE_CEILING_M:g} m AGL"),
                )
            )
        return terms

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "intensity": self.intensity, "seed": self.seed,
                "jsbsim_turb_type": self.model, "poe_index": self.poe_index,
                "w20_kt": self.w20_kt,
                "measured_sigma_w_fps": POE_SIGMA_W_FPS[self.poe_index]}


class ScheduledDrydenTurbulence(DrydenTurbulence):
    """Turbulence intensity following the clock: the evolving-conditions card.

    Segments are (start_s, intensity word); the current word's W20 is
    written every step, held until the next segment -- and NOTHING else
    moves. The seed is written once (§9's 515 g failure), and severity is
    pinned to the nonzero constant 1.0 forever, because severity 0 is a
    measured master off-switch and mid-run severity changes deliver 2-5x
    the commanded sigma_w (docs/JSBSIM_CORRECTIONS.md §13). The W20 route
    governs below ~300 m AGL only; a schedule flown above the ceiling
    delivers the constant POE index-1 floor instead, so schedule scenarios
    fly low and the vocabulary says so.
    """

    name = "scheduled_dryden_turbulence"

    #: The card's ``turbulence`` word (see LeeRotorTurbulence.card_word).
    card_word = "scheduled"

    def __init__(self, segments, seed: int) -> None:
        segments = [(float(t), str(word)) for t, word in segments]
        if not segments:
            raise ValueError("a turbulence schedule needs at least one segment")
        if segments[0][0] != 0.0:
            raise ValueError("the first schedule segment must start at t=0")
        times = [t for t, _ in segments]
        if times != sorted(times):
            raise ValueError("schedule segments must be in increasing time order")
        for _, word in segments:
            if word not in W20_KT:
                raise ValueError(f"unknown intensity word {word!r} in schedule")
        # The strongest word sets the provider's nominal intensity (for the
        # manifest); delivery is per step through W20.
        strongest = max(segments,
                        key=lambda seg: TARGET_SIGMA_W_FPS[seg[1]])[1]
        super().__init__(intensity=strongest if strongest != "none" else "light",
                         seed=seed, model=TURB_TUSTIN)
        self.segments = segments

    #: Severity pin: nonzero constant, written once (see class docstring).
    PINNED_SEVERITY = 1.0

    def w20_fps_at(self, time_s: float) -> float:
        word = self.segments[0][1]
        for start, name in self.segments:
            if time_s >= start:
                word = name
        return u.kt_to_fps(W20_KT[word])

    def configure(self) -> Dict[str, float]:
        return {
            "atmosphere/turb-type": float(TURB_TUSTIN),
            "atmosphere/randomseed": float(self.seed),
            "atmosphere/turbulence/milspec/severity": self.PINNED_SEVERITY,
            "atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps":
                self.w20_fps_at(0.0),
        }

    def step_writes(self, position, time_s: float) -> Dict[str, float]:
        """W20 only, held until the next segment (§13)."""
        return {"atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps":
                self.w20_fps_at(time_s)}

    def expected_sigma_w_mps(self, agl_m: float,
                             time_s: float = 0.0) -> float:
        if agl_m > LOW_ALTITUDE_CEILING_M:
            return u.fps_to_mps(POE_SIGMA_W_FPS[int(self.PINNED_SEVERITY)])
        return u.fps_to_mps(0.107 * self.w20_fps_at(time_s))

    def card_schedule(self) -> Dict[str, Any]:
        """The run card's ``turbulence_schedule`` block: times + W20 fps only."""
        return {
            "times_s": [t for t, _ in self.segments],
            "w20_fps": [u.kt_to_fps(W20_KT[word]) for _, word in self.segments],
        }

    def vocabulary(self) -> List[Term]:
        terms = super().vocabulary()
        terms.append(Term(
            "schedule", " -> ".join(f"{t:g}s {w}" for t, w in self.segments),
            None, INTENSITY_STANDARD,
            note=(f"delivered per step as W20 only, severity pinned "
                  f"{self.PINNED_SEVERITY:g}, seed written once; the W20 "
                  f"route governs below {LOW_ALTITUDE_CEILING_M:g} m AGL "
                  f"(JSBSIM_CORRECTIONS §13)")))
        return terms

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "schedule": [[t, w] for t, w in self.segments],
                "delivery": "per-step W20, severity pinned, seed once (§13)"}
