"""Reference speeds measured from the flight model, not asserted.

§5 Phase 1 requires validation to use "measured lift coefficients to derive
Vs / Vref / Vr rather than asserting them". The distinction matters: a stall
speed copied from a table describes the real aircraft, while a stall speed
measured from the model describes *the thing that is actually going to be
simulated*. Validating a scenario against the former would reject runs the model
can fly and accept runs it cannot.

Method
------
Lift coefficient is read directly rather than inferred. JSBSim exposes the
wind-frame aerodynamic force, so

    CL = F_wz / (qbar * S)

The sign is worth stating because getting it backwards is silent: an inverted
lift curve still produces a CLmax and a stall speed, just at the wrong end of
the sweep. Measured on the B747, ``forces/fwz-aero-lbs`` rises with alpha and
breaks after the peak, which is the lift curve; the ``clipped`` flag below
exists to catch the inverted case, where the maximum lands on a sweep edge.

Sweeping angle of attack at fixed dynamic pressure traces the model's lift
curve, and its maximum is the model's CLmax -- including whatever the aero
tables actually do near the stall, which for a stock model may be a plateau
rather than a break.

    Vs = sqrt( 2 * W / (rho * S * CLmax) )

Caveats, which are the point of docs/VALIDITY.md
------------------------------------------------
This measures the *model*. Stock JSBSim aero tables carry no fidelity guarantee
(§3.3), so a CLmax measured here is not a claim about the real airframe. It is
the right number to validate a scenario against, and the wrong number to quote
in a performance comparison.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..fdm import units as u
from ..fdm.fdm import FlightDynamics

#: Multiple of Vs for the approach reference speed. 14 CFR 25.125 defines the
#: landing reference speed as not less than 1.23 Vsr for transports; 1.3 Vs is
#: the long-standing operational convention and is used here.
VREF_FACTOR = 1.30
VREF_BASIS = "1.30 x Vs (operational convention; cf. 14 CFR 25.125 1.23 Vsr)"

#: Rotation speed. A real Vr depends on runway, weight and thrust; this is a
#: conservative envelope bound, not a performance figure.
VR_FACTOR = 1.10
VR_BASIS = "1.10 x Vs (envelope bound, not a performance calculation)"


@dataclass(frozen=True)
class LiftCurve:
    """A measured lift curve for one aircraft at one condition."""

    aircraft: str
    altitude_m: float
    alphas_deg: Tuple[float, ...]
    cls: Tuple[float, ...]
    cl_max: float
    alpha_at_cl_max_deg: float
    wing_area_m2: float
    #: True if CLmax sits at the edge of the swept range, meaning the tables
    #: never actually broke and the real maximum was not bracketed.
    clipped: bool

    def summary(self) -> str:
        note = " (CLmax at sweep edge -- not bracketed)" if self.clipped else ""
        return (
            f"{self.aircraft}: CLmax {self.cl_max:.3f} at alpha "
            f"{self.alpha_at_cl_max_deg:.1f} deg, S={self.wing_area_m2:.1f} m2{note}"
        )


@dataclass(frozen=True)
class ReferenceSpeeds:
    """Speeds derived from a measured lift curve, at a stated mass."""

    aircraft: str
    mass_kg: float
    altitude_m: float
    cl_max: float
    vs_kt: float           #: 1 g stall, clean, true airspeed
    vref_kt: float
    vr_kt: float
    clipped: bool

    def summary(self) -> str:
        return (
            f"{self.aircraft} at {self.mass_kg:,.0f} kg, {self.altitude_m:.0f} m: "
            f"Vs {self.vs_kt:.0f} kt, Vref {self.vref_kt:.0f} kt, Vr {self.vr_kt:.0f} kt "
            f"(CLmax {self.cl_max:.3f})"
        )


def measure_lift_curve(
    aircraft: str,
    altitude_m: float = 3000.0,
    probe_cas_kt: float = 250.0,
    alpha_min_deg: float = -4.0,
    alpha_max_deg: float = 24.0,
    step_deg: float = 0.5,
) -> LiftCurve:
    """Sweep angle of attack and read the model's lift coefficient at each point.

    The aircraft is re-initialised at each alpha rather than pitched through the
    sweep, so each sample is a static aerodynamic reading with no rate effects
    or history in it.
    """
    fdm = FlightDynamics(aircraft)
    wing_area_m2 = None
    alphas: List[float] = []
    cls: List[float] = []

    alpha = alpha_min_deg
    while alpha <= alpha_max_deg + 1e-9:
        fdm.set_initial_conditions(
            {
                "h-sl-ft": u.m_to_ft(altitude_m),
                "vc-kts": probe_cas_kt,
                "alpha-deg": alpha,
                "phi-deg": 0.0, "psi-true-deg": 0.0, "beta-deg": 0.0,
                "lat-geod-deg": 0.0, "long-gc-deg": 0.0,
                "terrain-elevation-ft": 0.0,
            },
            # Alpha is achieved through the velocity vector and lands within a
            # fraction of a degree; the sweep does not need it exact, only known.
            tolerance=5e-2,
        )
        fdm.step()

        qbar_psf = fdm.props.get("aero/qbar-psf")
        s_sqft = fdm.props.get("metrics/Sw-sqft")
        lift_lbs = fdm.props.get("forces/fwz-aero-lbs")
        if wing_area_m2 is None:
            wing_area_m2 = s_sqft * u.M_PER_FT ** 2

        if qbar_psf > 1e-6:
            alphas.append(fdm.props.get("aero/alpha-deg"))
            cls.append(lift_lbs / (qbar_psf * s_sqft))
        alpha += step_deg

    if not cls:
        raise ValueError(f"no usable lift samples for {aircraft!r}")

    peak = max(range(len(cls)), key=lambda i: cls[i])
    return LiftCurve(
        aircraft=aircraft,
        altitude_m=altitude_m,
        alphas_deg=tuple(alphas),
        cls=tuple(cls),
        cl_max=cls[peak],
        alpha_at_cl_max_deg=alphas[peak],
        wing_area_m2=wing_area_m2,
        clipped=peak in (0, len(cls) - 1),
    )


def air_density_kgm3(altitude_m: float) -> float:
    """ISA density. Used only to convert CLmax into a speed."""
    fdm = FlightDynamics("c172p")
    fdm.set_initial_conditions(
        {"h-sl-ft": u.m_to_ft(altitude_m), "vc-kts": 100.0,
         "lat-geod-deg": 0.0, "long-gc-deg": 0.0, "terrain-elevation-ft": 0.0}
    )
    return u.slugft3_to_kgm3(fdm.props.get("atmosphere/rho-slugs_ft3"))


def reference_speeds(
    aircraft: str,
    mass_kg: float,
    altitude_m: float = 0.0,
    curve: Optional[LiftCurve] = None,
) -> ReferenceSpeeds:
    """Derive Vs / Vref / Vr from a measured lift curve at a stated mass."""
    curve = curve or measure_lift_curve(aircraft, altitude_m=max(altitude_m, 1000.0))
    rho = air_density_kgm3(altitude_m)
    weight_n = mass_kg * u.G0
    vs_mps = math.sqrt(2.0 * weight_n / (rho * curve.wing_area_m2 * curve.cl_max))
    vs_kt = u.mps_to_kt(vs_mps)
    return ReferenceSpeeds(
        aircraft=aircraft,
        mass_kg=mass_kg,
        altitude_m=altitude_m,
        cl_max=curve.cl_max,
        vs_kt=vs_kt,
        vref_kt=vs_kt * VREF_FACTOR,
        vr_kt=vs_kt * VR_FACTOR,
        clipped=curve.clipped,
    )
