"""Orographic wind: ridge lift, lee sink and rotor.

Physics ported from the previous build's ``terrain_field.py``, which §8 marks as
sound and worth keeping. What changes is the delivery mechanism: there it
computed a number and applied it to a baked trajectory, here it is an
environment provider writing to JSBSim's wind properties every step, so the
aircraft actually flies through the field and the response is emergent.

Terrain is supplied through :class:`TerrainField`, a minimal interface with an
elevation lookup. Phase 4 substitutes a real DEM behind the same interface, at
which point "ridge lift over this ridge" becomes a checkable claim rather than a
precise number about nothing.

Model and its limits
--------------------
1. **Ridge lift.** The linearised lower boundary condition: at the surface the
   flow is tangent to the ground, so a horizontal wind crossing a slope acquires

       w = U . grad(h)

   Standard in mountain meteorology (Smith 1979, *The influence of mountains on
   the atmosphere*, Adv. Geophys. 21, eq. 2.3; Queney 1948). It assumes small
   slopes, steady neutral flow and no separation, so above
   :data:`LINEAR_SLOPE_VALID` the result is saturated rather than believed.

   The perturbation decays with height as exp(-z/H). For neutral irrotational
   flow over sinusoidal terrain the exact potential-flow solution has
   H = L/(2*pi) with L the terrain wavelength (Lamb, *Hydrodynamics*, art. 231).

2. **Lee sink and rotor.** Downwind of a crest the flow separates: the descent
   exceeds the windward ascent and drags a rotor of mechanical turbulence with
   it (FAA AC 00-57; Doyle & Durran 2002, *The dynamics of mountain-wave-induced
   rotors*, J. Atmos. Sci. 59). Linear theory gives neither, so both are added
   explicitly, anchored to the ascent the same crest produced -- a crude
   mass-continuity statement: what the ridge lifted has to come back down.

   Separation is assumed wherever a crest is upstream, with no dependence on
   lee-slope angle, Froude number or inversion strength, all of which control
   whether a real rotor forms at all. This is the weakest part of the model and
   is stated as such in docs/VALIDITY.md.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional

from .base import Position, Term, WindNED, WindProvider

#: Slope beyond which linear theory is saturated rather than trusted.
LINEAR_SLOPE_VALID = 0.35
#: Vertical decay height as a fraction of the terrain wavelength, L/(2*pi).
DECAY_FROM_WAVELENGTH = 1.0 / (2.0 * math.pi)
DECAY_HEIGHT_MIN_M = 80.0
DECAY_HEIGHT_MAX_M = 1500.0

#: Lee descent divided by windward ascent. AC 00-57 puts the lee downdraft as
#: the stronger of the pair.
LEE_SINK_GAIN = 1.3
#: e-folding distance downwind, in crest prominences. The rotor proper sits
#: within 1-3 (Doyle & Durran); trapped lee waves reach ~10. A documented middle
#: choice, not a measured value.
LEE_DECAY_RIDGE_HEIGHTS = 4.0
LEE_SCAN_POINTS = 12
LEE_PROMINENCE_REF_M = 120.0

RIDGE_STANDARD = "Smith 1979 Adv. Geophys. 21 eq. 2.3 (linearised orographic lift)"
LEE_STANDARD = "FAA AC 00-57; Doyle & Durran 2002 J. Atmos. Sci. 59, 186-201"


class TerrainField:
    """Terrain elevation, in local metres about a scene origin.

    Deliberately minimal: an elevation lookup and a dominant wavelength. Phase 4
    implements the same interface over a baked DEM raster, and the orographic
    provider never learns which kind of terrain it is querying -- which is what
    makes terrain statistics a controllable independent variable measured in the
    same units either way (§3.2).
    """

    def __init__(self, elevation: Callable[[float, float], float],
                 wavelength_m: float = 1600.0, name: str = "terrain") -> None:
        self._elevation = elevation
        self.wavelength_m = float(wavelength_m)
        self.name = name

    def elevation_m(self, north_m: float, east_m: float) -> float:
        return float(self._elevation(north_m, east_m))

    def gradient(self, north_m: float, east_m: float,
                 span_m: Optional[float] = None):
        """Central-difference terrain gradient (dh/dn, dh/de), dimensionless."""
        span = span_m if span_m is not None else max(self.wavelength_m / 16.0, 5.0)
        half = span / 2.0
        dn = (self.elevation_m(north_m + half, east_m)
              - self.elevation_m(north_m - half, east_m)) / span
        de = (self.elevation_m(north_m, east_m + half)
              - self.elevation_m(north_m, east_m - half)) / span
        return dn, de

    @classmethod
    def sinusoidal_ridge(cls, amplitude_m: float = 300.0,
                         wavelength_m: float = 4000.0) -> "TerrainField":
        """An analytic ridge, for tests and for the null-test ladder.

        A closed form matters here: the exact potential-flow solution for this
        shape is known, so the provider's output can be checked against theory
        rather than against itself.
        """
        k = 2.0 * math.pi / wavelength_m
        return cls(lambda n, e: amplitude_m * math.cos(k * n),
                   wavelength_m=wavelength_m, name="sinusoidal_ridge")

    @classmethod
    def flat(cls, elevation_m: float = 0.0) -> "TerrainField":
        return cls(lambda n, e: elevation_m, name="flat")


class OrographicWind(WindProvider):
    """Vertical wind forced by terrain, given the local horizontal wind."""

    name = "orographic"

    def __init__(
        self,
        terrain: TerrainField,
        wind_speed_mps: float,
        wind_from_deg: float,
        decay_height_m: Optional[float] = None,
        enable_lee: bool = True,
    ) -> None:
        self.terrain = terrain
        self.wind_speed_mps = float(wind_speed_mps)
        self.wind_from_deg = float(wind_from_deg) % 360.0
        self.enable_lee = enable_lee
        if decay_height_m is None:
            decay_height_m = terrain.wavelength_m * DECAY_FROM_WAVELENGTH
        self.decay_height_m = min(max(decay_height_m, DECAY_HEIGHT_MIN_M),
                                  DECAY_HEIGHT_MAX_M)
        horizontal = WindNED.from_meteorological(self.wind_speed_mps,
                                                 self.wind_from_deg)
        self._wn, self._we = horizontal.north, horizontal.east

    # -- components -----------------------------------------------------

    def linear_updraught(self, north_m: float, east_m: float) -> float:
        """w = U . grad(h), positive UP, saturated on steep slopes."""
        dn, de = self.terrain.gradient(north_m, east_m)
        slope = math.hypot(dn, de)
        w = self._wn * dn + self._we * de
        if slope > LINEAR_SLOPE_VALID:
            w *= LINEAR_SLOPE_VALID / slope
        return w

    def decay(self, agl_m: float) -> float:
        """exp(-z/H): potential-flow decay of the terrain perturbation."""
        return 1.0 if agl_m <= 0.0 else math.exp(-agl_m / self.decay_height_m)

    def lee_sink(self, north_m: float, east_m: float) -> float:
        """Downward velocity from separation behind an upstream crest, m/s."""
        if not self.enable_lee or self.wind_speed_mps < 0.5:
            return 0.0
        # Unit vector pointing upstream: the wind blows from there to here.
        un = -self._wn / self.wind_speed_mps
        ue = -self._we / self.wind_speed_mps
        fetch = max(self.decay_height_m * 6.0, self.terrain.wavelength_m * 1.5)

        here = self.terrain.elevation_m(north_m, east_m)
        best_ascent = 0.0
        best_prominence = 0.0
        best_distance = 0.0
        for i in range(1, LEE_SCAN_POINTS + 1):
            distance = fetch * i / LEE_SCAN_POINTS
            n = north_m + un * distance
            e = east_m + ue * distance
            prominence = self.terrain.elevation_m(n, e) - here
            if prominence <= 0.0:
                continue
            ascent = self.linear_updraught(n, e)
            if ascent > best_ascent:
                best_ascent, best_prominence, best_distance = (
                    ascent, prominence, distance
                )
        if best_ascent <= 0.0:
            return 0.0

        # Fades with crest prominence and with distance downwind.
        prominence_factor = min(best_prominence / LEE_PROMINENCE_REF_M, 1.0)
        decay_length = max(best_prominence * LEE_DECAY_RIDGE_HEIGHTS, 1.0)
        strength = prominence_factor * math.exp(-best_distance / decay_length)
        return LEE_SINK_GAIN * best_ascent * strength

    # -- provider -------------------------------------------------------

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        """Vertical contribution only; the horizontal field is the wind provider's."""
        north_m, east_m = self._scene_coords(position)
        updraught = self.linear_updraught(north_m, east_m)
        sink = self.lee_sink(north_m, east_m)
        w_up = (updraught - sink) * self.decay(position.agl_m)
        # NED down is positive downward, so an updraught is negative down.
        return WindNED(0.0, 0.0, -w_up)

    @staticmethod
    def _scene_coords(position: Position):
        """Local metres from latitude/longitude about the origin.

        A local tangent-plane approximation, which is what the terrain field is
        defined on. Good to well under a metre over the tens of kilometres a
        scene spans, and replaced by the DEM's own georeferencing in Phase 4.
        """
        metres_per_degree = 111_320.0
        north = position.latitude_deg * metres_per_degree
        east = (position.longitude_deg * metres_per_degree
                * math.cos(math.radians(position.latitude_deg)))
        return north, east

    def vocabulary(self) -> List[Term]:
        return [
            Term("ridge lift", "U . grad(h)", "m/s", RIDGE_STANDARD, (0.0, 20.0),
                 note=f"saturated above slope {LINEAR_SLOPE_VALID:g}; "
                      f"decays over {self.decay_height_m:.0f} m"),
            Term("lee sink", LEE_SINK_GAIN, "x windward ascent", LEE_STANDARD,
                 (0.0, 3.0),
                 note=f"fades over {LEE_DECAY_RIDGE_HEIGHTS:g} crest prominences"),
            Term("rotor", "not modelled as turbulence here", None, LEE_STANDARD,
                 note="separation is assumed wherever a crest is upstream, with "
                      "no Froude number or inversion dependence"),
        ]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "terrain": self.terrain.name,
                "terrain_wavelength_m": self.terrain.wavelength_m,
                "wind_speed_mps": self.wind_speed_mps,
                "wind_from_deg": self.wind_from_deg,
                "decay_height_m": self.decay_height_m,
                "lee_enabled": self.enable_lee}
