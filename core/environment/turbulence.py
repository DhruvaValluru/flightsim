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
