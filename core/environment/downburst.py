"""Microburst / downburst: the wind-shear encounter, as a checkable field.

The scenario this models is the one that killed Delta 191 at DFW (1985) and
drove the FAA Windshear Training Aid: an aircraft at low altitude crosses a
downburst and sees, in order, a performance-increasing headwind, a downdraft
core, and a performance-decreasing tailwind -- the reversal arriving exactly
when energy is lowest.

The field
---------
Axisymmetric and EXACTLY divergence-free, by construction rather than by
assertion. The radial outflow takes Vicroy's vertical shaping (NASA TM-104053,
1992: ``e^{c1 z/zm} - e^{c2 z/zm}`` with c1 = -0.15, c2 = -3.2175, which peaks
at z = zm -- the height of maximum outflow) and a Gaussian radial envelope;
the vertical component is then DERIVED from incompressible continuity in
cylindrical coordinates:

    u_r(r, z) = (lambda r / 2) e^{-(r/R)^2} p(z/zm)
    w_up(r, z) = -lambda (1 - (r/R)^2) e^{-(r/R)^2} P(z)

with ``p`` the Vicroy shaping, ``P`` its closed-form integral, so that
``div(u) = 0`` identically -- the test suite checks this numerically rather
than trusting the algebra. The structure that falls out is the measured one:
downdraft core inside r < R, a compensating updraft ring outside it, outflow
strongest near zm above the ground and zero at the surface.

What is claimed and what is not (§2.5)
--------------------------------------
* The vertical shaping constants and the outflow-peak height are Vicroy's.
* The radial envelope is a Gaussian of convenience: Vicroy's own radial
  profile differs in form; both peak the outflow near the core radius.
* Magnitudes are scenario inputs. ``outflow_max_mps = 12`` with a 1 km core
  reproduces a severe event's ~25-30 kt headwind-to-tailwind swing and a
  ~14 m/s core downdraft at 300 m AGL -- inside the envelope of measured
  severe microbursts (JAWS campaign; Fujita, *The Downburst*, 1985), and
  recorded per run.
* Like the discrete gust, the SHOWCASE delivery evaluates the field along the
  nominal track as a function of time (the run card's wind schedule). That
  approximation is labeled wherever it is used: the field itself is spatial,
  and this module answers spatial queries.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Position, Term, WindNED, WindProvider

#: Vicroy (NASA TM-104053, 1992) vertical shaping constants. With these, the
#: outflow maximum sits at exactly z = zm (d/dz of the shaping vanishes at
#: zm to four decimal places -- checked in the tests, not assumed).
VICROY_C1 = -0.15
VICROY_C2 = -3.2175

DOWNBURST_STANDARD = (
    "Vicroy NASA TM-104053 (1992) vertical shaping; vertical velocity from "
    "incompressible continuity; magnitudes per JAWS / Fujita 1985 envelopes"
)


def _shaping(zeta: float) -> float:
    """Vicroy's p(z/zm): zero at the ground, max 1-ish at zeta = 1."""
    return math.exp(VICROY_C1 * zeta) - math.exp(VICROY_C2 * zeta)


def _shaping_integral(zeta: float) -> float:
    """Closed-form integral of the shaping from 0 to zeta (in zeta units)."""
    return ((math.exp(VICROY_C1 * zeta) - 1.0) / VICROY_C1
            - (math.exp(VICROY_C2 * zeta) - 1.0) / VICROY_C2)


#: Value of the shaping at its peak (zeta = ln(c1/c2)/(c2-c1), ~1.0).
_PEAK_ZETA = math.log(VICROY_C1 / VICROY_C2) / (VICROY_C2 - VICROY_C1)
_PEAK_SHAPING = _shaping(_PEAK_ZETA)


class Downburst(WindProvider):
    """One downburst, fixed in space, queried by scene position.

    Parameters
    ----------
    centre_north_m, centre_east_m:
        Where the downdraft axis meets the ground, in scene metres.
    core_radius_m:
        R: downdraft inside, compensating updraft ring outside. Measured
        events: 0.5-1.5 km (JAWS).
    outflow_max_mps:
        Peak radial outflow anywhere in the field (at r = R/sqrt(2),
        z = zm). Severe events reach ~15 m/s.
    outflow_height_m:
        zm, the height of maximum outflow. Measured: 50-200 m.
    """

    name = "downburst"

    def __init__(
        self,
        centre_north_m: float,
        centre_east_m: float,
        core_radius_m: float = 1000.0,
        outflow_max_mps: float = 12.0,
        outflow_height_m: float = 150.0,
    ) -> None:
        if core_radius_m <= 0 or outflow_height_m <= 0:
            raise ValueError("core radius and outflow height must be positive")
        if outflow_max_mps < 0:
            raise ValueError("outflow magnitude cannot be negative")
        self.centre_north_m = float(centre_north_m)
        self.centre_east_m = float(centre_east_m)
        self.core_radius_m = float(core_radius_m)
        self.outflow_max_mps = float(outflow_max_mps)
        self.outflow_height_m = float(outflow_height_m)
        # lambda from the commanded outflow peak: u_r maximises at
        # r = R/sqrt(2) (where d/dr of r e^{-(r/R)^2} vanishes) and z = zm.
        radial_peak = (self.core_radius_m / (2.0 * math.sqrt(2.0))) \
            * math.exp(-0.5)
        self._lambda = self.outflow_max_mps / (radial_peak * _PEAK_SHAPING)

    # -- the field ------------------------------------------------------

    def radial_outflow_mps(self, r_m: float, agl_m: float) -> float:
        """u_r: positive away from the axis. Zero at the ground and axis."""
        if agl_m <= 0.0:
            return 0.0
        zeta = agl_m / self.outflow_height_m
        envelope = math.exp(-((r_m / self.core_radius_m) ** 2))
        return 0.5 * self._lambda * r_m * envelope * _shaping(zeta)

    def vertical_mps(self, r_m: float, agl_m: float) -> float:
        """w, positive UP: the continuity-derived downdraft/updraft-ring."""
        if agl_m <= 0.0:
            return 0.0
        zeta = agl_m / self.outflow_height_m
        ratio_sq = (r_m / self.core_radius_m) ** 2
        integral = self.outflow_height_m * _shaping_integral(zeta)
        return -self._lambda * (1.0 - ratio_sq) * math.exp(-ratio_sq) * integral

    def wind_components(self, north_m: float, east_m: float,
                        agl_m: float) -> WindNED:
        """The full NED wind vector at a scene point."""
        dn = north_m - self.centre_north_m
        de = east_m - self.centre_east_m
        r = math.hypot(dn, de)
        outflow = self.radial_outflow_mps(r, agl_m)
        if r < 1e-6:
            north = east = 0.0
        else:
            north = outflow * dn / r
            east = outflow * de / r
        # NED: down positive; the field's w is up-positive.
        return WindNED(north, east, -self.vertical_mps(r, agl_m))

    # -- provider -------------------------------------------------------

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        # Scene coordinates come from the caller's own convention; the
        # showcase evaluates along a nominal track instead (and says so).
        metres_per_degree = 111_320.0
        north = position.latitude_deg * metres_per_degree
        east = (position.longitude_deg * metres_per_degree
                * math.cos(math.radians(position.latitude_deg)))
        return self.wind_components(north, east, position.agl_m)

    def vocabulary(self) -> List[Term]:
        return [
            Term("downburst outflow", self.outflow_max_mps, "m/s peak",
                 DOWNBURST_STANDARD, (0.0, 20.0),
                 note=f"core radius {self.core_radius_m:.0f} m, outflow peak "
                      f"at {self.outflow_height_m:.0f} m AGL"),
            Term("downdraft core", round(-self.vertical_mps(0.0, 2.0 * self.outflow_height_m), 2),
                 "m/s at 2*zm", DOWNBURST_STANDARD, (0.0, 30.0),
                 note="derived from continuity, not set independently"),
            Term("headwind-tailwind swing",
                 round(2.0 * self.outflow_max_mps * 1.943844, 1), "kt across the core",
                 DOWNBURST_STANDARD, (0.0, 80.0),
                 note="the reversal is the hazard: energy lowest as it arrives"),
        ]

    def card_block(self, origin_x_m: float, origin_y_m: float) -> Dict[str, float]:
        """The run card's ``downburst`` block for the UE host's port.

        Every parameter the C++ side needs, computed here; the port derives
        only the closed-form lambda, and the manifest's selftest grid pins
        that derivation against this provider point by point. The origin is
        the projected-CRS anchor of the local north/east frame -- the same
        convention as the orographic block, so the two hosts cannot disagree
        about where the aircraft is.
        """
        return {
            "origin_x_m": float(origin_x_m),
            "origin_y_m": float(origin_y_m),
            "centre_north_m": self.centre_north_m,
            "centre_east_m": self.centre_east_m,
            "core_radius_m": self.core_radius_m,
            "outflow_max_mps": self.outflow_max_mps,
            "outflow_height_m": self.outflow_height_m,
        }

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "centre_north_m": self.centre_north_m,
                "centre_east_m": self.centre_east_m,
                "core_radius_m": self.core_radius_m,
                "outflow_max_mps": self.outflow_max_mps,
                "outflow_height_m": self.outflow_height_m,
                "vertical_shaping": "Vicroy c1=-0.15 c2=-3.2175",
                "divergence_free": "by construction; checked numerically in tests"}
