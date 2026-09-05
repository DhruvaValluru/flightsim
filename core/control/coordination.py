"""Turn coordination gains, measured on the engaging airframe (Package G).

The yaw channel of ``tecs.xml`` was a washed-out yaw-rate damper alone: it
damps Dutch roll without fighting a steady turn, and coordinates nothing.
Measured on the B747 at 3000 m (analysis/flight-dynamics-research-ledger.md,
cycle 1): a 25 deg autopilot turn ran 9% below the coordinated-turn rate
g tan(phi)/V with 1.08 deg of sideslip and a side force of 3.6% of weight --
a physically correct SLIPPING turn, because nothing asked for anything
else. The standard remedy is sideslip (or lateral acceleration) fed to the
rudder beside the damper (Stevens & Lewis; Roskam), which is what this
module tunes.

Measured, not assumed
---------------------
The plant seen by a beta-to-rudder loop is the steady sideslip a rudder
offset produces with the wings held level by the roll channel: the slope
d(beta)/d(rudder) in degrees per unit command, whose sign and size differ
between airframes and with airspeed. It is measured on a throwaway
TECS-equipped instance of the engaging aircraft at its own altitude and
airspeed, with ``ap/yaw/rudder-bias`` as the probe input (the one write
the measurement makes; it exists for this purpose). The proportional gain
is then the one that closes the loop at :data:`LOOP_GAIN`, signed so the
feedback is negative whatever the airframe's convention, and the integral
gain follows from :data:`INTEGRAL_TIME_S`. A probe whose slope is too
small to sign refuses by name (``control.coordination``): guessing a sign
here closes a loop with positive feedback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict

from ..fdm import units as u
from ..fdm.errors import FDMError

#: Closed-loop proportional gain on sideslip: the steady residual is
#: beta_open / (1 + LOOP_GAIN) before the integrator removes it. Swept on
#: the B747 at 3000 m / 230 kt (experiments/airborne/turn_coordination.py
#: and the sweep recorded in docs/AIRBORNE_PHASE2_REPORT.md): 2, 3 and 5
#: all coordinate the turn to within 1.3% of g tan(phi)/V with |beta| <
#: 0.01 deg once the integrator has acted, but the Dutch-roll damping
#: ratio after a rudder pulse falls with the loop gain (0.21 / 0.19 / 0.14
#: with the damper at 1.5; 0.25 / 0.22 / 0.18 at 3.0). 2 keeps the mode
#: at MIL-F-8785C Level 1 (zeta >= 0.19) with margin.
LOOP_GAIN = 2.0

#: Integral time of the coordinator. Slower than the Dutch-roll period
#: (~6 s on the B747) so the integrator does not become a second
#: oscillator; fast enough to zero the sideslip within a heading capture.
INTEGRAL_TIME_S = 4.0

#: The rudder offset the probe applies, and how long it holds it. Small
#: enough to stay linear, long enough for the lateral modes to settle.
PROBE_RUDDER = 0.05
PROBE_SECONDS = 12.0
PROBE_SETTLE_S = 4.0

#: Below this slope the sign cannot be trusted and the loop is refused.
MIN_SLOPE_DEG = 0.5

_CACHE: Dict[tuple, "YawAuthority"] = {}


class CoordinationError(FDMError):
    """The beta-per-rudder slope could not be measured on this airframe."""

    constraint = "control.coordination"


@dataclass(frozen=True)
class YawAuthority:
    aircraft: str
    altitude_m: float
    cas_kt: float
    beta_per_rudder_deg: float    # steady beta (deg) per unit rudder command
    probe_rudder: float
    k_beta: float                 # rudder per deg beta, signed
    ki_beta: float                # rudder per (deg*s) beta, signed

    def as_properties(self) -> Dict[str, float]:
        return {"ap/yaw/k-beta": self.k_beta, "ap/yaw/ki-beta": self.ki_beta}

    def provenance(self) -> Dict[str, Any]:
        return {
            "aircraft": self.aircraft,
            "altitude_m": self.altitude_m,
            "cas_kt": self.cas_kt,
            "beta_per_rudder_deg": self.beta_per_rudder_deg,
            "probe_rudder": self.probe_rudder,
            "loop_gain": LOOP_GAIN,
            "integral_time_s": INTEGRAL_TIME_S,
            "k_beta": self.k_beta,
            "ki_beta": self.ki_beta,
            "claim": "beta-to-rudder gains from the steady sideslip a rudder "
                     "offset produces with wings held level, measured on "
                     "this airframe at this state; sign included",
        }


def measure_yaw_authority(aircraft: str, altitude_m: float, cas_kt: float,
                          use_cache: bool = True) -> YawAuthority:
    """Steady sideslip per unit rudder, wings held level, at this state."""
    key = (aircraft, int(round(altitude_m / 10.0)), int(round(cas_kt)))
    if use_cache and key in _CACHE:
        return _CACHE[key]

    from ..fdm.fdm import FlightDynamics
    from ..fdm.trim import mode_for
    from .autopilot import Autopilot

    fdm = FlightDynamics.with_tecs(aircraft)
    fdm.set_initial_conditions({
        "h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": cas_kt, "gamma-deg": 0.0,
        "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
        "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0,
    })
    fdm.props.set_many({"atmosphere/wind-north-fps": 0.0,
                        "atmosphere/wind-east-fps": 0.0,
                        "atmosphere/wind-down-fps": 0.0,
                        "atmosphere/turb-type": 0.0})
    fdm.start_engines()
    try:
        fdm.trim(mode_for(crosswind=False))
    except FDMError as exc:
        raise CoordinationError(
            f"{aircraft!r}: the coordination probe could not trim at "
            f"{altitude_m:.0f} m / {cas_kt:.0f} kt CAS ({exc})") from exc
    fdm.hold_mass(True)
    autopilot = Autopilot(fdm)
    autopilot.engage(coordinate=False)
    autopilot.command(bank_deg=0.0)

    def hold(seconds: float):
        betas = []
        for i in range(int(round(seconds * fdm.rate_hz))):
            fdm.step()
            if i % 60 == 0:
                autopilot.update()
            betas.append(fdm.props.get("aero/beta-deg"))
        tail = betas[-int(round(PROBE_SETTLE_S * fdm.rate_hz)):]
        return sum(tail) / len(tail)

    beta_zero = hold(PROBE_SECONDS)
    fdm.props.set("ap/yaw/rudder-bias", PROBE_RUDDER)
    beta_probe = hold(PROBE_SECONDS)
    slope = (beta_probe - beta_zero) / PROBE_RUDDER
    if not math.isfinite(slope) or abs(slope) < MIN_SLOPE_DEG:
        raise CoordinationError(
            f"{aircraft!r}: a {PROBE_RUDDER:+.2f} rudder offset moved the "
            f"steady sideslip by only {beta_probe - beta_zero:+.3f} deg at "
            f"{altitude_m:.0f} m / {cas_kt:.0f} kt CAS. The sign of the "
            f"sideslip loop cannot be determined, and guessing it would "
            f"close the loop with positive feedback.")
    k_beta = -LOOP_GAIN / slope
    authority = YawAuthority(
        aircraft=aircraft, altitude_m=float(altitude_m), cas_kt=float(cas_kt),
        beta_per_rudder_deg=float(slope), probe_rudder=PROBE_RUDDER,
        k_beta=float(k_beta), ki_beta=float(k_beta / INTEGRAL_TIME_S))
    _CACHE[key] = authority
    return authority
