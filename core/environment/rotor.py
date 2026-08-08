"""Rotor turbulence in the lee: Dryden intensity coupled to the lee-sink field.

The orographic provider computes where the flow separates behind a crest and
how strongly it descends (``OrographicWind.lee_sink``, FAA AC 00-57; Doyle &
Durran 2002). Its vocabulary has always said the *turbulence* of that rotor
is not modelled. This provider models it, with the mechanism the pinned build
measurably supports and nothing more.

Mechanism, dictated by measurement (docs/JSBSIM_CORRECTIONS.md §13)
-------------------------------------------------------------------
Turbulence intensity that varies mid-run may ONLY be driven through
``windspeed_at_20ft_AGL-fps`` (W20), and only below the ~300 m AGL ceiling
where that route governs: continuous W20 ramps deliver sigma_w tracking the
measured relation sigma_w = 0.107 * W20 with no restart artifacts, while
mid-run POE-severity changes overshoot 2-5x and take tens of seconds to
settle. So this provider

* writes ``severity`` = 1 and the seed exactly once, at configure time
  (severity 0 is a measured master off-switch that silences the W20 route
  too; any nonzero value below the ceiling delivers the identical
  W20-governed sigma_w -- §13);
* re-writes W20 every step from the lee-sink magnitude at the aircraft's
  position;
* is valid below :data:`~core.environment.turbulence.LOW_ALTITUDE_CEILING_M`
  only. Above the ceiling JSBSim ignores W20 (measured, §9), so the coupling
  is gone and the process delivers the constant POE index-1 floor
  (1.785 fps) -- a stated model boundary, recorded in the vocabulary and
  docs/VALIDITY.md, not a silent approximation.

Intensity anchor
----------------
sigma_w = :data:`ROTOR_SIGMA_GAIN` x the local lee descent (after height
decay). Doyle & Durran 2002 (J. Atmos. Sci. 59) simulate rotor circulations
whose turbulent fluctuations are of the same order as the wave's vertical
velocities, so the gain is 1.0: an order-of-magnitude anchor from the rotor
literature, stated as such, not a validated calibration. W20 follows from
the measured relation W20 = sigma_w / 0.107, capped at the vocabulary's
"severe" W20 (45 kt) so the coupling cannot claim intensities outside the
measured ladder.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..fdm import units as u
from .base import Position, Term
from .terrain_field import LEE_STANDARD, OrographicWind
from .turbulence import (
    LOW_ALTITUDE_CEILING_M,
    MAX_JSBSIM_SEED,
    TURB_TUSTIN,
    W20_KT,
    DrydenTurbulence,
)

#: sigma_w per unit lee descent. Doyle & Durran 2002: rotor turbulent
#: fluctuations are of the order of the wave vertical velocity. An anchor,
#: not a calibration.
ROTOR_SIGMA_GAIN = 1.0

#: The measured low-altitude relation on the pinned build (§9, §13).
SIGMA_W_PER_W20 = 0.107

#: W20 never exceeds the "severe" vocabulary word.
W20_CAP_KT = W20_KT["severe"]

#: Severity is a master off-switch at 0 (measured: it silences the W20 route
#: as well) and its nonzero value is irrelevant below the ceiling (severity 1
#: and 3 both deliver 5.481 fps at W20 30 kt / 150 m). Pinned to the smallest
#: value that keeps the process alive; above the ceiling this floor governs.
PINNED_SEVERITY = 1.0

W20_PROP = "atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps"


class LeeRotorTurbulence(DrydenTurbulence):
    """Dryden turbulence whose W20 follows the lee-sink field per step.

    Subclasses :class:`DrydenTurbulence` so the stack treats it as the one
    turbulence provider; the ``intensity`` word sets a *floor* (ambient
    turbulence away from the rotor, "none" for a pure rotor cell) and the
    rotor coupling raises W20 above it wherever the orographic field says the
    flow has separated.
    """

    name = "lee_rotor_turbulence"

    #: The card's ``turbulence`` word. Anything but "none" tells the UE host
    #: to apply the carried configure() writes; the word itself is the
    #: honest description the panel shows.
    card_word = "lee-rotor"

    def __init__(self, orographic: OrographicWind, seed: int,
                 background_intensity: str = "none") -> None:
        super().__init__(intensity=background_intensity, seed=seed,
                         model=TURB_TUSTIN)
        self.orographic = orographic
        self.background_w20_kt = W20_KT[background_intensity]
        # The rotor must be able to raise intensity even when the background
        # word is "none": force the Tustin model on regardless of the word.
        self.model = TURB_TUSTIN

    # -- the coupling ---------------------------------------------------

    def rotor_sigma_w_mps(self, position: Position) -> float:
        """Target sigma_w from the local (height-decayed) lee descent."""
        north_m, east_m = OrographicWind._scene_coords(position)
        sink = self.orographic.lee_sink(north_m, east_m)
        return ROTOR_SIGMA_GAIN * sink * self.orographic.decay(position.agl_m)

    def w20_kt_at(self, position: Position) -> float:
        """W20 delivering max(background, rotor) sigma_w, capped at severe."""
        rotor_w20_kt = u.mps_to_kt(
            u.fps_to_mps(u.mps_to_fps(self.rotor_sigma_w_mps(position))
                         / SIGMA_W_PER_W20))
        return min(max(self.background_w20_kt, rotor_w20_kt), W20_CAP_KT)

    # -- provider contract ----------------------------------------------

    def configure(self) -> Dict[str, float]:
        """Seed, model and a constant severity of 1, written once.

        Severity never moves mid-run (the POE route is the one the pinned
        build cannot drive, §13). It cannot be zero either: severity 0 is a
        master off-switch that silences the W20 route too, and any nonzero
        value below the ceiling delivers the identical W20-governed sigma_w
        (measured, §13: severity 1 and 3 both give 5.481 fps at W20 30 kt).
        So it is pinned to 1.0, and intensity is delivered entirely through
        the per-step W20 writes.
        """
        return {
            "atmosphere/turb-type": float(self.model),
            "atmosphere/randomseed": float(self.seed),
            "atmosphere/turbulence/milspec/severity": PINNED_SEVERITY,
            W20_PROP: u.kt_to_fps(self.background_w20_kt),
        }

    def step_writes(self, position: Position, time_s: float) -> Dict[str, float]:
        """The per-step W20 write. Never the seed, never severity (§13)."""
        return {W20_PROP: u.kt_to_fps(self.w20_kt_at(position))}

    def expected_sigma_w_mps(self, agl_m: float,
                             position: Position = None) -> float:
        """sigma_w the coupling claims at a position, for the null test.

        Above the ceiling the W20 route is inert, so the coupling is gone
        and the process delivers the constant POE index-1 floor -- the
        stated model boundary, not zero and not the rotor.
        """
        if agl_m > LOW_ALTITUDE_CEILING_M:
            from .turbulence import POE_SIGMA_W_FPS
            return u.fps_to_mps(POE_SIGMA_W_FPS[int(PINNED_SEVERITY)])
        if position is None:
            return u.fps_to_mps(SIGMA_W_PER_W20
                                * u.kt_to_fps(self.background_w20_kt))
        return u.fps_to_mps(SIGMA_W_PER_W20
                            * u.kt_to_fps(self.w20_kt_at(position)))

    def vocabulary(self) -> List[Term]:
        return [
            Term("rotor turbulence", ROTOR_SIGMA_GAIN, "x lee descent",
                 LEE_STANDARD, (0.0, u.kt_to_mps(W20_CAP_KT) * 0.107),
                 note=(f"sigma_w = gain x local lee sink, delivered as "
                       f"W20 = sigma_w/{SIGMA_W_PER_W20:g} (measured relation), "
                       f"capped at W20 {W20_CAP_KT:g} kt; coupling valid below "
                       f"{LOW_ALTITUDE_CEILING_M:g} m AGL only -- above it the "
                       f"W20 route is inert and the process delivers the "
                       f"constant POE index-1 floor (1.785 fps), not the rotor "
                       f"(JSBSIM_CORRECTIONS §13)")),
        ]

    def card_block(self) -> Dict[str, float]:
        """The run card's ``rotor`` block: the constants of the coupling.

        The C++ mirror computes W20 from the SAME lee-sink field (its
        FFlightSimOrographicWind port, cross-checked separately) and these
        four numbers; the manifest's rotor selftest grid pins the combined
        result against :meth:`w20_kt_at` point by point. The configure()
        writes (pinned severity, seed, model) travel separately as
        turbulence_properties.
        """
        return {
            "sigma_gain": ROTOR_SIGMA_GAIN,
            "sigma_per_w20": SIGMA_W_PER_W20,
            "w20_cap_fps": u.kt_to_fps(W20_CAP_KT),
            "background_w20_fps": u.kt_to_fps(self.background_w20_kt),
        }

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "coupling": "lee_sink -> W20 (per-step), severity pinned 1",
                "rotor_sigma_gain": ROTOR_SIGMA_GAIN,
                "sigma_w_per_w20": SIGMA_W_PER_W20,
                "w20_cap_kt": W20_CAP_KT,
                "background_intensity": self.intensity,
                "valid_below_agl_m": LOW_ALTITUDE_CEILING_M,
                "orographic": self.orographic.provenance()}
