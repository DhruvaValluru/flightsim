"""A tornado as a kinematic Rankine vortex, honestly scoped.

The wind field is the classical Rankine combined vortex (solid-body
rotation inside the core, circulation-conserving decay outside -- the
textbook first model of tornado tangential wind, e.g. Davies-Jones 1986,
"Tornado dynamics" review) plus a schematic core updraft:

    v_t(r) = v_max * (r / r_core)          r <= r_core
    v_t(r) = v_max * (r_core / r)          r >  r_core
    w(r)   = w_max * (1 - (r/r_core)^2)    r <= r_core, else 0

with the whole field faded linearly to zero between ``top_m`` and
``fade_top_m`` AGL (a funnel does not extend to cruise altitude).

What this is NOT, stated plainly: not a simulated tornado (no dynamics,
no pressure deficit, no debris, no cyclostrophic imbalance); the updraft
profile is schematic (the tangential profile is the cited part); the
wind is point-sampled at the aircraft CG, so a vortex narrower than the
wingspan produces NO differential airloads across the span (the same
stated limit as every other wind field here). v_max and r_core are
documented middle choices in the EF2 band, carried on the card, never
derived in C++.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Tuple

from .base import Position, Term, WindNED, WindProvider

#: Documented middle choices, EF2 band (EF scale: EF2 = 111-135 mph
#: = 50-60 m/s estimated 3-second gust). v_max sits at the band's low
#: edge because this is a MEAN kinematic field, not a gust estimate.
V_MAX_MPS = 50.0
R_CORE_M = 150.0
W_MAX_MPS = 15.0
#: Full-strength ceiling and fade-out top, m AGL. Schematic: observed
#: tornado circulations weaken with height through the parent storm's
#: lowest kilometres.
TOP_M = 1500.0
FADE_TOP_M = 3000.0

STANDARD = ("Rankine combined vortex (solid-body core, 1/r exterior; "
            "Davies-Jones 1986 review); schematic core updraft; "
            "EF2-band v_max as a documented middle choice")


class TornadoVortex(WindProvider):
    """Position-coupled tornado wind at the aircraft, every step."""

    name = "tornado"

    def __init__(self, centre_north_m: float, centre_east_m: float,
                 v_max_mps: float = V_MAX_MPS,
                 r_core_m: float = R_CORE_M,
                 w_max_mps: float = W_MAX_MPS,
                 top_m: float = TOP_M,
                 fade_top_m: float = FADE_TOP_M) -> None:
        if r_core_m <= 0 or v_max_mps < 0 or w_max_mps < 0:
            raise ValueError("tornado parameters must be positive")
        if fade_top_m <= top_m:
            raise ValueError("fade_top_m must sit above top_m")
        self.centre_north_m = float(centre_north_m)
        self.centre_east_m = float(centre_east_m)
        self.v_max_mps = float(v_max_mps)
        self.r_core_m = float(r_core_m)
        self.w_max_mps = float(w_max_mps)
        self.top_m = float(top_m)
        self.fade_top_m = float(fade_top_m)

    # -- the field ------------------------------------------------------

    def decay(self, agl_m: float) -> float:
        """1 below top_m, linear to 0 at fade_top_m."""
        if agl_m <= self.top_m:
            return 1.0
        if agl_m >= self.fade_top_m:
            return 0.0
        return 1.0 - (agl_m - self.top_m) / (self.fade_top_m - self.top_m)

    def wind_components(self, north_m: float, east_m: float,
                        agl_m: float) -> Tuple[float, float, float]:
        """(north, east, down) m/s at a local position. Cyclonic
        (counter-clockwise seen from above, the common NH sense)."""
        dn = north_m - self.centre_north_m
        de = east_m - self.centre_east_m
        r = math.hypot(dn, de)
        fade = self.decay(agl_m)
        if r < 1e-9 or fade == 0.0:
            # Exactly on the axis the tangential wind is zero; the updraft
            # is at its maximum.
            return 0.0, 0.0, -self.w_max_mps * fade if fade else 0.0
        if r <= self.r_core_m:
            v_t = self.v_max_mps * (r / self.r_core_m)
            w_up = self.w_max_mps * (1.0 - (r / self.r_core_m) ** 2)
        else:
            v_t = self.v_max_mps * (self.r_core_m / r)
            w_up = 0.0
        # Counter-clockwise seen from above (cyclonic, NH sense): the
        # velocity is Omega x r with Omega UP, i.e. (north, east) =
        # v_t * (de, -dn) / r. Checked at the rims: north of the centre
        # the flow points WEST, east of the centre it points NORTH.
        north = v_t * (de / r) * fade
        east = v_t * (-dn / r) * fade
        return north, east, -w_up * fade

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        north_m, east_m = self._scene_coords(position)
        n, e, d = self.wind_components(north_m, east_m, position.agl_m)
        return WindNED(n, e, d)

    @staticmethod
    def _scene_coords(position: Position):
        """Local tangent-plane metres, the pre-Phase-4 convention shared
        with OrographicWind._scene_coords."""
        metres_per_degree = 111_320.0
        north = position.latitude_deg * metres_per_degree
        east = (position.longitude_deg * metres_per_degree
                * math.cos(math.radians(position.latitude_deg)))
        return north, east

    # -- the card -------------------------------------------------------

    def card_block(self, origin_x_m: float,
                   origin_y_m: float) -> Dict[str, float]:
        """The run card's ``tornado`` block: every parameter computed here,
        the C++ port derives nothing (the downburst discipline)."""
        return {
            "origin_x_m": float(origin_x_m),
            "origin_y_m": float(origin_y_m),
            "centre_north_m": self.centre_north_m,
            "centre_east_m": self.centre_east_m,
            "v_max_mps": self.v_max_mps,
            "r_core_m": self.r_core_m,
            "w_max_mps": self.w_max_mps,
            "top_m": self.top_m,
            "fade_top_m": self.fade_top_m,
        }

    def vocabulary(self):
        return [
            Term("tornado", self.v_max_mps, "m/s tangential peak", STANDARD,
                 (0.0, 90.0),
                 note=f"Rankine core r={self.r_core_m:g} m; schematic "
                      f"updraft {self.w_max_mps:g} m/s; full strength "
                      f"below {self.top_m:g} m AGL, gone by "
                      f"{self.fade_top_m:g} m; point-sampled at the CG -- "
                      f"no span-differential airloads"),
        ]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "model": "Rankine combined vortex + schematic core updraft",
                "v_max_mps": self.v_max_mps, "r_core_m": self.r_core_m,
                "w_max_mps": self.w_max_mps, "top_m": self.top_m,
                "fade_top_m": self.fade_top_m,
                "centre_north_m": self.centre_north_m,
                "centre_east_m": self.centre_east_m}
