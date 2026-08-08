"""Convective thermals: Allen's NASA soaring updraft model, faithfully.

Source: Michael J. Allen, *Updraft Model for Development of Autonomous
Soaring Uninhabited Air Vehicles*, NASA/TM-2006-214019 (2006). The model is
implemented from the paper's equations (11)-(23) AND its Appendix B MATLAB
reference code, which produced the paper's own check case (Figure 12). Where
the two disagree, the code wins, because the code is the artifact the check
case verifies:

* Appendix B's ``Kshape`` table has FIVE columns per r1/r2 row and the code
  reads columns 1-4, so the effective k4 values are the fourth column
  (-0.1950 ... -0.0033), NOT the fifth column that the paper's Table 3
  prints as "k4" (0.0008 ... 0.0001). This implementation follows the code
  and records the discrepancy here rather than silently picking one.

Model structure (all from the TM):

* Mean updraft strength w_bar = w* (z/zi)^(1/3) (1 - 1.1 z/zi)   [eq 11]
* Outer radius r2 = max(10, 0.102 (z/zi)^(1/3) (1 - 0.25 z/zi) zi) [eq 12]
* Inner radius from the fitted r1/r2 ratio                        [eq 13]
* Bell-shaped velocity profile with Table-3/Appendix-B constants  [eq 16]
* Toroidal edge downdraft for 0.5 < z/zi < 0.9                [eqs 17-18]
* Updraft count N = 0.6 X Y / (zi r2), Lenschow spacing at
  z/zi = 0.4                                                  [eqs 19-20]
* Environment sink w_e balancing the updraft mass flux         [eqs 21-22]
* Blend to the sink outside the core                              [eq 23]

The **nearest** updraft governs at a query point (Appendix B), not a sum:
thermals do not superpose in this model, the environment sink between them
is the balancing term, and that is exactly what makes the conservation
check meaningful: the area-mean vertical velocity over the field is ~zero.

Placement is DETERMINISTIC from the spec seed: positions are drawn once,
at construction, from ``numpy.random.default_rng(seed)``, uniform over the
stated area. The paper prescribes re-drawing positions every ~20 simulated
minutes; every clip here is far shorter, so placement is static per run and
the manifest records the seed. Thermals are a daytime-convection phenomenon;
w* and zi are inputs (Table 2 gives monthly envelopes -- July mean
w* = 2.69 m/s with zi = 1975 m is the "summer" word used by the matrix).

Limits, stated (VALIDITY.md): the model was fitted to Desert Rock, Nevada
soundings; no wind drift, no merging, no time evolution, no terrain
coupling -- thermals rise from a flat abstract floor at terrain elevation.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import Position, Term, WindNED, WindProvider

STANDARD = "Allen, NASA/TM-2006-214019 (2006), eqs 11-23 + Appendix B"

#: r1/r2 break points and shape constants, Appendix B ``Kshape``. Columns
#: are (k1, k2, k3, k4) as the code reads them; the fifth printed column is
#: unused by the reference implementation (see module docstring).
R1R2_SHAPE = (0.14, 0.25, 0.36, 0.47, 0.58, 0.69, 0.80)
K_SHAPE = (
    (1.5352, 2.5826, -0.0113, -0.1950),
    (1.5265, 3.6054, -0.0176, -0.1265),
    (1.4866, 4.8356, -0.0320, -0.0818),
    (1.2042, 7.7904, 0.0848, -0.0445),
    (0.8816, 13.9720, 0.3404, -0.0216),
    (0.7067, 23.9940, 0.5689, -0.0099),
    (0.6189, 42.7965, 0.7157, -0.0033),
)

#: The month words the matrix uses, from the TM's Table 2 (mean w*, its zi).
SEASON_TABLE = {
    "winter": (1.26, 441.0),    # December mean
    "spring": (1.97, 1213.0),   # April mean
    "summer": (2.69, 1975.0),   # July mean
    "autumn": (1.79, 893.0),    # October mean
}

#: Updraft spacing is Lenschow's at z/zi = 0.4 (eq 19); N is evaluated
#: there once, at construction, because the count cannot follow the query
#: altitude.
SPACING_HEIGHT_RATIO = 0.4


def shape_constants(r1r2: float) -> Tuple[float, float, float, float]:
    """Nearest-breakpoint lookup, exactly as Appendix B's elseif ladder."""
    for i in range(len(R1R2_SHAPE) - 1):
        if r1r2 < 0.5 * (R1R2_SHAPE[i] + R1R2_SHAPE[i + 1]):
            return K_SHAPE[i]
    return K_SHAPE[-1]


class AllenThermals(WindProvider):
    """Convective updraft field over a stated area, per NASA/TM-2006-214019."""

    name = "allen_thermals"

    def __init__(
        self,
        wstar_mps: float,
        zi_m: float,
        area_north_m: float,
        area_east_m: float,
        seed: int,
        origin_north_m: float = 0.0,
        origin_east_m: float = 0.0,
        positions: Optional[Sequence[Tuple[float, float]]] = None,
    ) -> None:
        if wstar_mps < 0:
            raise ValueError("w* cannot be negative")
        if zi_m <= 0:
            raise ValueError("mixing-layer depth zi must be positive")
        self.wstar_mps = float(wstar_mps)
        self.zi_m = float(zi_m)
        self.area_north_m = float(area_north_m)
        self.area_east_m = float(area_east_m)
        self.origin_north_m = float(origin_north_m)
        self.origin_east_m = float(origin_east_m)
        self.seed = int(seed)

        # N from eq (20) at the spacing height ratio; at least one updraft
        # or the provider is pointless and says so.
        r2_spacing = self._r2_m(SPACING_HEIGHT_RATIO * self.zi_m)
        count = round(0.6 * self.area_north_m * self.area_east_m
                      / (self.zi_m * r2_spacing))
        self.count = max(int(count), 1)

        if positions is not None:
            self.positions = tuple((float(n), float(e)) for n, e in positions)
            self.count = len(self.positions)
        else:
            rng = np.random.default_rng(self.seed)
            self.positions = tuple(
                (self.origin_north_m + float(rng.uniform(0, self.area_north_m)),
                 self.origin_east_m + float(rng.uniform(0, self.area_east_m)))
                for _ in range(self.count)
            )

        # Total updraft area must fit inside the stated area (Appendix B
        # refuses too-small test spaces).
        r2_bar = self._r2_m(SPACING_HEIGHT_RATIO * self.zi_m)
        if self.count * math.pi * r2_bar ** 2 >= (self.area_north_m
                                                  * self.area_east_m):
            raise ValueError(
                f"area {self.area_north_m:g} x {self.area_east_m:g} m cannot "
                f"hold {self.count} updrafts of radius {r2_bar:.0f} m")

    # -- the TM's pieces, each a pure function of height/radius ----------

    def w_bar_mps(self, agl_m: float) -> float:
        """Mean updraft velocity, eq (11). Negative above z/zi = 0.909."""
        zzi = agl_m / self.zi_m
        if zzi <= 0.0:
            return 0.0
        return self.wstar_mps * zzi ** (1.0 / 3.0) * (1.0 - 1.1 * zzi)

    def _r2_m(self, agl_m: float) -> float:
        """Outer radius, eq (12), floored at 10 m as the code floors it."""
        zzi = max(agl_m, 0.0) / self.zi_m
        if zzi <= 0.0:
            return 10.0
        return max(10.0, 0.102 * zzi ** (1.0 / 3.0) * (1.0 - 0.25 * zzi)
                   * self.zi_m)

    @staticmethod
    def _r1r2(r2_m: float) -> float:
        """Inner/outer radius ratio, eq (13)."""
        return 0.0011 * r2_m + 0.14 if r2_m < 600.0 else 0.8

    def w_at(self, north_m: float, east_m: float, agl_m: float) -> float:
        """Vertical velocity, positive UP, m/s. Appendix B line for line."""
        if agl_m <= 0.0:
            return 0.0
        zzi = agl_m / self.zi_m

        # Nearest updraft governs.
        distances = [math.hypot(north_m - n, east_m - e)
                     for n, e in self.positions]
        nearest = min(range(len(distances)), key=distances.__getitem__)
        dist = distances[nearest]

        r2 = self._r2_m(agl_m)
        r1r2 = self._r1r2(r2)
        r1 = r1r2 * r2
        w_bar = self.w_bar_mps(agl_m)
        wc = (3.0 * w_bar * (r2 ** 3 - r2 ** 2 * r1)
              / (r2 ** 3 - r1 ** 3))
        rr2 = dist / r2

        # Bell profile, eq (16), only below the mixing layer top.
        if zzi < 1.0:
            k1, k2, k3, k4 = shape_constants(r1r2)
            ws = 1.0 / (1.0 + abs(k1 * rr2 + k3) ** k2) + k4 * rr2
            ws = max(ws, 0.0)
        else:
            ws = 0.0

        # Toroidal edge downdraft, eqs (17)-(18); never positive.
        if dist > r1 and rr2 < 2.0:
            w1 = (math.pi / 6.0) * math.sin(math.pi * rr2)
        else:
            w1 = 0.0
        if 0.5 < zzi <= 0.9:
            swd = 2.5 * (zzi - 0.5)
            wd = min(swd * w1, 0.0)
        else:
            swd = 0.0
            wd = 0.0

        w2 = ws * wc + wd * w_bar

        # Environment sink, eq (21); never positive.
        area = self.area_north_m * self.area_east_m
        at = self.count * math.pi * r2 ** 2
        we = min(-(at * w_bar * (1.0 - swd)) / (area - at), 0.0)

        # Blend to the sink outside the core, eq (23).
        if dist > r1 and wc != 0.0:
            return w2 * (1.0 - we / wc) + we
        return w2

    # -- provider contract ----------------------------------------------

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        north, east = self._scene_coords(position)
        w_up = self.w_at(north, east, position.agl_m)
        return WindNED(0.0, 0.0, -w_up)

    @staticmethod
    def _scene_coords(position: Position) -> Tuple[float, float]:
        metres_per_degree = 111_320.0
        north = position.latitude_deg * metres_per_degree
        east = (position.longitude_deg * metres_per_degree
                * math.cos(math.radians(position.latitude_deg)))
        return north, east

    def vocabulary(self) -> List[Term]:
        terms = [
            Term(season, {"wstar_mps": wstar, "zi_m": zi}, None, STANDARD,
                 note=f"TM Table 2 monthly mean (w* {wstar:g} m/s, "
                      f"zi {zi:g} m); Desert Rock NV climatology")
            for season, (wstar, zi) in SEASON_TABLE.items()
        ]
        terms.append(
            Term("thermal field", self.count, "updrafts", STANDARD,
                 note=f"Lenschow spacing at z/zi = {SPACING_HEIGHT_RATIO}, "
                      f"deterministic placement from seed {self.seed}; "
                      f"nearest updraft governs, environment sink balances "
                      f"(area-mean w ~ 0)"))
        return terms

    def card_block(self, origin_x_m: float, origin_y_m: float) -> Dict[str, Any]:
        """The run card's ``thermals`` block for the UE host's port.

        The origin anchors the local frame in the projected CRS (the same
        convention as every other coupling); positions were drawn once, from
        the spec seed, at construction and travel verbatim. The manifest's
        thermals selftest grid pins the C++ field against :meth:`w_at`.
        """
        return {
            "wstar_mps": self.wstar_mps,
            "zi_m": self.zi_m,
            "area_north_m": self.area_north_m,
            "area_east_m": self.area_east_m,
            "origin_x_m": float(origin_x_m),
            "origin_y_m": float(origin_y_m),
            "positions_m": [list(p) for p in self.positions],
        }

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "wstar_mps": self.wstar_mps, "zi_m": self.zi_m,
                "area_north_m": self.area_north_m,
                "area_east_m": self.area_east_m,
                "origin_north_m": self.origin_north_m,
                "origin_east_m": self.origin_east_m,
                "seed": self.seed, "count": self.count,
                "positions_m": [list(p) for p in self.positions],
                "kshape_source": "Appendix B (columns 1-4; see module note)"}
